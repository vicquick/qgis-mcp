"""
QGIS MCP Server — Non-blocking socket server with newline-delimited JSON framing.

Accepts commands from the MCP proxy and dispatches to registered handler functions.
QGIS 4.x / Qt6 — verified on 4.2.1
"""

import errno
import hashlib
import hmac
import inspect
import json
import os
import socket
import traceback

from qgis.core import Qgis, QgsApplication, QgsMessageLog, QgsProject, QgsMapLayer, QgsRectangle
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
        self._sig_cache: dict = {}
        # Set by the dock: stop, reload modules, start again (reload_plugin).
        self.request_restart = None
        # Optional shared secret. Unset (the default) = no check at all. When
        # set, every command must carry the same value as "_token": the socket
        # binds to localhost, but any local process could otherwise drive
        # QGIS, execute_code included. Env wins over the QGIS setting.
        self._token = os.environ.get("QGIS_MCP_TOKEN") or ""
        if not self._token:
            try:
                from qgis.PyQt.QtCore import QSettings
                self._token = QSettings().value("QgisMCP/token", "", type=str) or ""
            except Exception:
                self._token = ""

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
        """Dispatch a command to the appropriate handler.

        Besides {status, result} the reply says what the call did to the
        project, so an agent can chain the next step without a separate
        get_layers/get_message_log round trip:
          layers_added / layers_removed  [{id, name}] — ids for the next call
          notices          QGIS warnings/errors logged while the handler ran
          ignored_params   arguments the handler swallowed in its **_ catch-all
          context_changed  + rev: the project fingerprint (see context_rev)
                           moved, so a cached get_context answer is stale
        Keys appear only when they carry something.
        """
        if self._token and not hmac.compare_digest(
                str(command.get("_token", "")).encode("utf-8"), self._token.encode("utf-8")):
            return {"status": "error", "code": "AUTH",
                    "message": "this QGIS MCP plugin requires a token (QGIS_MCP_TOKEN)"}
        cmd_type = command.get("type", "")
        params = command.get("params") or {}
        handler = self._HANDLERS.get(cmd_type)
        if not handler:
            return {"status": "error", "message": f"Unknown command: {cmd_type}"}
        ignored = self._ignored_params(handler, params)
        project = QgsProject.instance()
        before = {lid: l.name() for lid, l in project.mapLayers().items()}
        rev_before = self.context_rev()
        notices = []

        # Scoped to this one call: connected right before the handler runs and
        # disconnected in finally. Everything happens on the main thread (the
        # QTimer slot), so log lines from another call cannot land here; lines
        # a worker thread logs are queued and arrive after we disconnect.
        def on_message(message, tag, level):
            try:
                # Membership, not `<`: QGIS 4 enums are not guaranteed ordered.
                if tag == "QGIS MCP" or level not in (
                        Qgis.MessageLevel.Warning, Qgis.MessageLevel.Critical):
                    return
                if len(notices) < 20:
                    text = str(message)
                    notices.append(f"[{tag or 'QGIS'}] {text[:300]}")
            except Exception:
                pass

        log = QgsApplication.messageLog()
        log.messageReceived.connect(on_message)
        try:
            QgsMessageLog.logMessage(
                f"Executing: {cmd_type}", "QGIS MCP", Qgis.MessageLevel.Info,
            )
            response = {"status": "success", "result": handler(**params)}
        except Exception as e:
            tb = traceback.format_exc()
            QgsMessageLog.logMessage(
                f"Error in {cmd_type}: {e}\n{tb}", "QGIS MCP", Qgis.MessageLevel.Critical,
            )
            response = {"status": "error", "message": str(e), "traceback": tb}
        finally:
            try:
                log.messageReceived.disconnect(on_message)
            except Exception:
                pass

        try:
            after = {lid: l.name() for lid, l in project.mapLayers().items()}
            added = [{"id": lid, "name": n} for lid, n in after.items() if lid not in before]
            removed = [{"id": lid, "name": n} for lid, n in before.items() if lid not in after]
            if added:
                response["layers_added"] = added
            if removed:
                response["layers_removed"] = removed
            if notices:
                response["notices"] = notices
            if ignored:
                response["ignored_params"] = ignored
            rev_after = self.context_rev()
            if rev_after != rev_before:
                response["context_changed"] = True
                response["rev"] = rev_after
        except Exception as e:
            # The envelope is a convenience; never let it turn a call that
            # succeeded into a failure.
            QgsMessageLog.logMessage(
                f"Envelope for {cmd_type} failed: {e}", "QGIS MCP", Qgis.MessageLevel.Warning,
            )
        return response

    def _ignored_params(self, handler, params: dict) -> list:
        """Arguments the handler accepts only through a **_ catch-all.

        Most handlers end in **_ so an extra key never raises — which also
        meant a misspelt argument (layer instead of layer_id, colour instead of
        color) was dropped without a word and the call ran on defaults.
        """
        sig = self._sig_cache.get(handler)
        if sig is None:
            try:
                ps = inspect.signature(handler).parameters.values()
                named = {p.name for p in ps if p.kind not in (p.VAR_KEYWORD, p.VAR_POSITIONAL)}
                catch_all = any(p.kind == p.VAR_KEYWORD for p in ps)
                sig = (named, catch_all)
            except (TypeError, ValueError):
                sig = (set(), False)
            self._sig_cache[handler] = sig
        named, catch_all = sig
        if not catch_all:
            return []  # an unknown key raises TypeError, which already reports it
        return sorted(k for k in params if k not in named)

    @staticmethod
    def context_rev() -> str:
        """Short fingerprint of what an agent's picture of the project rests on.

        Covers project file and CRS, layer order, ids, names, visibility, CRS,
        field names and subset filters. Not features, not styles: those change
        too often to be useful here and are cheap to re-read on demand. Cheap
        enough to run before and after every call.
        """
        project = QgsProject.instance()
        root = project.layerTreeRoot()
        h = hashlib.sha1()
        h.update(f"{project.fileName()}|{project.crs().authid()}".encode("utf-8"))
        layers = project.mapLayers()
        seen = set()
        for node in root.findLayers():
            lid = node.layerId()
            layer = layers.get(lid)
            if layer is None:
                continue
            seen.add(lid)
            parts = [lid, layer.name(), "1" if node.isVisible() else "0", layer.crs().authid()]
            if layer.type() == Qgis.LayerType.Vector:
                parts.append(",".join(layer.fields().names()))
                parts.append(layer.subsetString())
            h.update(("\n" + "|".join(parts)).encode("utf-8"))
        for lid in sorted(set(layers) - seen):  # layers kept out of the tree
            h.update(f"\n{lid}|{layers[lid].name()}".encode("utf-8"))
        return h.hexdigest()[:12]

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
