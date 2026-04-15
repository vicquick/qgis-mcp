"""
Feature CRUD handlers — add, edit, delete, select, filter, fields, field calculator.
"""

from qgis.core import (
    Qgis,
    QgsExpression,
    QgsFeature,
    QgsFeatureRequest,
    QgsField,
    QgsGeometry,
    QgsProject,
    QgsVectorLayerUtils,
)
from qgis.PyQt.QtCore import QVariant

from ..server import GEOMETRY_TYPE_NAMES


def register(server):
    """Register feature handlers."""
    s = server

    def add_feature(layer_id: str, attributes: dict = None, wkt: str = None, **_):
        """Add a feature to a vector layer. Provide attributes dict and/or WKT geometry."""
        layer = s.get_layer_or_raise(layer_id)
        if layer.type() != Qgis.LayerType.Vector:
            raise RuntimeError(f"Not a vector layer: {layer_id}")

        feat = QgsFeature(layer.fields())

        # Validate attributes against field names
        unknown_fields = []
        if attributes:
            for name, val in attributes.items():
                idx = layer.fields().indexFromName(name)
                if idx >= 0:
                    feat.setAttribute(idx, val)
                else:
                    unknown_fields.append(name)

        if wkt:
            geom = QgsGeometry.fromWkt(wkt)
            if geom.isNull():
                raise RuntimeError(f"Invalid WKT geometry: {wkt[:100]}")
            if not geom.isGeosValid():
                raise RuntimeError(
                    f"Geometry is not valid: {geom.lastError() or 'GEOS validation failed'}. "
                    "Fix the geometry or use validate_wkt to diagnose."
                )
            # Check geometry type matches layer
            from qgis.core import QgsWkbTypes
            layer_geom_type = layer.geometryType()
            wkt_geom_type = geom.type()
            if layer_geom_type != Qgis.GeometryType.Unknown and wkt_geom_type != layer_geom_type:
                from ..server import GEOMETRY_TYPE_NAMES
                raise RuntimeError(
                    f"Geometry type mismatch: layer expects "
                    f"{GEOMETRY_TYPE_NAMES.get(layer_geom_type, str(layer_geom_type))}, "
                    f"got {GEOMETRY_TYPE_NAMES.get(wkt_geom_type, str(wkt_geom_type))}"
                )
            feat.setGeometry(geom)

        count_before = layer.featureCount()
        layer.startEditing()
        ok = layer.addFeature(feat)
        if not ok:
            layer.rollBack()
            raise RuntimeError("Failed to add feature")
        if not layer.commitChanges():
            errors = layer.commitErrors()
            layer.rollBack()
            raise RuntimeError(f"Commit failed: {'; '.join(errors)}")

        result = {
            "layer_id": layer_id,
            "feature_id": feat.id(),
            "feature_count": layer.featureCount(),
        }
        if unknown_fields:
            result["warning"] = f"Unknown fields ignored: {', '.join(unknown_fields)}"
        return result

    def edit_feature(layer_id: str, feature_id: int, attributes: dict = None,
                     wkt: str = None, **_):
        """Update attributes and/or geometry of an existing feature by feature ID."""
        layer = s.get_layer_or_raise(layer_id)
        if layer.type() != Qgis.LayerType.Vector:
            raise RuntimeError(f"Not a vector layer: {layer_id}")

        # Verify feature exists
        feat = next(layer.getFeatures(QgsFeatureRequest(feature_id)), None)
        if feat is None:
            raise RuntimeError(f"Feature not found: {feature_id}")

        layer.startEditing()

        unknown_fields = []
        changed_attrs = []
        if attributes:
            for name, val in attributes.items():
                idx = layer.fields().indexFromName(name)
                if idx >= 0:
                    layer.changeAttributeValue(feature_id, idx, val)
                    changed_attrs.append(name)
                else:
                    unknown_fields.append(name)

        if wkt:
            geom = QgsGeometry.fromWkt(wkt)
            if geom.isNull():
                raise RuntimeError(f"Invalid WKT geometry: {wkt[:100]}")
            if not geom.isGeosValid():
                layer.rollBack()
                raise RuntimeError(
                    f"Geometry is not valid: {geom.lastError() or 'GEOS validation failed'}"
                )
            layer.changeGeometry(feature_id, geom)

        if not layer.commitChanges():
            errors = layer.commitErrors()
            layer.rollBack()
            raise RuntimeError(f"Commit failed: {'; '.join(errors)}")

        result = {
            "layer_id": layer_id,
            "feature_id": feature_id,
            "updated": True,
            "changed_attributes": changed_attrs,
            "geometry_updated": wkt is not None,
        }
        if unknown_fields:
            result["warning"] = f"Unknown fields ignored: {', '.join(unknown_fields)}"
        return result

    def delete_features(layer_id: str, feature_ids: list, **_):
        """Delete features by their IDs from a vector layer."""
        layer = s.get_layer_or_raise(layer_id)
        if layer.type() != Qgis.LayerType.Vector:
            raise RuntimeError(f"Not a vector layer: {layer_id}")

        count_before = layer.featureCount()
        layer.startEditing()
        ok = layer.deleteFeatures(feature_ids)
        if not ok:
            layer.rollBack()
            raise RuntimeError("Failed to delete features")
        if not layer.commitChanges():
            errors = layer.commitErrors()
            layer.rollBack()
            raise RuntimeError(f"Commit failed: {'; '.join(errors)}")

        count_after = layer.featureCount()
        return {
            "layer_id": layer_id,
            "requested": len(feature_ids),
            "deleted": count_before - count_after,
            "feature_count": count_after,
        }

    def select_by_expression(layer_id: str, expression: str, **_):
        """Select features matching a QGIS expression. Returns selected count."""
        layer = s.get_layer_or_raise(layer_id)
        if layer.type() != Qgis.LayerType.Vector:
            raise RuntimeError(f"Not a vector layer: {layer_id}")

        expr = QgsExpression(expression)
        if expr.hasParserError():
            raise RuntimeError(f"Expression error: {expr.parserErrorString()}")

        request = QgsFeatureRequest(expr)
        ids = [f.id() for f in layer.getFeatures(request)]
        layer.selectByIds(ids)
        return {"layer_id": layer_id, "selected_count": len(ids)}

    def select_by_location(layer_id: str, intersect_layer_id: str,
                           predicate: str = "intersects", **_):
        """Select features from one layer by spatial relationship with another layer.

        predicate: intersects, within, contains, crosses, touches, overlaps, disjoint
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

        result = processing.run("native:selectbylocation", {
            "INPUT": layer,
            "PREDICATE": [pred_value],
            "INTERSECT": intersect_layer,
            "METHOD": 0,  # new selection
        })
        selected = layer.selectedFeatureCount()
        return {"layer_id": layer_id, "selected_count": selected, "predicate": predicate}

    def clear_selection(layer_id: str, **_):
        """Clear selection on a vector layer."""
        layer = s.get_layer_or_raise(layer_id)
        if layer.type() != Qgis.LayerType.Vector:
            raise RuntimeError(f"Not a vector layer: {layer_id}")
        layer.removeSelection()
        return {"layer_id": layer_id, "cleared": True}

    def get_selected_features(layer_id: str, limit: int = 100, **_):
        """Return currently selected features with attributes and geometry."""
        layer = s.get_layer_or_raise(layer_id)
        if layer.type() != Qgis.LayerType.Vector:
            raise RuntimeError(f"Not a vector layer: {layer_id}")

        features = []
        for i, feat in enumerate(layer.getSelectedFeatures()):
            if i >= limit:
                break
            attrs = {}
            for field in layer.fields():
                val = feat.attribute(field.name())
                if not isinstance(val, (str, int, float, bool, type(None))):
                    val = str(val)
                attrs[field.name()] = val

            geom = None
            if feat.hasGeometry():
                g = feat.geometry()
                geom = {
                    "type": GEOMETRY_TYPE_NAMES.get(g.type(), str(int(g.type()))),
                    "wkt": g.asWkt(precision=4),
                }
            features.append({"id": feat.id(), "attributes": attrs, "geometry": geom})

        return {
            "layer_id": layer_id,
            "total_selected": layer.selectedFeatureCount(),
            "returned": len(features),
            "features": features,
        }

    def set_layer_filter(layer_id: str, expression: str = "", **_):
        """Set or clear a subset string (SQL WHERE clause) on a vector layer.

        Pass empty string to clear the filter.
        """
        layer = s.get_layer_or_raise(layer_id)
        if layer.type() != Qgis.LayerType.Vector:
            raise RuntimeError(f"Not a vector layer: {layer_id}")

        if not layer.setSubsetString(expression):
            raise RuntimeError(f"Failed to set filter: {expression}")
        return {
            "layer_id": layer_id,
            "filter": expression,
            "feature_count": layer.featureCount(),
        }

    def add_field(layer_id: str, name: str, type: str = "String",
                  length: int = 0, precision: int = 0, **_):
        """Add a new field to a vector layer.

        type: String, Integer, Double, Date, DateTime, Boolean, etc.
        """
        layer = s.get_layer_or_raise(layer_id)
        if layer.type() != Qgis.LayerType.Vector:
            raise RuntimeError(f"Not a vector layer: {layer_id}")

        type_map = {
            "string": QVariant.Type.String,
            "integer": QVariant.Type.Int,
            "int": QVariant.Type.Int,
            "double": QVariant.Type.Double,
            "float": QVariant.Type.Double,
            "date": QVariant.Type.Date,
            "datetime": QVariant.Type.DateTime,
            "boolean": QVariant.Type.Bool,
            "bool": QVariant.Type.Bool,
            "longlong": QVariant.Type.LongLong,
        }
        qtype = type_map.get(type.lower())
        if qtype is None:
            raise RuntimeError(
                f"Unknown field type: {type}. Use: {', '.join(type_map.keys())}"
            )

        field = QgsField(name, qtype)
        if length > 0:
            field.setLength(length)
        if precision > 0:
            field.setPrecision(precision)

        # Check for duplicate field name
        if layer.fields().indexFromName(name) >= 0:
            raise RuntimeError(f"Field already exists: {name}")

        layer.startEditing()
        ok = layer.addAttribute(field)
        if not ok:
            layer.rollBack()
            raise RuntimeError(f"Failed to add field: {name}")
        if not layer.commitChanges():
            errors = layer.commitErrors()
            layer.rollBack()
            raise RuntimeError(f"Commit failed: {'; '.join(errors)}")

        # Verify field was added
        new_idx = layer.fields().indexFromName(name)
        return {
            "layer_id": layer_id,
            "field": name,
            "type": type,
            "verified": new_idx >= 0,
            "field_count": layer.fields().count(),
        }

    def delete_field(layer_id: str, name: str, **_):
        """Delete a field from a vector layer by field name."""
        layer = s.get_layer_or_raise(layer_id)
        if layer.type() != Qgis.LayerType.Vector:
            raise RuntimeError(f"Not a vector layer: {layer_id}")

        idx = layer.fields().indexFromName(name)
        if idx < 0:
            raise RuntimeError(f"Field not found: {name}")

        layer.startEditing()
        ok = layer.deleteAttribute(idx)
        if not ok:
            layer.rollBack()
            raise RuntimeError(f"Failed to delete field: {name}")
        if not layer.commitChanges():
            errors = layer.commitErrors()
            layer.rollBack()
            raise RuntimeError(f"Commit failed: {'; '.join(errors)}")

        return {
            "layer_id": layer_id,
            "deleted_field": name,
            "verified": layer.fields().indexFromName(name) < 0,
            "field_count": layer.fields().count(),
        }

    def update_field_values(layer_id: str, field: str, expression: str, **_):
        """Update field values using a QGIS expression (like the field calculator).

        Example: field="area_km2", expression="$area / 1000000"
        """
        layer = s.get_layer_or_raise(layer_id)
        if layer.type() != Qgis.LayerType.Vector:
            raise RuntimeError(f"Not a vector layer: {layer_id}")

        idx = layer.fields().indexFromName(field)
        if idx < 0:
            raise RuntimeError(f"Field not found: {field}")

        expr = QgsExpression(expression)
        if expr.hasParserError():
            raise RuntimeError(f"Expression error: {expr.parserErrorString()}")

        from qgis.core import QgsExpressionContext, QgsExpressionContextUtils
        context = QgsExpressionContext()
        context.appendScopes(
            QgsExpressionContextUtils.globalProjectLayerScopes(layer)
        )

        layer.startEditing()
        count = 0
        for feat in layer.getFeatures():
            context.setFeature(feat)
            value = expr.evaluate(context)
            if expr.hasEvalError():
                layer.rollBack()
                raise RuntimeError(f"Expression eval error: {expr.evalErrorString()}")
            layer.changeAttributeValue(feat.id(), idx, value)
            count += 1
        layer.commitChanges()
        return {"layer_id": layer_id, "field": field, "updated_count": count}

    # ── Form Configuration ────────────────────────────────────────

    def set_form_config(layer_id: str, layout_type: str = "auto",
                        suppress_on_add: bool = False, **_):
        """Set attribute form configuration for a vector layer.

        layout_type: 'auto' (auto-generated), 'drag_and_drop' (drag-and-drop designer),
                     'custom' (custom UI file).
        suppress_on_add: if True, suppress the form when adding new features.
        """
        layer = s.get_layer_or_raise(layer_id)
        if layer.type() != Qgis.LayerType.Vector:
            raise RuntimeError(f"Not a vector layer: {layer_id}")

        from qgis.core import QgsEditFormConfig
        config = layer.editFormConfig()

        layout_map = {
            "auto": Qgis.AttributeFormLayout.AutoGenerated,
            "drag_and_drop": Qgis.AttributeFormLayout.DragAndDrop,
            "custom": Qgis.AttributeFormLayout.UiFile,
        }
        lt = layout_map.get(layout_type.lower())
        if lt is None:
            raise RuntimeError(
                f"Unknown layout type: {layout_type}. Use: {', '.join(layout_map.keys())}"
            )

        config.setLayout(lt)

        suppress_map = {
            True: Qgis.AttributeFormSuppression.On,
            False: Qgis.AttributeFormSuppression.Default,
        }
        config.setSuppress(suppress_map[suppress_on_add])

        layer.setEditFormConfig(config)

        return {
            "layer_id": layer_id,
            "layout_type": layout_type,
            "suppress_on_add": suppress_on_add,
        }

    def set_field_widget(layer_id: str, field_name: str, widget_type: str,
                         config: dict = None, **_):
        """Configure the edit widget for a field on a vector layer.

        widget_type: TextEdit, Range, DateTime, ValueMap, CheckBox, UniqueValues,
                     Hidden, ExternalResource, RelationReference, Classification.
        config: dict of widget-specific configuration options:
          - Range: {"Min": 0, "Max": 100, "Step": 1}
          - ValueMap: {"map": [{"display": "Yes", "value": "1"}, {"display": "No", "value": "0"}]}
          - CheckBox: {"CheckedState": "1", "UncheckedState": "0"}
          - TextEdit: {"IsMultiline": True}
          - DateTime: {"display_format": "yyyy-MM-dd", "calendar_popup": True}
        """
        layer = s.get_layer_or_raise(layer_id)
        if layer.type() != Qgis.LayerType.Vector:
            raise RuntimeError(f"Not a vector layer: {layer_id}")

        idx = layer.fields().indexFromName(field_name)
        if idx < 0:
            raise RuntimeError(f"Field not found: {field_name}")

        from qgis.core import QgsEditorWidgetSetup
        widget_config = config or {}
        setup = QgsEditorWidgetSetup(widget_type, widget_config)
        layer.setEditorWidgetSetup(idx, setup)

        return {
            "layer_id": layer_id,
            "field_name": field_name,
            "widget_type": widget_type,
        }

    s._HANDLERS.update({
        "add_feature": add_feature,
        "edit_feature": edit_feature,
        "delete_features": delete_features,
        "select_by_expression": select_by_expression,
        "select_by_location": select_by_location,
        "clear_selection": clear_selection,
        "get_selected_features": get_selected_features,
        "set_layer_filter": set_layer_filter,
        "add_field": add_field,
        "delete_field": delete_field,
        "update_field_values": update_field_values,
        "set_form_config": set_form_config,
        "set_field_widget": set_field_widget,
    })
