"""
Analysis handlers — statistics, spatial queries, geometry measurement, counting.
"""

from qgis.core import (
    Qgis,
    QgsExpression,
    QgsExpressionContext,
    QgsExpressionContextUtils,
    QgsFeatureRequest,
)


def register(server):
    """Register analysis handlers."""
    s = server

    def calculate_statistics(layer_id: str, field: str, **_):
        """Calculate field statistics: min, max, mean, median, stdev, sum, count, unique values."""
        layer = s.get_layer_or_raise(layer_id)
        if layer.type() != Qgis.LayerType.Vector:
            raise RuntimeError(f"Not a vector layer: {layer_id}")

        idx = layer.fields().indexFromName(field)
        if idx < 0:
            raise RuntimeError(f"Field not found: {field}")

        # Collect values
        values = []
        null_count = 0
        for feat in layer.getFeatures():
            val = feat.attribute(field)
            if val is None or (isinstance(val, float) and val != val):
                null_count += 1
            else:
                try:
                    values.append(float(val))
                except (ValueError, TypeError):
                    pass

        if not values:
            return {
                "layer_id": layer_id,
                "field": field,
                "count": 0,
                "null_count": null_count,
            }

        values.sort()
        n = len(values)
        total = sum(values)
        mean = total / n

        # Median
        if n % 2 == 0:
            median = (values[n // 2 - 1] + values[n // 2]) / 2
        else:
            median = values[n // 2]

        # Standard deviation
        variance = sum((v - mean) ** 2 for v in values) / n
        stdev = variance ** 0.5

        # Unique values (limited)
        unique = list(set(values))
        unique.sort()

        return {
            "layer_id": layer_id,
            "field": field,
            "count": n,
            "null_count": null_count,
            "min": values[0],
            "max": values[-1],
            "sum": total,
            "mean": mean,
            "median": median,
            "stdev": stdev,
            "unique_count": len(unique),
            "unique_values": unique[:100],
        }

    def spatial_query(layer_id: str, intersect_layer_id: str,
                      predicate: str = "intersects", **_):
        """Select features from one layer by spatial relationship with another.

        predicate: intersects, within, contains, crosses, touches, overlaps, disjoint.
        Returns selected feature count.
        """
        import processing
        predicate_map = {
            "intersects": 0,
            "contains": 1,
            "disjoint": 2,
            "equals": 3,
            "touches": 4,
            "overlaps": 5,
            "within": 6,
            "crosses": 7,
        }
        pred_value = predicate_map.get(predicate.lower())
        if pred_value is None:
            raise RuntimeError(
                f"Unknown predicate: {predicate}. "
                f"Use: {', '.join(predicate_map.keys())}"
            )

        layer = s.get_layer_or_raise(layer_id)
        intersect_layer = s.get_layer_or_raise(intersect_layer_id)

        processing.run("native:selectbylocation", {
            "INPUT": layer,
            "PREDICATE": [pred_value],
            "INTERSECT": intersect_layer,
            "METHOD": 0,
        })
        selected = layer.selectedFeatureCount()
        return {
            "layer_id": layer_id,
            "intersect_layer_id": intersect_layer_id,
            "predicate": predicate,
            "selected_count": selected,
        }

    def measure_geometry(layer_id: str, feature_ids: list = None,
                         limit: int = 100, **_):
        """Calculate area, perimeter, and length for features in a vector layer.

        If feature_ids is provided, only those features are measured.
        Values are in the layer's CRS units.
        """
        layer = s.get_layer_or_raise(layer_id)
        if layer.type() != Qgis.LayerType.Vector:
            raise RuntimeError(f"Not a vector layer: {layer_id}")

        results = []
        request = QgsFeatureRequest()
        if feature_ids:
            request.setFilterFids(feature_ids)
        request.setLimit(limit)

        for feat in layer.getFeatures(request):
            if not feat.hasGeometry():
                continue
            geom = feat.geometry()
            entry = {"id": feat.id()}

            gt = geom.type()
            if gt == Qgis.GeometryType.Polygon:
                entry["area"] = geom.area()
                entry["perimeter"] = geom.constGet().perimeter()
            elif gt == Qgis.GeometryType.Line:
                entry["length"] = geom.length()
            elif gt == Qgis.GeometryType.Point:
                entry["x"] = geom.asPoint().x()
                entry["y"] = geom.asPoint().y()

            results.append(entry)

        return {
            "layer_id": layer_id,
            "crs": layer.crs().authid(),
            "count": len(results),
            "measurements": results,
        }

    def count_features(layer_id: str, expression: str = None, **_):
        """Count features in a layer, optionally filtered by an expression."""
        layer = s.get_layer_or_raise(layer_id)
        if layer.type() != Qgis.LayerType.Vector:
            raise RuntimeError(f"Not a vector layer: {layer_id}")

        if expression:
            expr = QgsExpression(expression)
            if expr.hasParserError():
                raise RuntimeError(f"Expression error: {expr.parserErrorString()}")
            request = QgsFeatureRequest(expr)
            count = sum(1 for _ in layer.getFeatures(request))
        else:
            count = layer.featureCount()

        return {
            "layer_id": layer_id,
            "count": count,
            "expression": expression,
        }

    s._HANDLERS.update({
        "calculate_statistics": calculate_statistics,
        "spatial_query": spatial_query,
        "measure_geometry": measure_geometry,
        "count_features": count_features,
    })
