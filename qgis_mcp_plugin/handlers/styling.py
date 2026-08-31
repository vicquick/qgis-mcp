"""
Styling handlers — renderers, symbols, color ramps, opacity, style files.
"""

from qgis.core import (
    Qgis,
    QgsCategorizedSymbolRenderer,
    QgsFillSymbol,
    QgsGradientColorRamp,
    QgsGraduatedSymbolRenderer,
    QgsLineSymbol,
    QgsMarkerSymbol,
    QgsProject,
    QgsRendererCategory,
    QgsRendererRange,
    QgsRuleBasedRenderer,
    QgsSingleSymbolRenderer,
    QgsStyle,
    QgsSymbol,
)
from qgis.PyQt.QtGui import QColor

from ..server import GEOMETRY_TYPE_NAMES


def _make_symbol(geom_type, color=None, size=None):
    """Create a symbol appropriate for the geometry type."""
    if geom_type == Qgis.GeometryType.Point:
        symbol = QgsMarkerSymbol.createSimple({})
        if size is not None:
            symbol.setSize(size)
    elif geom_type == Qgis.GeometryType.Line:
        symbol = QgsLineSymbol.createSimple({})
        if size is not None:
            symbol.setWidth(size)
    else:
        symbol = QgsFillSymbol.createSimple({})

    if color:
        symbol.setColor(QColor(color))
    return symbol


