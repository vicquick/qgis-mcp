"""
Labeling handlers — label configuration, text format, placement, data-defined properties.
"""

from qgis.core import (
    Qgis,
    QgsPalLayerSettings,
    QgsProperty,
    QgsTextBufferSettings,
    QgsTextFormat,
    QgsVectorLayerSimpleLabeling,
)
from qgis.PyQt.QtGui import QColor, QFont


def register(server):
    """Register labeling handlers."""
    s = server

    def set_layer_labels(layer_id: str, field: str, enabled: bool = True,
                         font_size: float = 10, color: str = "#000000",
                         font_family: str = None, font_bold: bool = False,
                         font_italic: bool = False,
                         buffer_enabled: bool = False, buffer_size: float = 1.0,
                         buffer_color: str = "#ffffff",
                         placement: str = "around_point",
                         priority: float = 5.0,
                         is_expression: bool = False, **_):
        """Configure labels for a vector layer.

        field: field name or expression (set is_expression=True for expressions).
        placement: around_point, over_point, parallel, curved, horizontal, free.
        priority: 0 (low) to 10 (high).
        """
        layer = s.get_layer_or_raise(layer_id)
        if layer.type() != Qgis.LayerType.Vector:
            raise RuntimeError(f"Not a vector layer: {layer_id}")

        settings = QgsPalLayerSettings()
        settings.fieldName = field
        settings.isExpression = is_expression

        # Text format
        text_format = QgsTextFormat()
        font = QFont()
        if font_family:
            font.setFamily(font_family)
        font.setPointSizeF(font_size)
        font.setBold(font_bold)
        font.setItalic(font_italic)
        text_format.setFont(font)
        text_format.setColor(QColor(color))
        text_format.setSize(font_size)

        # Buffer (halo)
        if buffer_enabled:
            buf = QgsTextBufferSettings()
            buf.setEnabled(True)
            buf.setSize(buffer_size)
            buf.setColor(QColor(buffer_color))
            text_format.setBuffer(buf)

        settings.setFormat(text_format)

        # Placement
        placement_map = {
            "around_point": Qgis.LabelPlacement.AroundPoint,
            "over_point": Qgis.LabelPlacement.OverPoint,
            "parallel": Qgis.LabelPlacement.Line,
            "curved": Qgis.LabelPlacement.Curved,
            "horizontal": Qgis.LabelPlacement.Horizontal,
            "free": Qgis.LabelPlacement.Free,
        }
        settings.placement = placement_map.get(placement, Qgis.LabelPlacement.AroundPoint)

        # Priority
        settings.priority = max(0.0, min(10.0, priority))

        labeling = QgsVectorLayerSimpleLabeling(settings)
        layer.setLabeling(labeling)
        layer.setLabelsEnabled(enabled)
        layer.triggerRepaint()

        return {"layer_id": layer_id, "field": field, "enabled": enabled, "placement": placement}

    def remove_layer_labels(layer_id: str, **_):
        """Disable and remove labels from a vector layer."""
        layer = s.get_layer_or_raise(layer_id)
        if layer.type() != Qgis.LayerType.Vector:
            raise RuntimeError(f"Not a vector layer: {layer_id}")

        layer.setLabelsEnabled(False)
        layer.triggerRepaint()
        return {"layer_id": layer_id, "labels_enabled": False}

    def set_data_defined_property(layer_id: str, property_key: str, expression: str, **_):
        """Set a data-defined override on a label or symbol property using an expression.

        property_key examples: Size, Color, Rotation, OffsetX, OffsetY, FontSize, BufferSize, etc.
        The expression is evaluated per-feature.
        """
        layer = s.get_layer_or_raise(layer_id)
        if layer.type() != Qgis.LayerType.Vector:
            raise RuntimeError(f"Not a vector layer: {layer_id}")

        # Try to set on labeling
        labeling = layer.labeling()
        if labeling:
            settings = labeling.settings()
            prop = QgsProperty.fromExpression(expression)

            # Map common property names to QgsPalLayerSettings property keys
            prop_map = {
                "Size": QgsPalLayerSettings.Property.Size,
                "Color": QgsPalLayerSettings.Property.Color,
                "Rotation": QgsPalLayerSettings.Property.LabelRotation,
                "FontSize": QgsPalLayerSettings.Property.Size,
                "BufferSize": QgsPalLayerSettings.Property.BufferSize,
                "BufferColor": QgsPalLayerSettings.Property.BufferColor,
                "OffsetXY": QgsPalLayerSettings.Property.OffsetXY,
                "Bold": QgsPalLayerSettings.Property.Bold,
                "Italic": QgsPalLayerSettings.Property.Italic,
                "Show": QgsPalLayerSettings.Property.Show,
                "MinScale": QgsPalLayerSettings.Property.MinimumScale,
                "MaxScale": QgsPalLayerSettings.Property.MaximumScale,
            }
            pal_key = prop_map.get(property_key)
            if pal_key is not None:
                dd = settings.dataDefinedProperties()
                dd.setProperty(pal_key, prop)
                settings.setDataDefinedProperties(dd)
                new_labeling = QgsVectorLayerSimpleLabeling(settings)
                layer.setLabeling(new_labeling)
                layer.triggerRepaint()
                return {
                    "layer_id": layer_id,
                    "target": "labeling",
                    "property": property_key,
                    "expression": expression,
                }

        # Try to set on renderer symbol
        renderer = layer.renderer()
        if renderer and renderer.symbol():
            symbol = renderer.symbol()
            prop = QgsProperty.fromExpression(expression)

            # For symbol-level data-defined properties
            for i in range(symbol.symbolLayerCount()):
                sl = symbol.symbolLayer(i)
                dd = sl.dataDefinedProperties()
                # Use the property key string directly
                dd.setProperty(property_key, prop)
                sl.setDataDefinedProperties(dd)

            layer.triggerRepaint()
            return {
                "layer_id": layer_id,
                "target": "symbol",
                "property": property_key,
                "expression": expression,
            }

        raise RuntimeError(f"Could not set data-defined property: {property_key}")

    # ── Rule-Based Labeling ───────────────────────────────────────

    def set_rule_based_labels(layer_id: str, rules: list, **_):
        """Configure rule-based labeling on a vector layer.

        rules: list of dicts, each with:
          - expression: filter expression (e.g. '"pop" > 1000000'), use '' for ELSE
          - field: field name or expression for label text
          - font_size: float (default 10)
          - color: hex color (default '#000000')
          - label: rule description/label
          - enabled: bool (default True)
          - min_scale: float (optional, e.g. 100000)
          - max_scale: float (optional, e.g. 1000)
          - is_expression: bool (default False) — set True if 'field' is an expression
          - buffer_enabled: bool (default False)
          - buffer_size: float (default 1.0)
          - buffer_color: hex color (default '#ffffff')
        """
        layer = s.get_layer_or_raise(layer_id)
        if layer.type() != Qgis.LayerType.Vector:
            raise RuntimeError(f"Not a vector layer: {layer_id}")

        from qgis.core import QgsRuleBasedLabeling

        root_rule = QgsRuleBasedLabeling.Rule(None)

        for rule_def in rules:
            settings = QgsPalLayerSettings()
            settings.fieldName = rule_def.get("field", "")
            settings.isExpression = rule_def.get("is_expression", False)

            # Text format
            text_format = QgsTextFormat()
            font = QFont()
            font_size = rule_def.get("font_size", 10)
            font.setPointSizeF(font_size)
            text_format.setFont(font)
            text_format.setColor(QColor(rule_def.get("color", "#000000")))
            text_format.setSize(font_size)

            # Buffer
            if rule_def.get("buffer_enabled", False):
                buf = QgsTextBufferSettings()
                buf.setEnabled(True)
                buf.setSize(rule_def.get("buffer_size", 1.0))
                buf.setColor(QColor(rule_def.get("buffer_color", "#ffffff")))
                text_format.setBuffer(buf)

            settings.setFormat(text_format)

            child_rule = QgsRuleBasedLabeling.Rule(settings)
            child_rule.setDescription(rule_def.get("label", ""))
            child_rule.setActive(rule_def.get("enabled", True))

            expression = rule_def.get("expression", "")
            if expression:
                child_rule.setFilterExpression(expression)
            else:
                child_rule.setIsElse(True)

            # Scale-based visibility
            min_scale = rule_def.get("min_scale")
            max_scale = rule_def.get("max_scale")
            if min_scale is not None or max_scale is not None:
                child_rule.setScaleMinDenom(int(max_scale) if max_scale else 0)
                child_rule.setScaleMaxDenom(int(min_scale) if min_scale else 0)

            root_rule.appendChild(child_rule)

        labeling = QgsRuleBasedLabeling(root_rule)
        layer.setLabeling(labeling)
        layer.setLabelsEnabled(True)
        layer.triggerRepaint()

        return {
            "layer_id": layer_id,
            "rule_count": len(rules),
            "labeling_type": "rule_based",
        }

    s._HANDLERS.update({
        "set_layer_labels": set_layer_labels,
        "remove_layer_labels": remove_layer_labels,
        "set_data_defined_property": set_data_defined_property,
        "set_rule_based_labels": set_rule_based_labels,
    })
