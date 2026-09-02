"""
QGIS MCP Plugin entry point — menu, toolbar, auto-start, dock widget.
QGIS 4.0 / Qt6
"""

import datetime
import os

from qgis.core import QgsApplication
from qgis.gui import QgisInterface
from qgis.PyQt.QtCore import Qt, QTimer
from qgis.PyQt.QtGui import QAction

from .ui import QgisMCPDockWidget

_LOG_PATH = os.path.join(os.path.dirname(__file__), "mcp_debug.log")


class QgisMCPPlugin:
    """Main plugin class registered via classFactory."""

    def __init__(self, iface: QgisInterface):
        self.iface = iface
        self.dock: QgisMCPDockWidget | None = None
        self.action: QAction | None = None
        self._log_handler = None

    def _setup_file_logging(self):
        """Tee all QGIS MCP log messages to mcp_debug.log (survives QGIS crashes).

        Best-effort only: initGui() calls this first, before the toolbar
        action/menu entry exist and before auto-start is scheduled, so an
        unwritable plugin directory (system-wide install, locked-down
        profile, full disk) must not raise out of here — that would fail
        the whole plugin load (menu, toolbar icon, MCP auto-start included)
        over what is meant to be optional debug logging.
        """
        try:
            with open(_LOG_PATH, "a", encoding="utf-8") as f:
                f.write(
                    f"\n{'='*60}\n"
                    f"Session started {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                    f"{'='*60}\n"
                )
        except Exception:
            pass

        def on_message(message, tag, level):
            if "MCP" in tag or "mcp" in tag.lower():
                ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
                level_names = {0: "INFO", 1: "WARN", 2: "CRIT", 3: "SUCC"}
                lvl = level_names.get(int(level), str(level))
                try:
                    with open(_LOG_PATH, "a", encoding="utf-8") as f:
                        f.write(f"[{ts}] [{lvl}] {message}\n")
                except Exception:
                    pass

        QgsApplication.messageLog().messageReceived.connect(on_message)
        self._log_handler = on_message  # keep reference — prevents GC disconnect

    def initGui(self):
        """Called by QGIS when the plugin is loaded."""
        self._setup_file_logging()

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
