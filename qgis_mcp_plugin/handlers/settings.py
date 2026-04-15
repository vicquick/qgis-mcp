"""
QGIS settings handlers — snapping configuration, general settings read/write.
"""

from qgis.core import (
    Qgis,
    QgsProject,
    QgsSettings,
    QgsSnappingConfig,
    QgsTolerance,
)


def register(server):
    """Register settings handlers."""
    s = server

    def get_snapping_config(**_):
        """Return current snapping settings: enabled, mode, type, tolerance."""
        project = QgsProject.instance()
        config = project.snappingConfig()

        return {
            "enabled": config.enabled(),
            "mode": str(config.mode()),
            "type": str(config.type()),
            "tolerance": config.tolerance(),
            "unit": str(config.units()),
            "intersection_snapping": config.intersectionSnapping(),
        }

    def set_snapping_config(enabled: bool = None, mode: str = None,
                            type: str = None, tolerance: float = None,
                            unit: str = None,
                            intersection_snapping: bool = None, **_):
        """Configure snapping settings.

        mode: active_layer, all_layers, advanced
        type: vertex, segment, vertex_and_segment, area
        unit: pixels, project_units, layer_units
        """
        project = QgsProject.instance()
        config = project.snappingConfig()

        if enabled is not None:
            config.setEnabled(enabled)

        if mode is not None:
            mode_map = {
                "active_layer": Qgis.SnappingMode.ActiveLayer,
                "all_layers": Qgis.SnappingMode.AllLayers,
                "advanced": Qgis.SnappingMode.AdvancedConfiguration,
            }
            m = mode_map.get(mode.lower())
            if m is None:
                raise RuntimeError(f"Unknown snapping mode: {mode}")
            config.setMode(m)

        if type is not None:
            type_map = {
                "vertex": Qgis.SnappingType.Vertex,
                "segment": Qgis.SnappingType.Segment,
                "vertex_and_segment": Qgis.SnappingType.VertexAndSegment,
                "area": Qgis.SnappingType.Area,
            }
            t = type_map.get(type.lower())
            if t is None:
                raise RuntimeError(f"Unknown snapping type: {type}")
            config.setType(t)

        if tolerance is not None:
            config.setTolerance(tolerance)

        if unit is not None:
            unit_map = {
                "pixels": QgsTolerance.UnitType.Pixels,
                "project_units": QgsTolerance.UnitType.ProjectUnits,
                "layer_units": QgsTolerance.UnitType.LayerUnits,
            }
            u = unit_map.get(unit.lower())
            if u is None:
                raise RuntimeError(f"Unknown unit: {unit}")
            config.setUnits(u)

        if intersection_snapping is not None:
            config.setIntersectionSnapping(intersection_snapping)

        project.setSnappingConfig(config)

        return {
            "enabled": config.enabled(),
            "mode": str(config.mode()),
            "type": str(config.type()),
            "tolerance": config.tolerance(),
        }

    def get_settings(key: str, default: str = None, **_):
        """Read a QGIS setting by key path (e.g. 'qgis/locale/userLocale')."""
        settings = QgsSettings()
        value = settings.value(key, default)
        if not isinstance(value, (str, int, float, bool, type(None))):
            value = str(value)
        return {"key": key, "value": value}

    def set_settings(key: str, value: str, **_):
        """Write a QGIS setting by key path."""
        settings = QgsSettings()
        settings.setValue(key, value)
        return {"key": key, "value": value}

    # ── Plugin Management ─────────────────────────────────────────

    def list_plugins(**_):
        """List all installed QGIS plugins with their enabled/disabled status."""
        from qgis.utils import plugins, active_plugins, available_plugins
        import qgis.utils

        result = []
        # Get all known plugins
        all_plugins = set()
        if hasattr(qgis.utils, 'available_plugins'):
            all_plugins.update(available_plugins)
        # Also include currently loaded plugins
        all_plugins.update(plugins.keys())

        for plugin_name in sorted(all_plugins):
            info = {
                "name": plugin_name,
                "enabled": plugin_name in active_plugins,
                "loaded": plugin_name in plugins,
            }
            result.append(info)
        return result

    def enable_plugin(name: str, **_):
        """Enable (load) a QGIS plugin by name."""
        from qgis.utils import loadPlugin, startPlugin, active_plugins, available_plugins

        if name not in available_plugins:
            raise RuntimeError(f"Plugin not found: {name}")

        if name in active_plugins:
            return {"name": name, "status": "already_enabled"}

        if not loadPlugin(name):
            raise RuntimeError(f"Failed to load plugin: {name}")
        if not startPlugin(name):
            raise RuntimeError(f"Failed to start plugin: {name}")

        return {"name": name, "status": "enabled"}

    def disable_plugin(name: str, **_):
        """Disable (unload) a QGIS plugin by name."""
        from qgis.utils import unloadPlugin, active_plugins

        if name not in active_plugins:
            return {"name": name, "status": "already_disabled"}

        if not unloadPlugin(name):
            raise RuntimeError(f"Failed to unload plugin: {name}")

        return {"name": name, "status": "disabled"}

    s._HANDLERS.update({
        "get_snapping_config": get_snapping_config,
        "set_snapping_config": set_snapping_config,
        "get_settings": get_settings,
        "set_settings": set_settings,
        "list_plugins": list_plugins,
        "enable_plugin": enable_plugin,
        "disable_plugin": disable_plugin,
    })
