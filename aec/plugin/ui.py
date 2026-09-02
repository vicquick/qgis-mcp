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

from .server import DEFAULT_PORT_START, QgisMCPServer

# Remembers the user's chosen start port across QGIS sessions/restarts. An
# env override (QGIS_MCP_PORT, baked into DEFAULT_PORT_START) still wins the
# first time this key has never been set.
_PORT_SETTINGS_KEY = "QgisMCP/portStart"


class QgisMCPDockWidget(QDockWidget):
    """Dock widget providing start/stop controls and status for the MCP server."""

    closed = pyqtSignal()

    def __init__(self, iface: QgisInterface):
        super().__init__("QGIS MCP")
        self.iface = iface
        self.server: QgisMCPServer | None = None
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

    def _start(self):
        """Create and start the MCP server."""
        requested_port = self.port_spin.value()
        QSettings().setValue(_PORT_SETTINGS_KEY, requested_port)
        if not self.server:
            self.server = QgisMCPServer(port=requested_port, iface=self.iface)
        if self.server.start():
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

    def closeEvent(self, event):
        self._stop()
        self.closed.emit()
        super().closeEvent(event)
