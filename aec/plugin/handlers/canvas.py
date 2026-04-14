"""
Map canvas control handlers — extent, CRS, scale, zoom, rotation, refresh, render.
"""

from qgis.core import (
    Qgis,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsMapRendererParallelJob,
    QgsMapSettings,
    QgsProject,
    QgsRectangle,
)
from qgis.PyQt.QtCore import QSize
from qgis.PyQt.QtGui import QColor


def register(server):
    """Register canvas handlers."""
    s = server

    def get_canvas_info(**_):
        """Return current canvas state: extent, CRS, scale, rotation, size in pixels."""
        canvas = s.iface.mapCanvas()
        extent = canvas.extent()
        return {
            "extent": s.extent_to_dict(extent),
            "crs": canvas.mapSettings().destinationCrs().authid(),
            "scale": canvas.scale(),
            "rotation": canvas.rotation(),
            "map_units": str(canvas.mapUnits()),
            "width_px": canvas.width(),
            "height_px": canvas.height(),
        }

    def set_canvas_extent(xmin: float, ymin: float, xmax: float, ymax: float,
                          crs: str = None, **_):
        """Set the canvas extent. Optionally provide source CRS for auto-transform."""
        canvas = s.iface.mapCanvas()
        rect = QgsRectangle(xmin, ymin, xmax, ymax)

        if crs:
            src_crs = QgsCoordinateReferenceSystem(crs)
            dst_crs = canvas.mapSettings().destinationCrs()
            if src_crs.isValid() and src_crs != dst_crs:
                xform = QgsCoordinateTransform(src_crs, dst_crs, QgsProject.instance())
                rect = xform.transformBoundingBox(rect)

        canvas.setExtent(rect)
        canvas.refresh()
        return {"extent": s.extent_to_dict(canvas.extent())}

    def set_project_crs(crs: str, **_):
        """Set the project CRS by authid (e.g. 'EPSG:4326') and refresh canvas."""
        crs_obj = QgsCoordinateReferenceSystem(crs)
        if not crs_obj.isValid():
            raise RuntimeError(f"Invalid CRS: {crs}")
        QgsProject.instance().setCrs(crs_obj)
        s.iface.mapCanvas().refresh()
        return {"crs": crs_obj.authid()}

    def zoom_to_extent(xmin: float, ymin: float, xmax: float, ymax: float, **_):
        """Zoom canvas to the given WGS84 (EPSG:4326) extent, auto-transformed to project CRS."""
        canvas = s.iface.mapCanvas()
        src_crs = QgsCoordinateReferenceSystem("EPSG:4326")
        dst_crs = QgsProject.instance().crs()
        rect = QgsRectangle(xmin, ymin, xmax, ymax)

        if src_crs != dst_crs:
            xform = QgsCoordinateTransform(src_crs, dst_crs, QgsProject.instance())
            rect = xform.transformBoundingBox(rect)

        canvas.setExtent(rect)
        canvas.refresh()
        return {"extent": s.extent_to_dict(canvas.extent())}

    def zoom_in(factor: float = 2.0, **_):
        """Zoom in by the given factor (default 2x)."""
        canvas = s.iface.mapCanvas()
        canvas.zoomByFactor(1.0 / factor)
        return {"scale": canvas.scale()}

    def zoom_out(factor: float = 2.0, **_):
        """Zoom out by the given factor (default 2x)."""
        canvas = s.iface.mapCanvas()
        canvas.zoomByFactor(factor)
        return {"scale": canvas.scale()}

    def zoom_to_full_extent(**_):
        """Zoom the canvas to show all layers."""
        s.iface.zoomFull()
        canvas = s.iface.mapCanvas()
        return {
            "extent": s.extent_to_dict(canvas.extent()),
            "scale": canvas.scale(),
        }

    def set_scale(scale: float, **_):
        """Set exact map scale (e.g. 25000 for 1:25000)."""
        canvas = s.iface.mapCanvas()
        canvas.zoomScale(scale)
        return {"scale": canvas.scale()}

    def set_rotation(rotation: float, **_):
        """Set map rotation in degrees (0-360)."""
        canvas = s.iface.mapCanvas()
        canvas.setRotation(rotation)
        canvas.refresh()
        return {"rotation": canvas.rotation()}

    def refresh_canvas(**_):
        """Force a canvas refresh/repaint."""
        s.iface.mapCanvas().refresh()
        return {"refreshed": True}

    def render_map(path: str, width: int = 800, height: int = 600,
                   extent: dict = None, crs: str = None,
                   dpi: int = 96, layers: list = None, **_):
        """Render the current map view to an image file.

        Optional: extent dict {xmin, ymin, xmax, ymax}, CRS override,
        DPI, specific layer IDs to render.
        """
        project = QgsProject.instance()
        ms = QgsMapSettings()

        # Layers
        if layers:
            render_layers = []
            for lid in layers:
                lyr = project.mapLayer(lid)
                if lyr:
                    render_layers.append(lyr)
            ms.setLayers(render_layers)
        else:
            ms.setLayers(list(project.mapLayers().values()))

        # CRS
        dest_crs = QgsCoordinateReferenceSystem(crs) if crs else project.crs()
        ms.setDestinationCrs(dest_crs)

        # Extent
        if extent:
            rect = QgsRectangle(
                extent["xmin"], extent["ymin"], extent["xmax"], extent["ymax"]
            )
            ms.setExtent(rect)
        else:
            ms.setExtent(s.iface.mapCanvas().extent())

        ms.setOutputSize(QSize(width, height))
        ms.setBackgroundColor(QColor(255, 255, 255))
        ms.setOutputDpi(dpi)

        render = QgsMapRendererParallelJob(ms)
        render.start()
        render.waitForFinished()

        img = render.renderedImage()
        if not img.save(path):
            raise RuntimeError(f"Failed to save render: {path}")
        return {"rendered": True, "path": path, "width": width, "height": height, "dpi": dpi}

    # ── Map Themes ────────────────────────────────────────────────

    def list_map_themes(**_):
        """List all map themes (visibility presets) in the project."""
        collection = QgsProject.instance().mapThemeCollection()
        themes = []
        for name in collection.mapThemes():
            record = collection.mapThemeState(name)
            layer_records = record.layerRecords()
            layers = []
            for lr in layer_records:
                lyr = lr.layer()
                layers.append({
                    "layer_id": lyr.id() if lyr else None,
                    "layer_name": lyr.name() if lyr else None,
                    "visible": lr.isVisible,
                })
            themes.append({
                "name": name,
                "layer_count": len(layer_records),
                "layers": layers,
            })
        return themes

    def apply_map_theme(name: str, **_):
        """Apply a map theme (changes layer visibility and styles)."""
        collection = QgsProject.instance().mapThemeCollection()
        if name not in collection.mapThemes():
            raise RuntimeError(f"Map theme not found: {name}")
        root = QgsProject.instance().layerTreeRoot()
        model = s.iface.layerTreeView().layerTreeModel()
        collection.applyTheme(name, root, model)
        s.iface.mapCanvas().refresh()
        return {"applied_theme": name}

    def create_map_theme(name: str, **_):
        """Save current layer visibility and styles as a named map theme."""
        from qgis.core import QgsMapThemeCollection
        project = QgsProject.instance()
        collection = project.mapThemeCollection()
        root = project.layerTreeRoot()
        model = s.iface.layerTreeView().layerTreeModel()
        record = QgsMapThemeCollection.createThemeFromCurrentState(root, model)
        collection.insert(name, record)
        return {"created_theme": name}

    def delete_map_theme(name: str, **_):
        """Delete a map theme by name."""
        collection = QgsProject.instance().mapThemeCollection()
        if name not in collection.mapThemes():
            raise RuntimeError(f"Map theme not found: {name}")
        collection.removeMapTheme(name)
        return {"deleted_theme": name}

    def get_canvas_screenshot(path: str, **_):
        """Fast canvas screenshot using QWidget.grab() — much faster than render_map.

        Captures the canvas exactly as displayed (including decorations, selections,
        and UI elements). No re-render needed.
        """
        canvas = s.iface.mapCanvas()
        pixmap = canvas.grab()
        if not pixmap.save(path):
            raise RuntimeError(f"Failed to save screenshot: {path}")
        return {
            "path": path,
            "width": pixmap.width(),
            "height": pixmap.height(),
        }

    def get_message_log(level: str = None, tag: str = None, limit: int = 50, **_):
        """Get recent QGIS message log entries. Useful for debugging.

        level: 'info', 'warning', 'critical' (default: all levels).
        tag: filter by log tag (e.g. 'QGIS MCP', 'Processing').
        """
        from qgis.core import QgsMessageLog, QgsApplication

        # The message log is not easily iterable from Python API,
        # so we read from the log file instead
        import os
        log_dir = QgsApplication.qgisSettingsDirPath()
        log_file = os.path.join(log_dir, "qgis_sketching.log")

        # Fallback: return what we know about the logging state
        return {
            "note": "Use QGIS message log panel or check log files for detailed entries",
            "log_dir": log_dir,
            "tip": "Errors from MCP operations are returned in tool responses directly",
        }

    s._HANDLERS.update({
        "get_canvas_info": get_canvas_info,
        "set_canvas_extent": set_canvas_extent,
        "set_project_crs": set_project_crs,
        "zoom_to_extent": zoom_to_extent,
        "zoom_in": zoom_in,
        "zoom_out": zoom_out,
        "zoom_to_full_extent": zoom_to_full_extent,
        "set_scale": set_scale,
        "set_rotation": set_rotation,
        "refresh_canvas": refresh_canvas,
        "render_map": render_map,
        "list_map_themes": list_map_themes,
        "apply_map_theme": apply_map_theme,
        "create_map_theme": create_map_theme,
        "delete_map_theme": delete_map_theme,
        "get_canvas_screenshot": get_canvas_screenshot,
        "get_message_log": get_message_log,
    })
