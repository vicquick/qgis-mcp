"""
Layout pre-flight: what to fix before an export, and where the map items sit
so the bridge's check_export can look at those areas in the output.

Everything here is a read: it reports, it never changes the layout.
"""

import os
import re

from qgis.core import (
    QgsExpression,
    QgsLayoutItemLabel,
    QgsLayoutItemLegend,
    QgsLayoutItemMap,
    QgsLayoutItemPicture,
    QgsLayoutObject,
    QgsProject,
    QgsUnitTypes,
)

_EXPR_RE = re.compile(r"\[%(.*?)%\]", re.S)

# Providers whose tiles come over the network and can render blank on a page
# while the export still reports success.
_ONLINE_PROVIDERS = {"wms", "xyz", "wcs", "arcgismapserver", "arcgisfeatureserver",
                     "wfs", "oapif", "vectortile"}


def _map_layers(project, item):
    if item.followVisibilityPreset():
        theme = item.followVisibilityPresetName()
        return project.mapThemeCollection().mapThemeVisibleLayers(theme), theme
    if item.keepLayerSet():
        return item.layers(), None
    root = project.layerTreeRoot()
    return [n.layer() for n in root.findLayers() if n.isVisible() and n.layer()], None


def _is_online(layer):
    prov = (layer.providerType() or "").lower()
    if prov in _ONLINE_PROVIDERS:
        return True
    return prov == "vectortile" or "url=http" in (layer.source() or "")


def _picture_dd_active(item):
    try:
        prop = QgsLayoutObject.DataDefinedProperty.PictureSource
    except AttributeError:
        prop = getattr(QgsLayoutObject, "PictureSource", None)
    try:
        return prop is not None and item.dataDefinedProperties().isActive(prop)
    except Exception:
        return False


def register(server):
    s = server

    def check_layout(layout_name: str, **_):
        """Pre-export check of a print layout. Reports issues (legend without a
        linked map, missing picture files, unresolved [% %] in labels, invalid
        or online layers in maps, empty atlas) and the page/map geometry that
        check_export uses to look for blank map areas in the exported file."""
        project = QgsProject.instance()
        layout = project.layoutManager().layoutByName(layout_name)
        if layout is None:
            raise RuntimeError(f"Layout not found: {layout_name}")
        issues = []

        def issue(severity, item, text):
            issues.append({"severity": severity, "item": item, "issue": text})

        mm = layout.units() == QgsUnitTypes.LayoutUnit.LayoutMillimeters \
            if hasattr(QgsUnitTypes, "LayoutUnit") else True
        pages = []
        pc = layout.pageCollection()
        for i in range(pc.pageCount()):
            pg = pc.page(i)
            pages.append({"index": i, "width": round(pg.rect().width(), 2),
                          "height": round(pg.rect().height(), 2)})

        atlas = layout.atlas()
        atlas_info = {"enabled": atlas.enabled()}
        if atlas.enabled():
            cov = atlas.coverageLayer()
            atlas_info["coverage_layer"] = cov.name() if cov else None
            atlas_info["filter"] = atlas.filterExpression() if atlas.filterFeatures() else None
            count = atlas.updateFeatures()
            atlas_info["count"] = count
            if cov is None:
                issue("error", "atlas", "atlas has no coverage layer")
            elif count == 0:
                issue("error", "atlas", "atlas filter leaves no features")

        maps, legends = [], []
        for item in layout.items():
            iid = getattr(item, "id", lambda: "")() or getattr(item, "uuid", lambda: "")()
            if isinstance(item, QgsLayoutItemMap):
                layers, theme = _map_layers(project, item)
                online = sorted({l.name() for l in layers if _is_online(l)})
                invalid = sorted({l.name() for l in layers if not l.isValid()})
                pos = item.pagePos()
                rect = item.rect()
                maps.append({
                    "id": iid, "page": item.page(), "theme": theme,
                    "x": round(pos.x(), 2), "y": round(pos.y(), 2),
                    "width": round(rect.width(), 2), "height": round(rect.height(), 2),
                    "layers": len(layers), "online_layers": online,
                    "atlas_driven": bool(item.atlasDriven()),
                })
                if not layers:
                    issue("error", iid, "map shows no layers")
                if invalid:
                    issue("error", iid, f"invalid layers: {invalid}")
                if online:
                    issue("info", iid, f"online layers can render blank on single pages: {online}")
                if theme and theme not in project.mapThemeCollection().mapThemes():
                    issue("error", iid, f"follows missing map theme '{theme}'")
            elif isinstance(item, QgsLayoutItemLegend):
                linked = item.linkedMap()
                legends.append({"id": iid, "linked_map": linked.id() if linked else None})
                if linked is None:
                    issue("warning", iid, "legend has no linked map: it shows the layers' "
                          "current styles, not the map's theme")
            elif isinstance(item, QgsLayoutItemPicture):
                path = item.picturePath()
                if not _picture_dd_active(item) and path and not path.startswith(
                        ("http", "base64:")) and not os.path.exists(path):
                    issue("error", iid, f"picture file missing: {path}")
            elif isinstance(item, QgsLayoutItemLabel):
                # currentText() is only evaluated once an atlas page rendered,
                # so "[%" in it says nothing. Parse each expression instead and
                # report the ones that cannot work on any page.
                for expr in _EXPR_RE.findall(item.text() or ""):
                    e = QgsExpression(expr)
                    if e.hasParserError():
                        issue("error", iid, f"label expression does not parse: "
                              f"{expr.strip()[:80]} ({e.parserErrorString()[:120]})")

        return {
            "layout": layout_name,
            "units_mm": bool(mm),
            "pages": pages,
            "atlas": atlas_info,
            "maps": maps,
            "legends": legends,
            "issues": issues,
            "ok": not any(i["severity"] == "error" for i in issues),
        }

    s._HANDLERS.update({
        "check_layout": check_layout,
    })
