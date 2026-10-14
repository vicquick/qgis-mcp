"""
QGIS MCP Dock Widget — Start/stop UI for the MCP socket server.
QGIS 4.0 / Qt6
"""

from qgis.gui import QgisInterface
from qgis.PyQt.QtCore import QSettings, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QDockWidget,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

import importlib
import sys

from . import server as _server_module
from .server import DEFAULT_PORT_START

# Remembers the user's chosen start port across QGIS sessions/restarts. An
# env override (QGIS_MCP_PORT, baked into DEFAULT_PORT_START) still wins the
# first time this key has never been set.
_PORT_SETTINGS_KEY = "QgisMCP/portStart"


def _reload_code():
    """Re-import server.py and every handler module from disk.

    Stop/Start used to restart only the listener: Python keeps a module it
    has imported, so updated handler files stayed unused until QGIS itself
    restarted. Submodules first, then the package (its `from . import`
    rebinds to the fresh modules and picks up new ones), then server.py.
    ui.py and plugin.py are not reloaded; they only hold the dock.
    """
    pkg = __package__
    for name in sorted(n for n in list(sys.modules) if n.startswith(pkg + ".handlers.")):
        importlib.reload(sys.modules[name])
    importlib.reload(sys.modules[pkg + ".handlers"])
    return importlib.reload(sys.modules[pkg + ".server"])


class QgisMCPDockWidget(QDockWidget):
    """Dock widget providing start/stop controls and status for the MCP server."""

    closed = pyqtSignal()

    def __init__(self, iface: QgisInterface):
        super().__init__("QGIS MCP")
        self.iface = iface
        self.server = None
        # The first start uses the modules QGIS just imported; every later
        # Start (manual or via reload_plugin) reads the code from disk again.
        self._started_once = False
        self._setup_ui()

    def _setup_ui(self):
        widget = QWidget()
        layout = QVBoxLayout()
        widget.setLayout(layout)

        layout.addWidget(QLabel("Start Port:"))
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1024, 65535)
        self.port_spin.setToolTip(
            "First port tried. If it's taken (e.g. another QGIS instance is "
            "already running the plugin), the next ports are tried in turn."
        )
        self.port_spin.setValue(self._initial_port())
        layout.addWidget(self.port_spin)

        self.start_btn = QPushButton("Start Server")
        self.start_btn.clicked.connect(self._start)
        layout.addWidget(self.start_btn)

        self.stop_btn = QPushButton("Stop Server")
        self.stop_btn.clicked.connect(self._stop)
        self.stop_btn.setEnabled(False)
        layout.addWidget(self.stop_btn)

        self.status = QLabel("Server: Stopped")
        layout.addWidget(self.status)

        self.setWidget(widget)

    @staticmethod
    def _initial_port() -> int:
        """Last port the user picked (QSettings), else the plugin default
        (which itself honors the QGIS_MCP_PORT env override)."""
        saved = QSettings().value(_PORT_SETTINGS_KEY, type=int)
        return saved or DEFAULT_PORT_START

    def _start(self, *_):
        """Create and start the MCP server (fresh code after the first start)."""
        requested_port = self.port_spin.value()
        QSettings().setValue(_PORT_SETTINGS_KEY, requested_port)
        if not self.server:
            module = _server_module
            if self._started_once:
                try:
                    module = _reload_code()
                except Exception as e:
                    # A broken file on disk must not leave QGIS without a
                    # server: fall back to the code already loaded.
                    from qgis.core import Qgis, QgsMessageLog
                    QgsMessageLog.logMessage(
                        f"Reload failed, starting the loaded code: {e}",
                        "QGIS MCP", Qgis.MessageLevel.Critical,
                    )
                    module = sys.modules.get(__package__ + ".server", _server_module)
            self.server = module.QgisMCPServer(port=requested_port, iface=self.iface)
            self.server.request_restart = self._restart
        if self.server.start():
            self._started_once = True
            # Bound port can differ from requested_port when that one was
            # already taken by another QGIS instance — show what actually
            # bound, both in the status line and the dock's own title, so
            # several docked instances stay distinguishable at a glance.
            handler_count = len(self.server._HANDLERS)
            self.setWindowTitle(f"QGIS MCP :{self.server.port}")
            self.status.setText(
                f"Server: Running on port {self.server.port} ({handler_count} handlers)"
            )
            self.start_btn.setEnabled(False)
            self.stop_btn.setEnabled(True)
            self.port_spin.setEnabled(False)
        else:
            self.status.setText(
                f"Server: Failed to bind any port in "
                f"{requested_port}-{requested_port + self.server.port_span - 1}"
            )
            self.server = None

    def _stop(self):
        """Stop the MCP server."""
        if self.server:
            self.server.stop()
            self.server = None
        self.setWindowTitle("QGIS MCP")
        self.status.setText("Server: Stopped")
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.port_spin.setEnabled(True)

    def _restart(self):
        """Stop, reload the code and start on the same port (reload_plugin)."""
        port = self.server.port if self.server else None
        self._stop()
        if port:
            self.port_spin.setValue(port)
        self._start()

    def closeEvent(self, event):
        self._stop()
        self.closed.emit()
        super().closeEvent(event)
