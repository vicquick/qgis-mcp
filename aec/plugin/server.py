"""
QGIS MCP Server — Non-blocking socket server with newline-delimited JSON framing.

Accepts commands from the MCP proxy and dispatches to registered handler functions.
QGIS 4.x / Qt6 — verified on 4.2.1
"""

import json
import socket
import traceback

from qgis.core import Qgis, QgsMessageLog, QgsProject, QgsMapLayer, QgsRectangle
from qgis.gui import QgisInterface
from qgis.PyQt.QtCore import QObject, QTimer


GEOMETRY_TYPE_NAMES = {
    Qgis.GeometryType.Point: "point",
    Qgis.GeometryType.Line: "line",
    Qgis.GeometryType.Polygon: "polygon",
    Qgis.GeometryType.Unknown: "unknown",
    Qgis.GeometryType.Null: "null",
}


class QgisMCPServer(QObject):
    """Socket server that accepts MCP commands and dispatches to registered handlers."""

    def __init__(self, host: str = "0.0.0.0", port: int = 9877, iface: QgisInterface = None):
        super().__init__()
        self.host = host
        self.port = port
        self.iface = iface
        self.running = False
        self._socket: socket.socket | None = None
        self._client: socket.socket | None = None
        self._buffer = b""
        self._timer: QTimer | None = None
        self._HANDLERS: dict = {}

    def start(self) -> bool:
        """Start listening for connections."""
        # Register all handlers before starting
        from .handlers import register_all_handlers
        register_all_handlers(self)

        self.running = True
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self._socket.bind((self.host, self.port))
            self._socket.listen(1)
            self._socket.setblocking(False)
            self._timer = QTimer()
            self._timer.timeout.connect(self._process)
            self._timer.start(100)
            QgsMessageLog.logMessage(
                f"MCP server started on {self.host}:{self.port} "
                f"({len(self._HANDLERS)} handlers registered)",
                "QGIS MCP", Qgis.MessageLevel.Info,
            )
            return True
        except Exception as e:
            QgsMessageLog.logMessage(
                f"Failed to start server: {e}", "QGIS MCP", Qgis.MessageLevel.Critical,
            )
            self.stop()
            return False

    def stop(self):
        """Stop the server and clean up."""
        self.running = False
        if self._timer:
            self._timer.stop()
            self._timer = None
        if self._client:
            self._client.close()
            self._client = None
        if self._socket:
            self._socket.close()
            self._socket = None
        self._buffer = b""
        QgsMessageLog.logMessage("MCP server stopped", "QGIS MCP", Qgis.MessageLevel.Info)

    def _process(self):
        """Timer callback: accept connections and read commands."""
        if not self.running:
            return
        try:
            # Accept new connections.
            #
            # Always attempt the accept, even while a client is held. This used
            # to accept only when self._client was None, so a client that died
            # abruptly — an MCP server killed rather than shut down — left a
            # half-open socket in that slot forever. Nothing arrives on a dead
            # peer for recv() to fail on, so the slot was never released and
            # every later connection was refused: the bridge stayed wedged
            # until the plugin was stopped and started by hand.
            #
            # A newer connection therefore takes over from an older one. Only
            # one MCP server talks to this plugin at a time, so the newcomer is
            # by definition the live one.
            if self._socket:
                try:
                    new_client, addr = self._socket.accept()
                    new_client.setblocking(False)
                    # Let the OS notice a peer that vanishes without a FIN.
                    try:
                        new_client.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
                    except Exception:
                        pass
                    if self._client:
                        QgsMessageLog.logMessage(
                            "Replacing a previous client connection",
                            "QGIS MCP", Qgis.MessageLevel.Info,
                        )
                        try:
                            self._client.close()
                        except Exception:
                            pass
                        self._buffer = b""
                    self._client = new_client
                    QgsMessageLog.logMessage(
                        f"Client connected: {addr}", "QGIS MCP", Qgis.MessageLevel.Info,
                    )
                except BlockingIOError:
                    pass
                except Exception as e:
                    QgsMessageLog.logMessage(
                        f"Accept error: {e}", "QGIS MCP", Qgis.MessageLevel.Warning,
                    )

            # Read from client — newline-delimited JSON framing
            if self._client:
                try:
                    data = self._client.recv(65536)
                    if data:
                        self._buffer += data
                        while b"\n" in self._buffer:
                            line, self._buffer = self._buffer.split(b"\n", 1)
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                command = json.loads(line.decode("utf-8"))
                            except json.JSONDecodeError as e:
                                QgsMessageLog.logMessage(
                                    f"Invalid JSON: {e}", "QGIS MCP", Qgis.MessageLevel.Warning,
                                )
                                continue
                            response = self._execute(command)
                            self._client.sendall(
                                json.dumps(response).encode("utf-8") + b"\n"
                            )
                    else:
                        QgsMessageLog.logMessage(
                            "Client disconnected", "QGIS MCP", Qgis.MessageLevel.Info,
                        )
                        self._client.close()
                        self._client = None
                        self._buffer = b""
                except BlockingIOError:
                    pass
                except Exception as e:
                    QgsMessageLog.logMessage(
                        f"Client error: {e}", "QGIS MCP", Qgis.MessageLevel.Warning,
                    )
                    if self._client:
                        self._client.close()
                        self._client = None
                    self._buffer = b""
        except Exception as e:
            QgsMessageLog.logMessage(
                f"Server error: {e}", "QGIS MCP", Qgis.MessageLevel.Critical,
            )

    def _execute(self, command: dict) -> dict:
        """Dispatch a command to the appropriate handler."""
        cmd_type = command.get("type", "")
        params = command.get("params", {})
        handler = self._HANDLERS.get(cmd_type)
        if not handler:
            return {"status": "error", "message": f"Unknown command: {cmd_type}"}
        try:
            QgsMessageLog.logMessage(
                f"Executing: {cmd_type}", "QGIS MCP", Qgis.MessageLevel.Info,
            )
            return {"status": "success", "result": handler(**params)}
        except Exception as e:
            tb = traceback.format_exc()
            QgsMessageLog.logMessage(
                f"Error in {cmd_type}: {e}\n{tb}", "QGIS MCP", Qgis.MessageLevel.Critical,
            )
            return {"status": "error", "message": str(e), "traceback": tb}

    # ── Utility methods used by handlers ─────────────────────────

    @staticmethod
    def layer_type_str(layer: QgsMapLayer) -> str:
        """Return a human-readable layer type string."""
        lt = layer.type()
        if lt == Qgis.LayerType.Vector:
            gt = layer.geometryType()
            return f"vector_{GEOMETRY_TYPE_NAMES.get(gt, str(int(gt)))}"
        if lt == Qgis.LayerType.Raster:
            return "raster"
        if lt == Qgis.LayerType.Mesh:
            return "mesh"
        if lt == Qgis.LayerType.PointCloud:
            return "pointcloud"
        if lt == Qgis.LayerType.VectorTile:
            return "vectortile"
        if lt == Qgis.LayerType.Annotation:
            return "annotation"
        if lt == Qgis.LayerType.Group:
            return "group"
        return str(lt)

    @staticmethod
    def get_layer_or_raise(layer_id: str) -> QgsMapLayer:
        """Look up a layer by ID and raise if not found."""
        layer = QgsProject.instance().mapLayer(layer_id)
        if not layer:
            raise RuntimeError(f"Layer not found: {layer_id}")
        return layer

    @staticmethod
    def extent_to_dict(extent: QgsRectangle) -> dict:
        """Convert a QgsRectangle to a serializable dict."""
        return {
            "xmin": extent.xMinimum(),
            "ymin": extent.yMinimum(),
            "xmax": extent.xMaximum(),
            "ymax": extent.yMaximum(),
        }
