"""
QGIS MCP Plugin entry point — menu, toolbar, auto-start, dock widget.
QGIS 4.0 / Qt6
"""

from qgis.gui import QgisInterface
from qgis.PyQt.QtCore import Qt, QTimer
from qgis.PyQt.QtGui import QAction

from .ui import QgisMCPDockWidget


class QgisMCPPlugin:
    """Main plugin class registered via classFactory."""

    def __init__(self, iface: QgisInterface):
        self.iface = iface
        self.dock: QgisMCPDockWidget | None = None
        self.action: QAction | None = None

    def initGui(self):
        """Called by QGIS when the plugin is loaded."""
        self.action = QAction("QGIS MCP", self.iface.mainWindow())
        self.action.setCheckable(True)
        self.action.triggered.connect(self._toggle)
        self.iface.addPluginToMenu("QGIS MCP", self.action)
        self.iface.addToolBarIcon(self.action)

        # Auto-start MCP server after QGIS finishes loading
        QTimer.singleShot(3000, self._auto_start)

    def _auto_start(self):
        """Auto-start MCP server on plugin load."""
        try:
            if not self.dock:
                self.dock = QgisMCPDockWidget(self.iface)
                self.iface.addDockWidget(
                    Qt.DockWidgetArea.RightDockWidgetArea, self.dock,
                )
                self.dock.closed.connect(lambda: self.action.setChecked(False))
            self.dock._start()
            self.action.setChecked(True)
        except Exception as e:
            from qgis.core import Qgis, QgsMessageLog
            import traceback
            QgsMessageLog.logMessage(
                f"MCP auto-start failed: {e}\n{traceback.format_exc()}",
                "QGIS MCP", Qgis.MessageLevel.Critical,
            )

    def _toggle(self, checked: bool):
        """Show/hide the dock widget."""
        if checked:
            if not self.dock:
                self.dock = QgisMCPDockWidget(self.iface)
                self.iface.addDockWidget(
                    Qt.DockWidgetArea.RightDockWidgetArea, self.dock,
                )
                self.dock.closed.connect(lambda: self.action.setChecked(False))
            else:
                self.dock.show()
        elif self.dock:
            self.dock.hide()

    def unload(self):
        """Called by QGIS when the plugin is unloaded."""
        if self.dock:
            self.dock._stop()
            self.iface.removeDockWidget(self.dock)
            self.dock = None
        if self.action:
            self.iface.removePluginMenu("QGIS MCP", self.action)
            self.iface.removeToolBarIcon(self.action)


def classFactory(iface: QgisInterface):
    """QGIS plugin entry point."""
    return QgisMCPPlugin(iface)
