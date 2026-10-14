"""Field-tested rules for driving a live QGIS through this server.

Each rule is something that crashed, hung or silently misbehaved in a real
session, written down so the next agent does not rediscover it. They are
served as MCP resources (qgis://rules/<slug>) and through the search_rules
tool. Keep them generic: this repository is public.

A rule has: slug, title, severity ("crash" | "hang" | "silent" | "api"),
keywords (extra search words) and text (Markdown).
"""

RULES = [
    {
        "slug": "no-project-write",
        "title": "Never call QgsProject.write() from execute_code",
        "severity": "crash",
        "keywords": "save project write qgz ctrl+s save_project",
        "text": """\
`QgsProject.instance().write()` (and save_project, which wraps it) runs inside
the plugin's socket slot, not from the event loop. If QGIS needs to ask
something (uncommitted edits), the dialog dies instead of asking — this has
crashed QGIS.

Safe pattern: queue the GUI save action, the same code path as Ctrl+S:

```python
from qgis.PyQt.QtCore import QTimer
p = QgsProject.instance()
assert not [l.name() for l in p.mapLayers().values()
            if hasattr(l, 'isEditable') and l.isEditable()]
p.setDirty(True)   # theme edits do not set dirty; a clean project saves nothing
QTimer.singleShot(0, iface.actionSaveProject().trigger)
```

It returns at once; QGIS saves on the next event-loop pass. Verify with
`p.isDirty()` and the file's mtime afterwards. Do not open/unzip the .qgz
while the save runs ("Unable to perform zip"). Better still: ask the user to
press Ctrl+S.""",
    },
    {
        "slug": "qgsfunction-register-once",
        "title": "Never register the same @qgsfunction twice",
        "severity": "crash",
        "keywords": "expression function qgsfunction register reload import exec_module",
        "text": """\
Executing a module with `@qgsfunction` decorators a second time in a running
QGIS (exec_module, console import, a build script) re-registers the functions
and has crashed QGIS. Two agents sharing one QGIS do not see each other's
registrations.

Before registering: `QgsExpression.isFunctionName('name')`. To reload, first
`QgsExpression.unregisterFunction('name')` and `del sys.modules['module']`,
then import again. `importlib.reload()` does not re-register. Prefer the
profile's `python/expressions/` autoload folder over live registration.""",
    },
    {
        "slug": "layout-clone-render",
        "title": "Layout clone() + atlas rendering, then rebuilding the layout, corrupts the heap",
        "severity": "crash",
        "keywords": "layout clone atlas beginRender seekTo renderRegionToImage rebuild",
        "text": """\
`QgsPrintLayout.clone()` with `atlas.beginRender()/seekTo()/renderRegionToImage()`
on the clone, repeated in one session, and then rebuilding the real layout
crashed QGIS with heap corruption (0xC0000374). Clones held only by a Python
variable are never released but keep atlas/render state on the shared
coverage layer.

Measure in the real layout instead (temporarily resize the item, render the
region, restore). If a clone is unavoidable: exactly one, `atlas.endRender()`
in `finally`, `del` the clone, and no layout rebuild in the same session.""",
    },
    {
        "slug": "render-deadlock-layer-expressions",
        "title": "Layer-referencing expressions + waitForFinished() deadlock QGIS",
        "severity": "hang",
        "keywords": "get_feature get_feature_by_id aggregate geometry generator render waitForFinished parallel job freeze",
        "text": """\
Symbols whose expressions read another layer (`get_feature*`, `aggregate`,
`overlay_*`) and a `QgsMapRendererParallelJob(...).waitForFinished()` inside
execute_code froze QGIS at 0 % CPU: the render threads need that layer's
feature source while the main thread is blocked waiting for them.

Render through `QgsLayoutExporter`, `QgsMapRendererSequentialJob`, or the
export/screenshot tools. For clipping one layer by another, precompute the
geometry once (a database view or a GeoPackage) instead of per-feature
expressions.""",
    },
    {
        "slug": "execute-code-hazards",
        "title": "Other execute_code calls that have crashed or wedged QGIS",
        "severity": "crash",
        "keywords": "execute_code painter render atlas currentFeature pip subprocess sys.executable",
        "text": """\
- `QgsLayoutItem.render()` with a hand-built QPainter context: crashed. Use the
  layout export tools.
- `atlas.currentFeature()` between `beginRender()` and `endRender()`: crashed.
  Walk the filtered coverage layer with a QgsFeatureRequest instead.
- `subprocess.run([sys.executable, '-m', 'pip', ...])`: inside QGIS
  `sys.executable` is the QGIS binary, which opens every argument as a data
  source and spams modal dialogs. Install packages from outside QGIS.
- Batch related changes into one execute_code call, and ask the user to save
  before anything risky (rendering, reloads, atlas loops).""",
    },
    {
        "slug": "renderer-clone-pattern",
        "title": "Edit renderers on a clone, then set the whole renderer back",
        "severity": "silent",
        "keywords": "renderer rule based symbol layer appendSymbolLayer clone setRenderer",
        "text": """\
Changing a sub-symbol of the live renderer in place (e.g. `appendSymbolLayer`
on a rule's symbol) is silently discarded. Clone the whole renderer, edit the
clone, `layer.setRenderer(clone)`, then `layer.triggerRepaint()` and
`iface.layerTreeView().refreshLayerSymbology(layer.id())`.""",
    },
    {
        "slug": "named-style-sync",
        "title": "setRenderer/setLabeling do not update the current named style",
        "severity": "silent",
        "keywords": "style manager setCurrentStyle named style removeStyle addStyleFromLayer labeling revert",
        "text": """\
Live changes are not written into the current named style of
`layer.styleManager()`; the next `setCurrentStyle` (also internal refreshes)
reverts them. To persist: switch to another style and back — but switching
away writes the live state into that other style's slot, so pick a throwaway
style. In style loops capture `QgsMapLayerStyle().readFromLayer(layer)` before
`removeStyle()` (removing the active style reloads another one and wipes
`setLabeling`), then `addStyle(name, captured)`; avoid `addStyleFromLayer` there.""",
    },
    {
        "slug": "legend-unlinked-map",
        "title": "A layout legend without a linked map follows the layers' current style",
        "severity": "silent",
        "keywords": "legend linkedMap theme export layout style switch",
        "text": """\
An unlinked legend has no map theme to take style overrides from, so any style
switch anywhere in the project changes it, while the map items still follow
their themes. Before exporting, check `legend.linkedMap()` for every legend;
fix with `legend.setLinkedMap(map_item); legend.updateLegend()`. Linking also
enables filter-by-map, so categories without features in view drop out.""",
    },
    {
        "slug": "theme-checked-legend-items",
        "title": "Map themes re-check every category unless the record uses legend items",
        "severity": "silent",
        "keywords": "map theme category render false checkedLegendItems usingLegendItems",
        "text": """\
Category on/off state belongs to the map theme record, not the style. A record
with `usingLegendItems == False` turns every category on, ignoring
`render="false"` in the style. To hide categories in theme-driven layouts set
`rec.usingLegendItems = True` and `rec.checkedLegendItems = {ruleKeys...}`,
then remove and re-insert the theme. Theme edits do not mark the project
dirty — call `setDirty(True)` before saving.""",
    },
    {
        "slug": "auxiliary-storage-shadows-dd",
        "title": "Auxiliary storage overrides data-defined label positions",
        "severity": "silent",
        "keywords": "label position auxiliary storage move label data defined PositionX PositionY",
        "text": """\
Dragging labels with the Move Label tool writes X/Y into the layer's
auxiliary storage, which wins over a data-defined PositionX/PositionY bound
to your own fields. Inspect `layer.auxiliaryLayer()` and delete its features
before seeding position fields.""",
    },
    {
        "slug": "polygon-label-dd-fallback",
        "title": "Large polygons ignore data-defined label XY when clipped by the view",
        "severity": "silent",
        "keywords": "polygon label data defined position jumps zoom fallback placement",
        "text": """\
When the viewport clips a large polygon, PAL re-derives the anchor and the
label moves despite data-defined X/Y. Fix:
`settings.placementSettings().setAllowDegradedPlacement(False)`
("Allow inferior fallback placements" off).""",
    },
    {
        "slug": "pdf-force-vector-drops-effects",
        "title": "PDF export with forceVectorOutput drops paint effects",
        "severity": "silent",
        "keywords": "pdf export forceVectorOutput drop shadow paint effect layout exporter",
        "text": """\
`PdfExportSettings.forceVectorOutput = True` skips paint effects (drop
shadows etc.) without a warning. Export with `forceVectorOutput=False` and
`textRenderFormat=AlwaysText` (text stays vector, effects rasterize), and look
at a render of the PDF — success codes and text checks do not catch it.""",
    },
    {
        "slug": "export-visual-check",
        "title": "Exports report success for blank or wrong maps",
        "severity": "silent",
        "keywords": "export atlas wms blank page verify screenshot",
        "text": """\
A WMS basemap can render blank on single atlas pages and the export still
reports success; a wrong style looks just as successful. After symbology,
label or layout changes use the screenshot tool, and after exports render
the output and look at it (re-export just the failed page if needed).""",
    },
    {
        "slug": "svg-zero-length-dash",
        "title": "Qt does not draw SVG dots made of zero-length dashes",
        "severity": "silent",
        "keywords": "svg stroke-dasharray dotted ring picture marker",
        "text": """\
`stroke-dasharray: 0 x` with round caps (dotted rings from design tools)
renders as nothing in QGIS. Rewrite such SVGs with real `<circle>` dots.
Picture items in Zoom mode also draw SVGs slightly smaller than the viewBox
suggests — calibrate against a render.""",
    },
    {
        "slug": "3d-expressions-no-hex",
        "title": "Use color_rgb()/color_hsl(), not '#rrggbb', in 3D renderer expressions",
        "severity": "api",
        "keywords": "3d renderer material diffuse expression hex colour xml",
        "text": """\
3D renderers can only be edited via an XML round-trip, and a `#` inside
data-defined material expressions breaks the parser afterwards. Write colours
as `color_rgb(r,g,b)` or `color_hsl(h,s,l)`.""",
    },
    {
        "slug": "pyqgis4-property-names",
        "title": "QGIS 4 names for data-defined symbol and label properties",
        "severity": "api",
        "keywords": "data defined property symbol layer enabled label distance QgsPropertyCollection",
        "text": """\
- Symbol layer on/off by expression:
  `sl.setDataDefinedProperty(QgsSymbolLayer.PropertyLayerEnabled, QgsProperty.fromExpression(...))`
  (`QgsSymbolLayer.Property.Enabled` does not exist).
- Labels have no `setDataDefinedProperty`; edit the collection:
  `dd = pal.dataDefinedProperties(); dd.setProperty(QgsPalLayerSettings.Property.LabelDistance, prop);
  pal.setDataDefinedProperties(dd); layer.setLabeling(QgsVectorLayerSimpleLabeling(pal))`.""",
    },
]


def by_slug(slug):
    for r in RULES:
        if r["slug"] == slug:
            return r
    return None
