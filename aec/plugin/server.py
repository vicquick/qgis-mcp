"""
QGIS MCP Server — Non-blocking socket server with newline-delimited JSON framing.

Accepts commands from the MCP proxy and dispatches to registered handler functions.
QGIS 4.x / Qt6 — verified on 4.2.1
"""

import errno
import json
import os
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


def _env_int(name: str, default: int) -> int:
    """Read an int env var, falling back to `default` if unset or not an int."""
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


# A single fixed port means only one QGIS instance can ever be controlled at
# a time. QGIS_MCP_PORT/QGIS_MCP_PORT_SPAN mirror the bridge's own env vars
# (see aec/server/qgis_mcp_server.py) so a value set for one side holds for
# the other: this is the *start* of a range, not a fixed port — start()
# below binds the first free port in [port, port + port_span).
DEFAULT_PORT_START = _env_int("QGIS_MCP_PORT", 9877)
DEFAULT_PORT_SPAN = _env_int("QGIS_MCP_PORT_SPAN", 10)


class QgisMCPServer(QObject):
    """Socket server that accepts MCP commands and dispatches to registered handlers."""

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = None,
        port_span: int = None,
        iface: QgisInterface = None,
    ):
        super().__init__()
        self.host = host
        # `port` starts out as the requested/first-tried port; start() below
        # rewrites it to whichever port in the range actually got bound, so
        # callers must read it back (self.server.port) only after start().
        self.port = DEFAULT_PORT_START if port is None else port
        self.port_span = max(1, DEFAULT_PORT_SPAN if port_span is None else port_span)
        self.iface = iface
        self.running = False
        self._socket: socket.socket | None = None
        self._client: socket.socket | None = None
        self._buffer = b""
        self._timer: QTimer | None = None
        self._HANDLERS: dict = {}

    def start(self) -> bool:
        """Start listening for connections.

        Tries every port in [self.port, self.port + self.port_span) in turn
        and binds the first free one, so a second (third, ...) QGIS instance
        on the same machine lands on the next port instead of failing to
        start. self.port is updated to whatever actually got bound.
        """
        # Register all handlers before starting
        from .handlers import register_all_handlers
        register_all_handlers(self)

        self.running = True
        port_start = self.port
        # Clamp to the valid TCP port range. self.port_span defaults to 10, but
        # ui.py's spin box allows a start port up to 65535, and a start port
        # above 65526 would otherwise put candidates past 65535 into bind()'s
        # (host, port) tuple — raising OverflowError, which is NOT an OSError
        # and is not caught below, so it would propagate out of start()
        # uncaught instead of hitting the graceful "failed to bind" path.
        port_end = min(port_start + self.port_span, 65536)
        bound_socket = None
        last_error: Exception | None = None
        for candidate in range(port_start, port_end):
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            # Deliberately NOT setting SO_REUSEADDR before this bind-probe.
            # On Windows, SO_REUSEADDR lets bind() succeed even when another
            # process already has this port bound and LISTENing — it does
            # not raise the WSAEADDRINUSE this loop depends on to detect
            # "taken" and advance to the next candidate. Setting it here
            # used to mean a second QGIS instance could silently "bind" the
            # same port as the first (self.port ends up identical for both,
            # and only one process's accept() ever actually receives
            # traffic) with no error logged anywhere, since bind() reported
            # success. Let a genuinely-in-use port fail the probe as
            # intended; there's no listening socket of our own from a prior
            # run to recover via TIME_WAIT here (stop() closes ours before
            # any restart would call start() again).
            try:
                sock.bind((self.host, candidate))
            except (OSError, OverflowError) as e:
                last_error = e
                sock.close()
                # Only "this port is already in use" is the expected,
                # silently-skip-and-try-next-port case. Anything else
                # (permission denied, bad address, ...) is a real
                # configuration/environment problem — log it immediately
                # instead of only surfacing it if every candidate in the
                # span happens to fail too, which could otherwise mask the
                # true cause behind an apparently successful start on some
                # later port.
                in_use = (
                    isinstance(e, OSError)
                    and (e.errno == errno.EADDRINUSE or getattr(e, "winerror", None) == 10048)
                )
                if not in_use:
                    QgsMessageLog.logMessage(
                        f"Unexpected error binding port {candidate}, trying next: {e}",
                        "QGIS MCP", Qgis.MessageLevel.Warning,
                    )
                continue
            bound_socket = sock
            self.port = candidate
            break

        if bound_socket is None:
            self.running = False
            QgsMessageLog.logMessage(
                f"Failed to bind any port in "
                f"{port_start}-{port_end - 1}: {last_error}",
                "QGIS MCP", Qgis.MessageLevel.Critical,
            )
            return False

        self._socket = bound_socket
        try:
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
