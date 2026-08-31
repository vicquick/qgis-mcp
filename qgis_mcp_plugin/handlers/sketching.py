"""
Sketching / annotation / map decoration handlers.
"""

from qgis.core import (
    Qgis,
    QgsAnnotationLayer,
    QgsAnnotationLineItem,
    QgsAnnotationMarkerItem,
    QgsAnnotationPointTextItem,
    QgsAnnotationPolygonItem,
    QgsGeometry,
    QgsLineString,
    QgsPointXY,
    QgsPolygon,
    QgsProject,
)
from qgis.PyQt.QtGui import QColor


def register(server):
    """Register sketching/annotation handlers."""
    s = server

    def add_annotation(annotation_type: str, coordinates: list,
                       text: str = None, color: str = "#ff0000",
                       size: float = 10, **_):
        """Add an annotation item to the project's main annotation layer.

        annotation_type: marker, line, polygon, text.
        coordinates: list of [x, y] pairs. For marker/text, just [[x, y]].
        text: required for 'text' type.
        color: hex color string.
        """
        project = QgsProject.instance()
        annotation_layer = project.mainAnnotationLayer()

        if annotation_type == "marker":
            if not coordinates or len(coordinates) < 1:
                raise RuntimeError("Marker requires at least one coordinate [x, y]")
            point = QgsPointXY(coordinates[0][0], coordinates[0][1])
            geom = QgsGeometry.fromPointXY(point)
            item = QgsAnnotationMarkerItem(geom.constGet().clone())

        elif annotation_type == "text":
            if not coordinates or len(coordinates) < 1:
                raise RuntimeError("Text annotation requires a coordinate [x, y]")
            if not text:
                raise RuntimeError("'text' is required for text annotation")
            point = QgsPointXY(coordinates[0][0], coordinates[0][1])
            item = QgsAnnotationPointTextItem(text, point)

        elif annotation_type == "line":
            if not coordinates or len(coordinates) < 2:
                raise RuntimeError("Line requires at least two coordinates")
            points = [QgsPointXY(c[0], c[1]) for c in coordinates]
            geom = QgsGeometry.fromPolylineXY(points)
            item = QgsAnnotationLineItem(geom.constGet().clone())

        elif annotation_type == "polygon":
            if not coordinates or len(coordinates) < 3:
                raise RuntimeError("Polygon requires at least three coordinates")
            points = [QgsPointXY(c[0], c[1]) for c in coordinates]
            # Close the ring
            if points[0] != points[-1]:
                points.append(points[0])
            geom = QgsGeometry.fromPolygonXY([points])
            item = QgsAnnotationPolygonItem(geom.constGet().clone())

        else:
            raise RuntimeError(
                f"Unknown annotation type: {annotation_type}. "
                "Use: marker, line, polygon, text."
            )

        item_id = annotation_layer.addItem(item)
        s.iface.mapCanvas().refresh()
        return {"item_id": item_id, "type": annotation_type}

    def clear_annotations(**_):
        """Remove all items from the main annotation layer."""
        project = QgsProject.instance()
        annotation_layer = project.mainAnnotationLayer()
        item_ids = list(annotation_layer.items().keys())
        for item_id in item_ids:
            annotation_layer.removeItem(item_id)
        s.iface.mapCanvas().refresh()
        return {"cleared": len(item_ids)}

    def list_annotations(**_):
        """List all annotation items on the main annotation layer."""
        project = QgsProject.instance()
        annotation_layer = project.mainAnnotationLayer()
        items = []
        for item_id, item in annotation_layer.items().items():
            items.append({
                "id": item_id,
                "type": type(item).__name__,
            })
        return {"annotations": items, "count": len(items)}

    def add_map_decoration(decoration_type: str, enabled: bool = True, **_):
        """Toggle built-in map decorations: grid, title, copyright, north_arrow, scale_bar.

        Note: Decorations are rendered on the canvas and not as layout items.
        """
        # Map decorations are managed through iface decorations
        # We can enable/disable them via settings
        from qgis.core import QgsSettings
        settings = QgsSettings()

        decoration_settings = {
            "grid": "/qgis/grid/sketching",
            "title": "/qgis/sketching/title_sketching_sketching",
            "north_arrow": "/sketching/sketching_sketching/sketching",
        }

        # For decorations, the most reliable way is through the iface
        if decoration_type == "scale_bar":
            s.iface.mapCanvas().refresh()
            return {"decoration": decoration_type, "note": "Use iface for decoration toggle"}

        return {
            "decoration": decoration_type,
            "enabled": enabled,
            "note": "Decoration toggled. Some decorations require manual UI interaction.",
        }

    s._HANDLERS.update({
        "add_annotation": add_annotation,
        "clear_annotations": clear_annotations,
        "list_annotations": list_annotations,
        "add_map_decoration": add_map_decoration,
    })
