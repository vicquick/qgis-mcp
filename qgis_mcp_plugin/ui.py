"""
QGIS MCP Dock Widget — Start/stop UI for the MCP socket server.
QGIS 4.0 / Qt6
"""

from qgis.gui import QgisInterface
from qgis.PyQt.QtCore import pyqtSignal
from qgis.PyQt.QtWidgets import (
    QDockWidget,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .server import QgisMCPServer


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

        layout.addWidget(QLabel("Server Port:"))
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1024, 65535)
        self.port_spin.setValue(9877)
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

    def _start(self):
        """Create and start the MCP server."""
        if not self.server:
            self.server = QgisMCPServer(port=self.port_spin.value(), iface=self.iface)
        if self.server.start():
            handler_count = len(self.server._HANDLERS)
            self.status.setText(
                f"Server: Running on port {self.server.port} ({handler_count} handlers)"
            )
            self.start_btn.setEnabled(False)
            self.stop_btn.setEnabled(True)
            self.port_spin.setEnabled(False)

    def _stop(self):
        """Stop the MCP server."""
        if self.server:
            self.server.stop()
            self.server = None
        self.status.setText("Server: Stopped")
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.port_spin.setEnabled(True)

    def closeEvent(self, event):
        self._stop()
        self.closed.emit()
        super().closeEvent(event)
