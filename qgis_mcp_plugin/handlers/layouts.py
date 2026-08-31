"""
Print layout handlers — create, manage items, atlas, export to PDF/image.
"""

from qgis.core import (
    Qgis,
    QgsDxfExport,
    QgsLayoutAtlas,
    QgsLayoutExporter,
    QgsLayoutItemLabel,
    QgsLayoutItemLegend,
    QgsLayoutItemMap,
    QgsLayoutItemMapOverview,
    QgsLayoutItemPicture,
    QgsLayoutItemScaleBar,
    QgsLayoutItemShape,
    QgsLayoutPoint,
    QgsLayoutSize,
    QgsMapSettings,
    QgsPrintLayout,
    QgsProject,
    QgsProperty,
    QgsUnitTypes,
)
from qgis.PyQt.QtGui import QColor, QFont


def register(server):
    """Register layout handlers."""
    s = server

    def _get_layout_or_raise(name: str):
        manager = QgsProject.instance().layoutManager()
        layout = manager.layoutByName(name)
        if not layout:
            raise RuntimeError(f"Layout not found: {name}")
        return layout

    def list_layouts(**_):
        """List all print layouts with page count and item count."""
        manager = QgsProject.instance().layoutManager()
        layouts = []
        for layout in manager.printLayouts():
            layouts.append({
                "name": layout.name(),
                "page_count": layout.pageCollection().pageCount(),
                "item_count": len(layout.items()),
            })
        return layouts

    def create_layout(name: str, width: float = 297, height: float = 210,
                      add_map: bool = True, orientation: str = "landscape", **_):
        """Create a new print layout. Default A4. orientation: landscape or portrait.

        If orientation is 'portrait', width/height are swapped if needed.
        """
        if orientation == "portrait" and width > height:
            width, height = height, width
        elif orientation == "landscape" and height > width:
            width, height = height, width

        project = QgsProject.instance()
        manager = project.layoutManager()

        # Remove existing layout with same name
        existing = manager.layoutByName(name)
        if existing:
            manager.removeLayout(existing)

        layout = QgsPrintLayout(project)
        layout.initializeDefaults()
        layout.setName(name)

        # Set page size
        unit = QgsUnitTypes.LayoutUnit.LayoutMillimeters
        page = layout.pageCollection().page(0)
        page.setPageSize(QgsLayoutSize(width, height, unit))

        if add_map:
            map_item = QgsLayoutItemMap(layout)
            map_item.setRect(0, 0, width, height)
            map_item.attemptResize(QgsLayoutSize(width - 20, height - 20, unit))
            map_item.attemptMove(QgsLayoutPoint(10, 10, unit))
            map_item.setExtent(s.iface.mapCanvas().extent())
            map_item.setCrs(project.crs())
            map_item.setLayers(list(project.mapLayers().values()))
            layout.addLayoutItem(map_item)

        manager.addLayout(layout)
        return {"name": name, "width": width, "height": height, "has_map": add_map}

    def delete_layout(name: str, **_):
        """Delete a print layout by name."""
        manager = QgsProject.instance().layoutManager()
        layout = manager.layoutByName(name)
        if not layout:
            raise RuntimeError(f"Layout not found: {name}")
        manager.removeLayout(layout)
        return {"deleted": name}

    def add_layout_item(layout_name: str, item_type: str,
                        x: float = 10, y: float = 10,
                        width: float = 50, height: float = 20,
                        text: str = None, font_size: float = 12,
                        image_path: str = None, **_):
        """Add an item to a print layout.

        item_type: map, label, legend, scalebar, picture, shape, north_arrow, attribute_table.
        """
        layout = _get_layout_or_raise(layout_name)
        unit = QgsUnitTypes.LayoutUnit.LayoutMillimeters

        if item_type == "label":
            item = QgsLayoutItemLabel(layout)
            item.setText(text or "")
            font = item.font()
            font.setPointSizeF(font_size)
            item.setFont(font)

        elif item_type == "legend":
            item = QgsLayoutItemLegend(layout)
            # Auto-link to first map
            maps = [i for i in layout.items() if isinstance(i, QgsLayoutItemMap)]
            if maps:
                item.setLinkedMap(maps[0])

        elif item_type == "scalebar":
            item = QgsLayoutItemScaleBar(layout)
            maps = [i for i in layout.items() if isinstance(i, QgsLayoutItemMap)]
            if maps:
                item.setLinkedMap(maps[0])

        elif item_type == "map":
            item = QgsLayoutItemMap(layout)
            item.setExtent(s.iface.mapCanvas().extent())
            item.setCrs(QgsProject.instance().crs())
            item.setLayers(list(QgsProject.instance().mapLayers().values()))

        elif item_type == "picture" or item_type == "north_arrow":
            item = QgsLayoutItemPicture(layout)
            if image_path:
                item.setPicturePath(image_path)

        elif item_type == "shape":
            item = QgsLayoutItemShape(layout)

        elif item_type == "attribute_table":
            from qgis.core import QgsLayoutItemAttributeTable
            item = QgsLayoutItemAttributeTable.create(layout)
            # Link to first vector layer
            project = QgsProject.instance()
            for lyr in project.mapLayers().values():
                from qgis.core import Qgis
                if lyr.type() == Qgis.LayerType.Vector:
                    item.setVectorLayer(lyr)
                    break

        else:
            raise RuntimeError(
                f"Unknown item_type: {item_type}. "
                "Use: map, label, legend, scalebar, picture, shape, north_arrow, attribute_table."
            )

        item.attemptResize(QgsLayoutSize(width, height, unit))
        item.attemptMove(QgsLayoutPoint(x, y, unit))
        layout.addLayoutItem(item)

        return {"layout": layout_name, "item_type": item_type, "id": item.id()}

    def remove_layout_item(layout_name: str, item_id: str, **_):
        """Remove an item from a layout by its ID."""
        layout = _get_layout_or_raise(layout_name)
        item = layout.itemById(item_id)
        if not item:
            raise RuntimeError(f"Item not found: {item_id}")
        layout.removeLayoutItem(item)
        return {"layout": layout_name, "removed_item": item_id}

    def set_layout_item_property(layout_name: str, item_id: str,
                                 x: float = None, y: float = None,
                                 width: float = None, height: float = None,
                                 text: str = None, font_size: float = None,
                                 **_):
        """Set properties on a layout item: position, size, text, font size."""
        layout = _get_layout_or_raise(layout_name)
        item = layout.itemById(item_id)
        if not item:
            raise RuntimeError(f"Item not found: {item_id}")

        unit = QgsUnitTypes.LayoutUnit.LayoutMillimeters

        if x is not None or y is not None:
            pos = item.positionWithUnits()
            new_x = x if x is not None else pos.x()
            new_y = y if y is not None else pos.y()
            item.attemptMove(QgsLayoutPoint(new_x, new_y, unit))

        if width is not None or height is not None:
            sz = item.sizeWithUnits()
            new_w = width if width is not None else sz.width()
            new_h = height if height is not None else sz.height()
            item.attemptResize(QgsLayoutSize(new_w, new_h, unit))

        if text is not None and isinstance(item, QgsLayoutItemLabel):
            item.setText(text)

        if font_size is not None and isinstance(item, QgsLayoutItemLabel):
            font = item.font()
            font.setPointSizeF(font_size)
            item.setFont(font)

        return {"layout": layout_name, "item_id": item_id, "updated": True}

    def set_atlas(layout_name: str, coverage_layer_id: str,
                  filename_expression: str = "'output_'||@atlas_featurenumber",
                  enabled: bool = True, filter_expression: str = None, **_):
        """Configure atlas generation on a layout.

        coverage_layer_id: layer whose features drive the atlas.
        filename_expression: expression for output filenames.
        """
        layout = _get_layout_or_raise(layout_name)
        atlas = layout.atlas()

        layer = s.get_layer_or_raise(coverage_layer_id)
        atlas.setCoverageLayer(layer)
        atlas.setFilenameExpression(filename_expression)
        atlas.setEnabled(enabled)

        if filter_expression:
            atlas.setFilterExpression(filter_expression)
            atlas.setFilterFeatures(True)

        return {
            "layout": layout_name,
            "atlas_enabled": enabled,
            "coverage_layer": layer.name(),
        }

    def export_layout_pdf(layout_name: str, path: str, dpi: int = 300, **_):
        """Export a print layout to PDF."""
        layout = _get_layout_or_raise(layout_name)
        exporter = QgsLayoutExporter(layout)
        settings = QgsLayoutExporter.PdfExportSettings()
        settings.dpi = dpi

        result = exporter.exportToPdf(path, settings)
        if result != QgsLayoutExporter.ExportResult.Success:
            raise RuntimeError(f"PDF export failed: {result}")
        return {"exported": path, "dpi": dpi}

    def export_layout_image(layout_name: str, path: str, dpi: int = 150, **_):
        """Export a print layout to PNG or JPEG image."""
        layout = _get_layout_or_raise(layout_name)
        exporter = QgsLayoutExporter(layout)
        settings = QgsLayoutExporter.ImageExportSettings()
        settings.dpi = dpi

        result = exporter.exportToImage(path, settings)
        if result != QgsLayoutExporter.ExportResult.Success:
            raise RuntimeError(f"Image export failed: {result}")
        return {"exported": path, "dpi": dpi}

    def export_atlas(layout_name: str, output_dir: str, format: str = "pdf",
                     dpi: int = 300, **_):
        """Export atlas pages as individual PDFs or images.

        format: pdf or image (png/jpg based on filename expression).
        """
        layout = _get_layout_or_raise(layout_name)
        atlas = layout.atlas()
        if not atlas.enabled():
            raise RuntimeError("Atlas is not enabled on this layout")

        exporter = QgsLayoutExporter(layout)

        import os
        os.makedirs(output_dir, exist_ok=True)

        if format.lower() == "pdf":
            settings = QgsLayoutExporter.PdfExportSettings()
            settings.dpi = dpi
            result = exporter.exportToPdfs(
                atlas, output_dir, settings,
            )
        else:
            settings = QgsLayoutExporter.ImageExportSettings()
            settings.dpi = dpi
            result = exporter.exportToImage(
                atlas, output_dir, "png", settings,
            )

        return {"output_dir": output_dir, "format": format, "dpi": dpi}

    # ── Layout Data-Defined Overrides ─────────────────────────────

    def set_layout_item_dd_property(layout_name: str, item_id: str,
                                    property_name: str, expression: str, **_):
        """Set a data-defined override on a layout item.

        property_name examples: MapExtent, MapScale, MapRotation, ItemWidth,
            ItemHeight, Text, Opacity, BackgroundColor, FrameColor.
        expression: QGIS expression evaluated per feature (for atlas) or globally.
        """
        layout = _get_layout_or_raise(layout_name)
        item = layout.itemById(item_id)
        if not item:
            raise RuntimeError(f"Item not found: {item_id}")

        # Map string property names to QgsLayoutObject property enums
        from qgis.core import QgsLayoutObject
        prop_map = {
            "Opacity": QgsLayoutObject.DataDefinedProperty.Opacity,
            "BackgroundColor": QgsLayoutObject.DataDefinedProperty.BackgroundColor,
            "FrameColor": QgsLayoutObject.DataDefinedProperty.FrameColor,
            "ItemWidth": QgsLayoutObject.DataDefinedProperty.ItemWidth,
            "ItemHeight": QgsLayoutObject.DataDefinedProperty.ItemHeight,
            "ItemRotation": QgsLayoutObject.DataDefinedProperty.ItemRotation,
            "ExcludeFromExports": QgsLayoutObject.DataDefinedProperty.ExcludeFromExports,
        }

        # Map-specific properties
        if isinstance(item, QgsLayoutItemMap):
            prop_map.update({
                "MapRotation": QgsLayoutObject.DataDefinedProperty.MapRotation,
                "MapScale": QgsLayoutObject.DataDefinedProperty.MapScale,
                "MapXMin": QgsLayoutObject.DataDefinedProperty.MapXMin,
                "MapXMax": QgsLayoutObject.DataDefinedProperty.MapXMax,
                "MapYMin": QgsLayoutObject.DataDefinedProperty.MapYMin,
                "MapYMax": QgsLayoutObject.DataDefinedProperty.MapYMax,
            })

        # Label-specific properties
        if isinstance(item, QgsLayoutItemLabel):
            prop_map.update({
                "Text": QgsLayoutObject.DataDefinedProperty.LabelText,
            })

        prop_enum = prop_map.get(property_name)
        if prop_enum is None:
            available = ", ".join(sorted(prop_map.keys()))
            raise RuntimeError(
                f"Unknown property: {property_name}. Available: {available}"
            )

        dd = item.dataDefinedProperties()
        dd.setProperty(prop_enum, QgsProperty.fromExpression(expression))
        item.setDataDefinedProperties(dd)
        item.refresh()

        return {
            "layout": layout_name,
            "item_id": item_id,
            "property": property_name,
            "expression": expression,
        }

    def add_layout_page(layout_name: str, width: float = None, height: float = None, **_):
        """Add a page to a layout (for multi-page layouts).

        If width/height not specified, matches the first page dimensions.
        """
        layout = _get_layout_or_raise(layout_name)
        unit = QgsUnitTypes.LayoutUnit.LayoutMillimeters
        page_collection = layout.pageCollection()

        # Default to first page size
        if width is None or height is None:
            first_page = page_collection.page(0)
            if first_page:
                size = first_page.pageSize()
                width = width or size.width()
                height = height or size.height()
            else:
                width = width or 297
                height = height or 210

        from qgis.core import QgsLayoutItemPage
        new_page = QgsLayoutItemPage(layout)
        new_page.setPageSize(QgsLayoutSize(width, height, unit))
        page_collection.addPage(new_page)

        return {
            "layout": layout_name,
            "page_count": page_collection.pageCount(),
            "width": width,
            "height": height,
        }

    # ── Layout Enhancements ────────────────────────────────────────

    def set_map_overview(layout_name: str, map_item_id: str,
                         overview_map_item_id: str,
                         frame_color: str = "#ff0000", **_):
        """Add or configure an overview frame on a map item.

        map_item_id: the map item that will show the overview rectangle.
        overview_map_item_id: the map item whose extent is shown as an overview.
        frame_color: color of the overview rectangle (hex).
        """
        layout = _get_layout_or_raise(layout_name)
        map_item = layout.itemById(map_item_id)
        if not map_item or not isinstance(map_item, QgsLayoutItemMap):
            raise RuntimeError(f"Map item not found: {map_item_id}")

        overview_map = layout.itemById(overview_map_item_id)
        if not overview_map or not isinstance(overview_map, QgsLayoutItemMap):
            raise RuntimeError(f"Overview map item not found: {overview_map_item_id}")

        # Get or create the overview
        overviews = map_item.overviews()
        if overviews.size() == 0:
            overviews.addOverview(QgsLayoutItemMapOverview("Overview", map_item))
        overview = overviews.overview(0)
        overview.setLinkedMap(overview_map)
        overview.setEnabled(True)

        # Set frame style
        from qgis.core import QgsSimpleFillSymbolLayer, QgsFillSymbol
        symbol = QgsFillSymbol.createSimple({
            "color": "0,0,0,0",
            "outline_color": frame_color,
            "outline_width": "0.5",
        })
        overview.setFrameSymbol(symbol)

        map_item.invalidateCache()
        return {
            "layout": layout_name,
            "map_item_id": map_item_id,
            "overview_map_item_id": overview_map_item_id,
        }

    def set_map_theme_for_item(layout_name: str, item_id: str, theme_name: str, **_):
        """Set which map theme a layout map item uses for rendering."""
        layout = _get_layout_or_raise(layout_name)
        item = layout.itemById(item_id)
        if not item or not isinstance(item, QgsLayoutItemMap):
            raise RuntimeError(f"Map item not found: {item_id}")

        collection = QgsProject.instance().mapThemeCollection()
        if theme_name not in collection.mapThemes():
            raise RuntimeError(f"Map theme not found: {theme_name}")

        item.setFollowVisibilityPreset(True)
        item.setFollowVisibilityPresetName(theme_name)
        item.invalidateCache()

        return {
            "layout": layout_name,
            "item_id": item_id,
            "theme_name": theme_name,
        }

    def export_layout_svg(layout_name: str, path: str, dpi: int = 300, **_):
        """Export a print layout to SVG."""
        layout = _get_layout_or_raise(layout_name)
        exporter = QgsLayoutExporter(layout)
        settings = QgsLayoutExporter.SvgExportSettings()
        settings.dpi = dpi

        result = exporter.exportToSvg(path, settings)
        if result != QgsLayoutExporter.ExportResult.Success:
            raise RuntimeError(f"SVG export failed: {result}")
        return {"exported": path, "dpi": dpi}

    def export_dxf(path: str, layer_ids: list = None, crs: str = None, **_):
        """Export project layers to a DXF file.

        layer_ids: optional list of layer IDs (all visible vector layers if empty).
        crs: optional CRS for the export (project CRS if not specified).
        """
        from qgis.core import QgsCoordinateReferenceSystem
        project = QgsProject.instance()

        dxf_export = QgsDxfExport()

        # Set CRS
        if crs:
            crs_obj = QgsCoordinateReferenceSystem(crs)
            if not crs_obj.isValid():
                raise RuntimeError(f"Invalid CRS: {crs}")
            dxf_export.setDestinationCrs(crs_obj)
        else:
            dxf_export.setDestinationCrs(project.crs())

        # Gather layers
        dxf_layers = []
        if layer_ids:
            for lid in layer_ids:
                layer = project.mapLayer(lid)
                if layer and layer.type() == Qgis.LayerType.Vector:
                    dxf_layers.append(QgsDxfExport.DxfLayer(layer))
        else:
            for layer in project.mapLayers().values():
                if layer.type() == Qgis.LayerType.Vector:
                    tree = project.layerTreeRoot().findLayer(layer.id())
                    if tree and tree.isVisible():
                        dxf_layers.append(QgsDxfExport.DxfLayer(layer))

        if not dxf_layers:
            raise RuntimeError("No vector layers found for DXF export")

        dxf_export.addLayers(dxf_layers)

        import os
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

        from qgis.PyQt.QtCore import QFile, QIODevice
        f = QFile(path)
        if not f.open(QIODevice.OpenModeFlag.WriteOnly):
            raise RuntimeError(f"Could not open file for writing: {path}")

        result = dxf_export.writeToFile(f, "")
        f.close()

        if result != QgsDxfExport.ExportResult.Success:
            raise RuntimeError(f"DXF export failed: {result}")

        return {
            "exported": path,
            "layer_count": len(dxf_layers),
        }

    s._HANDLERS.update({
        "list_layouts": list_layouts,
        "create_layout": create_layout,
        "delete_layout": delete_layout,
        "add_layout_item": add_layout_item,
        "remove_layout_item": remove_layout_item,
        "set_layout_item_property": set_layout_item_property,
        "set_atlas": set_atlas,
        "export_layout_pdf": export_layout_pdf,
        "export_layout_image": export_layout_image,
        "export_atlas": export_atlas,
        "set_layout_item_dd_property": set_layout_item_dd_property,
        "add_layout_page": add_layout_page,
        "set_map_overview": set_map_overview,
        "set_map_theme_for_item": set_map_theme_for_item,
        "export_layout_svg": export_layout_svg,
        "export_dxf": export_dxf,
    })

    # ── IDML Import ───────────────────────────────────────────────

    def import_idml(path: str, layout_name: str = None, add_map: bool = True,
                    unit: str = "points", **_):
        """Parse an InDesign IDML file and recreate it as a QGIS print layout.
        Extracts page size, text frames, rectangles, and image placeholders.
        IDML internally stores all coordinates in points (1pt = 1/72 inch).
        unit: 'points' (default, zero-loss) or 'mm' (converted, standard QGIS).
        Returns a summary of created items with IDs for data-defined overrides.
        """
        import zipfile
        import xml.etree.ElementTree as ET
        import os

        if not os.path.isfile(path):
            raise RuntimeError(f"IDML file not found: {path}")
        if not path.lower().endswith(".idml"):
            raise RuntimeError(f"Not an IDML file: {path}")

        project = QgsProject.instance()
        manager = project.layoutManager()

        # Derive layout name from filename if not provided
        if not layout_name:
            layout_name = os.path.splitext(os.path.basename(path))[0]

        # Remove existing layout with same name
        existing = manager.layoutByName(layout_name)
        if existing:
            manager.removeLayout(existing)

        # IDML always stores coordinates in points (1pt = 1/72 inch = 0.3528mm)
        # By default we keep points in QGIS (zero conversion loss).
        # If user wants mm, we convert.
        if unit == "mm":
            SCALE = 0.3527777778
            layout_unit = QgsUnitTypes.LayoutUnit.LayoutMillimeters
            unit_label = "mm"
        else:
            SCALE = 1.0
            layout_unit = QgsUnitTypes.LayoutUnit.LayoutPoints
            unit_label = "pt"

        items_created = []

        with zipfile.ZipFile(path, "r") as zf:
            # ── Parse designmap.xml for story references ──
            stories = {}
            story_files = [f for f in zf.namelist() if f.startswith("Stories/")]
            for sf in story_files:
                try:
                    tree = ET.parse(zf.open(sf))
                    root = tree.getroot()
                    ns = {"idPkg": "http://ns.adobe.com/AdobeInDesign/idml/1.0/packaging"}
                    story_el = root.find(".//Story") or root.find(".//{http://ns.adobe.com/AdobeInDesign/idml/1.0/packaging}Story")
                    if story_el is None:
                        # Try without namespace
                        for el in root.iter():
                            if el.tag.endswith("Story") or el.tag == "Story":
                                story_el = el
                                break
                    if story_el is not None:
                        story_id = story_el.get("Self", "")
                        # Extract all text content from the story
                        text_parts = []
                        for content in story_el.iter():
                            if content.tag == "Content" or content.tag.endswith("}Content"):
                                if content.text:
                                    text_parts.append(content.text)
                        if text_parts and story_id:
                            stories[story_id] = "\n".join(text_parts)
                except Exception:
                    pass

            # ── Parse Spreads for page size and frames ──
            spread_files = sorted([f for f in zf.namelist() if f.startswith("Spreads/")])
            page_width_mm = 297.0  # A4 landscape default
            page_height_mm = 210.0
            frames = []

            for sf in spread_files:
                try:
                    tree = ET.parse(zf.open(sf))
                    root = tree.getroot()
                except Exception:
                    continue

                # Find Page elements for page size
                for page in root.iter():
                    if page.tag == "Page" or page.tag.endswith("}Page"):
                        bounds = page.get("GeometricBounds", "")
                        if bounds:
                            parts = [float(x) for x in bounds.split()]
                            if len(parts) == 4:
                                top, left, bottom, right = parts
                                page_width_mm = (right - left) * SCALE
                                page_height_mm = (bottom - top) * SCALE

                # Find all frames (TextFrame, Rectangle, Polygon, Oval, Group, etc.)
                for elem in root.iter():
                    tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag

                    if tag not in ("TextFrame", "Rectangle", "Polygon", "Oval",
                                   "GraphicLine", "Group"):
                        continue

                    # Parse ItemTransform: "a b c d tx ty"
                    transform = elem.get("ItemTransform", "1 0 0 1 0 0")
                    try:
                        t = [float(x) for x in transform.split()]
                        tx, ty = t[4], t[5]
                    except (ValueError, IndexError):
                        tx, ty = 0, 0

                    # Parse PathPointArray for frame dimensions
                    x_coords = []
                    y_coords = []
                    for pp in elem.iter():
                        pp_tag = pp.tag.split("}")[-1] if "}" in pp.tag else pp.tag
                        if pp_tag == "PathPointType":
                            anchor = pp.get("Anchor", "")
                            if anchor:
                                try:
                                    ax, ay = [float(v) for v in anchor.split()]
                                    x_coords.append(ax)
                                    y_coords.append(ay)
                                except ValueError:
                                    pass

                    if not x_coords or not y_coords:
                        continue

                    # Frame bounds in local coords
                    local_left = min(x_coords)
                    local_top = min(y_coords)
                    local_right = max(x_coords)
                    local_bottom = max(y_coords)

                    # Convert to absolute page position in mm
                    frame_x = (tx + local_left) * SCALE
                    frame_y = (ty + local_top) * SCALE
                    frame_w = (local_right - local_left) * SCALE
                    frame_h = (local_bottom - local_top) * SCALE

                    # Skip tiny frames (likely hidden/empty)
                    if frame_w < 1 or frame_h < 1:
                        continue

                    frame_info = {
                        "tag": tag,
                        "x": round(frame_x, 2),
                        "y": round(frame_y, 2),
                        "w": round(frame_w, 2),
                        "h": round(frame_h, 2),
                    }

                    # Get fill color if available
                    fill_color = elem.get("FillColor", "")
                    if fill_color and "Swatch/None" not in fill_color:
                        frame_info["fill"] = fill_color

                    # For TextFrames, find the linked story
                    if tag == "TextFrame":
                        parent_story = elem.get("ParentStory", "")
                        if parent_story and parent_story in stories:
                            frame_info["text"] = stories[parent_story]

                    # Check for placed images
                    for child in elem.iter():
                        child_tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                        if child_tag in ("Image", "EPS", "PDF", "ImportedPage"):
                            link = child.find("Link") or child.find(".//{http://ns.adobe.com/AdobeInDesign/idml/1.0/packaging}Link")
                            if link is None:
                                for l in child.iter():
                                    l_tag = l.tag.split("}")[-1] if "}" in l.tag else l.tag
                                    if l_tag == "Link":
                                        link = l
                                        break
                            if link is not None:
                                frame_info["image"] = link.get("LinkResourceURI", "")
                            frame_info["tag"] = "Image"

                    frames.append(frame_info)

        # ── Create QGIS Layout ──

        layout = QgsPrintLayout(project)
        layout.initializeDefaults()
        layout.setName(layout_name)

        # Set page size (in chosen unit — points for zero-loss, mm if preferred)
        page = layout.pageCollection().page(0)
        page.setPageSize(QgsLayoutSize(
            page_width_mm, page_height_mm,
            layout_unit
        ))

        lu = layout_unit  # shorthand for all item placements below

        # Add a map item covering the full page if requested
        if add_map:
            map_item = QgsLayoutItemMap(layout)
            map_item.attemptResize(QgsLayoutSize(
                page_width_mm - 20, page_height_mm - 20, lu
            ))
            map_item.attemptMove(QgsLayoutPoint(10, 10, lu))
            map_item.setExtent(s.iface.mapCanvas().extent())
            map_item.setCrs(project.crs())
            map_item.setLayers(list(project.mapLayers().values()))
            map_item.setFrameEnabled(False)
            layout.addLayoutItem(map_item)
            items_created.append({
                "type": "map", "x": 10, "y": 10,
                "w": round(page_width_mm - 20, 1),
                "h": round(page_height_mm - 20, 1),
            })

        # Create layout items from parsed frames
        for frame in frames:
            x, y, w, h = frame["x"], frame["y"], frame["w"], frame["h"]

            if frame["tag"] == "TextFrame":
                item = QgsLayoutItemLabel(layout)
                text = frame.get("text", "")
                item.setText(text)
                item.setFrameEnabled(True)
                item.attemptResize(QgsLayoutSize(w, h, lu))
                item.attemptMove(QgsLayoutPoint(x, y, lu))
                layout.addLayoutItem(item)
                items_created.append({
                    "type": "label", "x": x, "y": y, "w": w, "h": h,
                    "text": text[:50] + "..." if len(text) > 50 else text,
                    "id": item.id(),
                })

            elif frame["tag"] == "Rectangle" or frame["tag"] == "Polygon":
                item = QgsLayoutItemShape(layout)
                item.setShapeType(QgsLayoutItemShape.Shape.Rectangle)
                item.attemptResize(QgsLayoutSize(w, h, lu))
                item.attemptMove(QgsLayoutPoint(x, y, lu))
                item.setFrameEnabled(True)
                layout.addLayoutItem(item)
                items_created.append({
                    "type": "shape", "x": x, "y": y, "w": w, "h": h,
                    "id": item.id(),
                })

            elif frame["tag"] == "Image":
                item = QgsLayoutItemPicture(layout)
                item.attemptResize(QgsLayoutSize(w, h, lu))
                item.attemptMove(QgsLayoutPoint(x, y, lu))
                image_path = frame.get("image", "")
                if image_path:
                    # Try to resolve relative paths
                    item.setPicturePath(image_path)
                item.setFrameEnabled(True)
                layout.addLayoutItem(item)
                items_created.append({
                    "type": "picture", "x": x, "y": y, "w": w, "h": h,
                    "image": image_path,
                    "id": item.id(),
                })

            elif frame["tag"] == "Oval":
                item = QgsLayoutItemShape(layout)
                item.setShapeType(QgsLayoutItemShape.Shape.Ellipse)
                item.attemptResize(QgsLayoutSize(w, h, lu))
                item.attemptMove(QgsLayoutPoint(x, y, lu))
                item.setFrameEnabled(True)
                layout.addLayoutItem(item)
                items_created.append({
                    "type": "ellipse", "x": x, "y": y, "w": w, "h": h,
                    "id": item.id(),
                })

        manager.addLayout(layout)

        return {
            "layout_name": layout_name,
            "page_width": round(page_width_mm, 2),
            "page_height": round(page_height_mm, 2),
            "unit": unit_label,
            "frames_parsed": len(frames),
            "items_created": items_created,
            "stories_found": len(stories),
        }

    s._HANDLERS["import_idml"] = import_idml