def register(server):
    """Register styling handlers."""
    s = server

    def set_layer_style(layer_id: str, style_type: str,
                        color: str = None, size: float = None,
                        opacity: float = None, field: str = None,
                        categories: list = None, ranges: list = None,
                        rules: list = None, **_):
        """Apply a renderer style to a vector layer.

        style_type: "single", "categorized", "graduated", or "rule_based"

        For "single": color (hex), size (float), opacity (0-1)
        For "categorized": field, categories [{value, color, label}, ...]
        For "graduated": field, ranges [{lower, upper, color, label}, ...]
        For "rule_based": rules [{expression, color, label, size}, ...]
        """
        layer = s.get_layer_or_raise(layer_id)
        if layer.type() != Qgis.LayerType.Vector:
            raise RuntimeError(f"Not a vector layer: {layer_id}")

        geom_type = layer.geometryType()

        if style_type == "single":
            symbol = _make_symbol(geom_type, color, size)
            renderer = QgsSingleSymbolRenderer(symbol)
            layer.setRenderer(renderer)
            if opacity is not None:
                layer.setOpacity(max(0.0, min(1.0, opacity)))

        elif style_type == "categorized":
            if not field:
                raise RuntimeError("'field' is required for categorized style")
            if not categories:
                raise RuntimeError("'categories' list is required for categorized style")

            cat_list = []
            for cat in categories:
                sym = _make_symbol(geom_type, cat.get("color"), size)
                cat_list.append(
                    QgsRendererCategory(
                        cat["value"], sym, cat.get("label", str(cat["value"])),
                    )
                )
            renderer = QgsCategorizedSymbolRenderer(field, cat_list)
            layer.setRenderer(renderer)

        elif style_type == "graduated":
            if not field:
                raise RuntimeError("'field' is required for graduated style")
            if not ranges:
                raise RuntimeError("'ranges' list is required for graduated style")

            range_list = []
            for r in ranges:
                sym = _make_symbol(geom_type, r.get("color"), size)
                range_list.append(
                    QgsRendererRange(
                        r["lower"], r["upper"], sym,
                        r.get("label", f"{r['lower']} - {r['upper']}"),
                    )
                )
            renderer = QgsGraduatedSymbolRenderer(field, range_list)
            layer.setRenderer(renderer)

        elif style_type == "rule_based":
            if not rules:
                raise RuntimeError("'rules' list is required for rule_based style")

            root_rule = QgsRuleBasedRenderer.Rule(None)
            for rule_def in rules:
                sym = _make_symbol(geom_type, rule_def.get("color"), rule_def.get("size"))
                rule = QgsRuleBasedRenderer.Rule(sym)
                rule.setFilterExpression(rule_def.get("expression", ""))
                rule.setLabel(rule_def.get("label", ""))
                if "min_scale" in rule_def:
                    rule.setMinimumScale(rule_def["min_scale"])
                if "max_scale" in rule_def:
                    rule.setMaximumScale(rule_def["max_scale"])
                root_rule.appendChild(rule)
            renderer = QgsRuleBasedRenderer(root_rule)
            layer.setRenderer(renderer)

        else:
            raise RuntimeError(
                f"Unknown style_type: {style_type}. "
                "Use 'single', 'categorized', 'graduated', or 'rule_based'."
            )

        layer.triggerRepaint()
        return {"layer_id": layer_id, "style_type": style_type}

    def get_layer_style(layer_id: str, **_):
        """Return current renderer info: type, field, categories/ranges/rules."""
        layer = s.get_layer_or_raise(layer_id)
        if layer.type() != Qgis.LayerType.Vector:
            raise RuntimeError(f"Not a vector layer: {layer_id}")

        renderer = layer.renderer()
        if not renderer:
            return {"layer_id": layer_id, "renderer_type": None}

        result = {
            "layer_id": layer_id,
            "renderer_type": type(renderer).__name__,
            "opacity": layer.opacity(),
        }

        if isinstance(renderer, QgsSingleSymbolRenderer):
            sym = renderer.symbol()
            result["color"] = sym.color().name()

        elif isinstance(renderer, QgsCategorizedSymbolRenderer):
            result["field"] = renderer.classAttribute()
            result["categories"] = []
            for cat in renderer.categories():
                result["categories"].append({
                    "value": cat.value() if not isinstance(cat.value(), type(None)) else None,
                    "label": cat.label(),
                    "color": cat.symbol().color().name(),
                })

        elif isinstance(renderer, QgsGraduatedSymbolRenderer):
            result["field"] = renderer.classAttribute()
            result["ranges"] = []
            for rng in renderer.ranges():
                result["ranges"].append({
                    "lower": rng.lowerValue(),
                    "upper": rng.upperValue(),
                    "label": rng.label(),
                    "color": rng.symbol().color().name(),
                })

        elif isinstance(renderer, QgsRuleBasedRenderer):
            result["rules"] = []
            for rule in renderer.rootRule().children():
                result["rules"].append({
                    "label": rule.label(),
                    "expression": rule.filterExpression(),
                    "color": rule.symbol().color().name() if rule.symbol() else None,
                })

        return result

    def set_layer_color(layer_id: str, color: str, **_):
        """Quick color change for a layer with a simple symbol renderer.

        If the layer doesn't have a single symbol renderer, creates one.
        """
        layer = s.get_layer_or_raise(layer_id)
        if layer.type() != Qgis.LayerType.Vector:
            raise RuntimeError(f"Not a vector layer: {layer_id}")

        renderer = layer.renderer()
        if isinstance(renderer, QgsSingleSymbolRenderer):
            renderer.symbol().setColor(QColor(color))
        else:
            symbol = _make_symbol(layer.geometryType(), color)
            layer.setRenderer(QgsSingleSymbolRenderer(symbol))

        layer.triggerRepaint()
        return {"layer_id": layer_id, "color": color}

    def set_color_ramp(layer_id: str, color1: str = "#ffffcc", color2: str = "#006837",
                       field: str = None, num_classes: int = 5,
                       method: str = "equal_interval", **_):
        """Apply a gradient color ramp to a graduated renderer.

        method: equal_interval, quantile, jenks, pretty_breaks, std_dev
        """
        layer = s.get_layer_or_raise(layer_id)
        if layer.type() != Qgis.LayerType.Vector:
            raise RuntimeError(f"Not a vector layer: {layer_id}")

        if not field:
            renderer = layer.renderer()
            if isinstance(renderer, QgsGraduatedSymbolRenderer):
                field = renderer.classAttribute()
            if not field:
                raise RuntimeError("'field' is required when no graduated renderer exists")

        ramp = QgsGradientColorRamp(QColor(color1), QColor(color2))

        method_map = {
            "equal_interval": QgsGraduatedSymbolRenderer.Mode.EqualInterval,
            "quantile": QgsGraduatedSymbolRenderer.Mode.Quantile,
            "jenks": QgsGraduatedSymbolRenderer.Mode.Jenks,
            "pretty_breaks": QgsGraduatedSymbolRenderer.Mode.Pretty,
            "std_dev": QgsGraduatedSymbolRenderer.Mode.StdDev,
        }
        mode = method_map.get(method.lower(), QgsGraduatedSymbolRenderer.Mode.EqualInterval)

        renderer = QgsGraduatedSymbolRenderer(field)
        renderer.setSourceColorRamp(ramp)
        renderer.setMode(mode)
        renderer.updateClasses(layer, num_classes)
        layer.setRenderer(renderer)
        layer.triggerRepaint()

        return {
            "layer_id": layer_id,
            "field": field,
            "num_classes": num_classes,
            "method": method,
        }

    def apply_style_from_file(layer_id: str, path: str, **_):
        """Apply a .qml style file to a layer."""
        layer = s.get_layer_or_raise(layer_id)
        msg, success = layer.loadNamedStyle(path)
        if not success:
            raise RuntimeError(f"Failed to load style: {msg}")
        layer.triggerRepaint()
        return {"layer_id": layer_id, "style_file": path}

    def save_style_to_file(layer_id: str, path: str, **_):
        """Save a layer's current style to a .qml file."""
        layer = s.get_layer_or_raise(layer_id)
        msg, success = layer.saveNamedStyle(path)
        if not success:
            raise RuntimeError(f"Failed to save style: {msg}")
        return {"layer_id": layer_id, "saved_to": path}

    def list_style_presets(**_):
        """List available styles in the QGIS default style library."""
        style = QgsStyle.defaultStyle()
        return {
            "symbol_count": style.symbolCount(),
            "color_ramp_count": style.colorRampCount(),
            "symbols": style.symbolNames()[:50],
            "color_ramps": style.colorRampNames()[:50],
        }

    s._HANDLERS.update({
        "set_layer_style": set_layer_style,
        "get_layer_style": get_layer_style,
        "set_layer_color": set_layer_color,
        "set_color_ramp": set_color_ramp,
        "apply_style_from_file": apply_style_from_file,
        "save_style_to_file": save_style_to_file,
        "list_style_presets": list_style_presets,
    })
