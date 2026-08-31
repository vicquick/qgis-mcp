"""
Layer CRUD + info handlers — add, remove, rename, duplicate, reorder, group, features, etc.
"""

import os

from qgis.core import (
    Qgis,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeatureRequest,
    QgsLayerTreeGroup,
    QgsProject,
    QgsRasterLayer,
    QgsVectorLayer,
)

from ..server import GEOMETRY_TYPE_NAMES


def register(server):
    """Register layer handlers."""
    s = server

    def get_layers(**_):
        """List all layers with type, visibility, feature count, CRS, and extent."""
        project = QgsProject.instance()
        result = []
        for lid, layer in project.mapLayers().items():
            tree_node = project.layerTreeRoot().findLayer(lid)
            info = {
                "id": lid,
                "name": layer.name(),
                "type": s.layer_type_str(layer),
                "visible": tree_node.isVisible() if tree_node else False,
                "crs": layer.crs().authid(),
                "extent": s.extent_to_dict(layer.extent()),
            }
            if layer.type() == Qgis.LayerType.Vector:
                info["feature_count"] = layer.featureCount()
                info["geometry_type"] = GEOMETRY_TYPE_NAMES.get(
                    layer.geometryType(), str(int(layer.geometryType()))
                )
            elif layer.type() == Qgis.LayerType.Raster:
                info["width"] = layer.width()
                info["height"] = layer.height()
            result.append(info)
        return result

    def add_vector_layer(path: str, provider: str = "ogr", name: str = None, **_):
        """Add a vector layer from a file path or URI.

        Supported providers: ogr, postgres, memory, delimitedtext, wfs, spatialite, gpkg, etc.
        """
        display_name = name or os.path.basename(path)
        layer = QgsVectorLayer(path, display_name, provider)
        if not layer.isValid():
            raise RuntimeError(f"Invalid vector layer: {path} (provider={provider})")
        QgsProject.instance().addMapLayer(layer)
        return {
            "id": layer.id(),
            "name": layer.name(),
            "type": s.layer_type_str(layer),
            "feature_count": layer.featureCount(),
            "crs": layer.crs().authid(),
        }

    def add_raster_layer(path: str, provider: str = "gdal", name: str = None, **_):
        """Add a raster layer from a file or URI.

        Supported providers: gdal, wms, wcs, xyz, etc.
        """
        display_name = name or os.path.basename(path)
        layer = QgsRasterLayer(path, display_name, provider)
        if not layer.isValid():
            raise RuntimeError(f"Invalid raster layer: {path} (provider={provider})")
        QgsProject.instance().addMapLayer(layer)
        return {
            "id": layer.id(),
            "name": layer.name(),
            "type": "raster",
            "width": layer.width(),
            "height": layer.height(),
            "crs": layer.crs().authid(),
        }

    def add_wms_layer(url: str, layers: str = "", name: str = None,
                      format: str = "image/png", crs: str = "EPSG:3857",
                      style: str = "", **_):
        """Add a WMS, WMTS, or XYZ tile layer by URL.

        For XYZ tiles, pass the tile URL template directly and set provider logic accordingly.
        For WMS, provide the base URL and layer names.
        """
        display_name = name or "WMS Layer"

        # Detect XYZ tile URLs
        if "{x}" in url.lower() or "{z}" in url.lower():
            # XYZ tiles
            uri = f"type=xyz&url={url}&zmin=0&zmax=19"
            layer = QgsRasterLayer(uri, display_name, "wms")
        else:
            # Standard WMS
            uri = (
                f"crs={crs}&dpiMode=7&format={format}"
                f"&layers={layers}&styles={style}&url={url}"
            )
            layer = QgsRasterLayer(uri, display_name, "wms")

        if not layer.isValid():
            raise RuntimeError(f"Invalid WMS/XYZ layer: {url}")
        QgsProject.instance().addMapLayer(layer)
        return {
            "id": layer.id(),
            "name": layer.name(),
            "type": "raster",
        }

    def remove_layer(layer_id: str, **_):
        """Remove a layer from the project by its ID."""
        project = QgsProject.instance()
        if layer_id not in project.mapLayers():
            raise RuntimeError(f"Layer not found: {layer_id}")
        project.removeMapLayer(layer_id)
        return {"removed": layer_id}

    def duplicate_layer(layer_id: str, name: str = None, **_):
        """Duplicate a layer in the project."""
        layer = s.get_layer_or_raise(layer_id)
        clone = layer.clone()
        if name:
            clone.setName(name)
        else:
            clone.setName(f"{layer.name()} (copy)")
        QgsProject.instance().addMapLayer(clone)
        return {
            "id": clone.id(),
            "name": clone.name(),
            "type": s.layer_type_str(clone),
        }

    def rename_layer(layer_id: str, name: str, **_):
        """Rename a layer."""
        layer = s.get_layer_or_raise(layer_id)
        layer.setName(name)
        return {"layer_id": layer_id, "name": name}

    def get_layer_info(layer_id: str, **_):
        """Return detailed info for one layer: CRS, extent, provider, source, fields, renderer type."""
        layer = s.get_layer_or_raise(layer_id)
        info = {
            "id": layer.id(),
            "name": layer.name(),
            "type": s.layer_type_str(layer),
            "crs": layer.crs().authid(),
            "extent": s.extent_to_dict(layer.extent()),
            "provider": layer.providerType(),
            "source": layer.source(),
        }
        if layer.type() == Qgis.LayerType.Vector:
            info["feature_count"] = layer.featureCount()
            info["geometry_type"] = GEOMETRY_TYPE_NAMES.get(
                layer.geometryType(), str(int(layer.geometryType()))
            )
            info["fields"] = [
                {
                    "name": f.name(),
                    "type": f.typeName(),
                    "length": f.length(),
                    "precision": f.precision(),
                    "comment": f.comment(),
                }
                for f in layer.fields()
            ]
            renderer = layer.renderer()
            info["renderer_type"] = type(renderer).__name__ if renderer else None
        elif layer.type() == Qgis.LayerType.Raster:
            info["width"] = layer.width()
            info["height"] = layer.height()
            info["band_count"] = layer.bandCount()
        return info

    def get_layer_fields(layer_id: str, **_):
        """Return field definitions for a vector layer (name, type, typeName, length, precision, comment)."""
        layer = s.get_layer_or_raise(layer_id)
        if layer.type() != Qgis.LayerType.Vector:
            raise RuntimeError(f"Not a vector layer: {layer_id}")
        fields = []
        for field in layer.fields():
            fields.append({
                "name": field.name(),
                "type": field.typeName(),
                "length": field.length(),
                "precision": field.precision(),
                "comment": field.comment(),
            })
        return {"layer_id": layer_id, "fields": fields}

    def get_layer_extent(layer_id: str, **_):
        """Return the spatial extent (bounding box) and CRS of a layer."""
        layer = s.get_layer_or_raise(layer_id)
        return {
            "layer_id": layer_id,
            "extent": s.extent_to_dict(layer.extent()),
            "crs": layer.crs().authid(),
        }

    def get_layer_features(layer_id: str, limit: int = 10, expression: str = None, **_):
        """Return features with attributes and WKT geometry. Supports limit and optional expression filter."""
        layer = s.get_layer_or_raise(layer_id)
        if layer.type() != Qgis.LayerType.Vector:
            raise RuntimeError(f"Not a vector layer: {layer_id}")

        request = QgsFeatureRequest()
        request.setLimit(limit)
        if expression:
            from qgis.core import QgsExpression
            expr = QgsExpression(expression)
            if expr.hasParserError():
                raise RuntimeError(f"Expression error: {expr.parserErrorString()}")
            request.setFilterExpression(expression)

        features = []
        for feat in layer.getFeatures(request):
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
            "feature_count": layer.featureCount(),
            "returned": len(features),
            "fields": [f.name() for f in layer.fields()],
            "features": features,
        }

    def set_layer_visibility(layer_id: str, visible: bool, **_):
        """Toggle layer visibility in the layer tree."""
        layer = s.get_layer_or_raise(layer_id)
        tree_node = QgsProject.instance().layerTreeRoot().findLayer(layer.id())
        if not tree_node:
            raise RuntimeError(f"Layer not in layer tree: {layer_id}")
        tree_node.setItemVisibilityChecked(visible)
        s.iface.mapCanvas().refresh()
        return {"layer_id": layer_id, "visible": visible}

    def set_layer_opacity(layer_id: str, opacity: float, **_):
        """Set layer opacity (0.0 = transparent, 1.0 = opaque)."""
        layer = s.get_layer_or_raise(layer_id)
        opacity = max(0.0, min(1.0, opacity))
        layer.setOpacity(opacity)
        layer.triggerRepaint()
        return {"layer_id": layer_id, "opacity": opacity}

    def reorder_layers(layer_ids: list, **_):
        """Reorder layers in the layer tree. Pass a list of layer IDs in desired top-to-bottom order."""
        project = QgsProject.instance()
        root = project.layerTreeRoot()

        # Validate all IDs first
        for lid in layer_ids:
            if lid not in project.mapLayers():
                raise RuntimeError(f"Layer not found: {lid}")

        # Clone and reinsert in order
        for i, lid in enumerate(layer_ids):
            node = root.findLayer(lid)
            if node:
                clone = node.clone()
                parent = node.parent() or root
                parent.removeChildNode(node)
                root.insertChildNode(i, clone)

        s.iface.mapCanvas().refresh()
        return {"reordered": layer_ids}

    def group_layers(group_name: str, layer_ids: list = None, **_):
        """Create a layer group. Optionally move existing layers into it."""
        root = QgsProject.instance().layerTreeRoot()
        group = root.insertGroup(0, group_name)

        if layer_ids:
            for lid in layer_ids:
                node = root.findLayer(lid)
                if node:
                    clone = node.clone()
                    node.parent().removeChildNode(node)
                    group.addChildNode(clone)

        return {"group": group_name, "layers": layer_ids or []}

    def zoom_to_layer(layer_id: str, **_):
        """Zoom the canvas to fit a layer's extent."""
        layer = s.get_layer_or_raise(layer_id)
        s.iface.setActiveLayer(layer)
        s.iface.zoomToActiveLayer()
        return {"zoomed_to": layer_id}

    # ── Temporal ─────────────────────────────────────────────────

    def set_layer_temporal(layer_id: str, enabled: bool = True,
                           field: str = None, mode: str = "SingleField",
                           start_field: str = None, end_field: str = None, **_):
        """Enable or configure temporal filtering on a vector layer.

        mode: FixedRange, SingleField, DualField.
        field: temporal field name (for SingleField mode).
        start_field / end_field: for DualField mode.
        """
        layer = s.get_layer_or_raise(layer_id)
        if layer.type() != Qgis.LayerType.Vector:
            raise RuntimeError(f"Not a vector layer: {layer_id}")

        from qgis.core import QgsVectorLayerTemporalProperties
        tp = layer.temporalProperties()

        mode_map = {
            "FixedRange": QgsVectorLayerTemporalProperties.TemporalMode.ModeFixedTemporalRange,
            "SingleField": QgsVectorLayerTemporalProperties.TemporalMode.ModeFeatureDateTimeInstantFromField,
            "DualField": QgsVectorLayerTemporalProperties.TemporalMode.ModeFeatureDateTimeStartAndEndFromFields,
        }
        tp_mode = mode_map.get(mode)
        if tp_mode is None:
            raise RuntimeError(f"Unknown temporal mode: {mode}. Use: {', '.join(mode_map.keys())}")

        tp.setMode(tp_mode)

        if mode == "SingleField" and field:
            tp.setStartField(field)
        elif mode == "DualField":
            if start_field:
                tp.setStartField(start_field)
            if end_field:
                tp.setEndField(end_field)

        tp.setIsActive(enabled)
        layer.triggerRepaint()

        return {
            "layer_id": layer_id,
            "temporal_enabled": enabled,
            "mode": mode,
        }

    def set_temporal_range(start: str, end: str, **_):
        """Set the project temporal range.

        start: ISO datetime string (e.g. '2024-01-01T00:00:00').
        end: ISO datetime string (e.g. '2024-12-31T23:59:59').
        """
        from qgis.core import QgsDateTimeRange
        from qgis.PyQt.QtCore import QDateTime

        start_dt = QDateTime.fromString(start, "yyyy-MM-ddTHH:mm:ss")
        end_dt = QDateTime.fromString(end, "yyyy-MM-ddTHH:mm:ss")

        if not start_dt.isValid():
            raise RuntimeError(f"Invalid start datetime: {start}")
        if not end_dt.isValid():
            raise RuntimeError(f"Invalid end datetime: {end}")

        temporal_range = QgsDateTimeRange(start_dt, end_dt)

        # Set the temporal controller range
        canvas = s.iface.mapCanvas()
        controller = canvas.temporalController()
        controller.setTemporalExtents(temporal_range)

        return {
            "start": start,
            "end": end,
        }

    # ── Map Tips ───────────────────────────────────────────────

    def set_map_tip(layer_id: str, html_template: str, **_):
        """Set HTML map tip template for a layer.

        html_template: HTML with QGIS expressions, e.g.
            '<b>[% "name" %]</b><br>Population: [% "pop" %]'
        """
        layer = s.get_layer_or_raise(layer_id)
        layer.setMapTipTemplate(html_template)
        return {"layer_id": layer_id, "map_tip_set": True}

    def get_map_tip(layer_id: str, **_):
        """Get the current map tip HTML template for a layer."""
        layer = s.get_layer_or_raise(layer_id)
        return {
            "layer_id": layer_id,
            "html_template": layer.mapTipTemplate(),
        }

    # ── Layer Actions ──────────────────────────────────────────

    def add_layer_action(layer_id: str, name: str, action_text: str,
                         action_type: str = "Generic", **_):
        """Add an action to a vector layer.

        action_type: Generic, Python, OpenURL.
        action_text: the action code/URL (for Python: python code, for OpenURL: URL template).
        """
        layer = s.get_layer_or_raise(layer_id)
        if layer.type() != Qgis.LayerType.Vector:
            raise RuntimeError(f"Not a vector layer: {layer_id}")

        from qgis.core import QgsAction
        type_map = {
            "Generic": Qgis.AttributeActionType.Generic,
            "Python": Qgis.AttributeActionType.GenericPython,
            "OpenURL": Qgis.AttributeActionType.OpenUrl,
        }
        at = type_map.get(action_type)
        if at is None:
            raise RuntimeError(
                f"Unknown action type: {action_type}. Use: {', '.join(type_map.keys())}"
            )

        action = QgsAction(at, name, action_text, "", False)
        layer.actions().addAction(action)

        return {
            "layer_id": layer_id,
            "action_name": name,
            "action_type": action_type,
            "action_count": layer.actions().size(),
        }

    def list_layer_actions(layer_id: str, **_):
        """List all actions configured on a vector layer."""
        layer = s.get_layer_or_raise(layer_id)
        if layer.type() != Qgis.LayerType.Vector:
            raise RuntimeError(f"Not a vector layer: {layer_id}")

        actions = []
        for i in range(layer.actions().size()):
            action = layer.actions().at(i)
            actions.append({
                "index": i,
                "name": action.name(),
                "type": str(action.type()),
                "command": action.command(),
            })
        return {"layer_id": layer_id, "actions": actions}

    def remove_layer_action(layer_id: str, index: int, **_):
        """Remove an action from a vector layer by index.

        Use list_layer_actions to get the index.
        """
        layer = s.get_layer_or_raise(layer_id)
        if layer.type() != Qgis.LayerType.Vector:
            raise RuntimeError(f"Not a vector layer: {layer_id}")

        if index < 0 or index >= layer.actions().size():
            raise RuntimeError(
                f"Action index out of range: {index} (layer has {layer.actions().size()} actions)"
            )

        action_id = layer.actions().at(index).id()
        layer.actions().removeAction(action_id)
        return {"layer_id": layer_id, "removed_index": index}

    # ── Layer Notes ────────────────────────────────────────────

    def set_layer_note(layer_id: str, note_html: str, **_):
        """Set a layer note (shown in the layer properties dialog).

        note_html: HTML formatted note text.
        """
        layer = s.get_layer_or_raise(layer_id)
        from qgis.core import QgsLayerNotesUtils
        QgsLayerNotesUtils.setLayerNotes(layer, note_html)
        return {"layer_id": layer_id, "note_set": True}

    def get_layer_note(layer_id: str, **_):
        """Get the layer note HTML."""
        layer = s.get_layer_or_raise(layer_id)
        from qgis.core import QgsLayerNotesUtils
        note = QgsLayerNotesUtils.layerNotes(layer)
        return {"layer_id": layer_id, "note_html": note}

    # ── Mesh & Point Cloud Info ────────────────────────────────

    def get_mesh_info(layer_id: str, **_):
        """Get mesh layer info: dataset groups, timesteps, extent."""
        layer = s.get_layer_or_raise(layer_id)
        if layer.type() != Qgis.LayerType.Mesh:
            raise RuntimeError(f"Not a mesh layer: {layer_id}")

        dp = layer.dataProvider()
        groups = []
        for i in range(dp.datasetGroupCount()):
            meta = dp.datasetGroupMetadata(i)
            groups.append({
                "index": i,
                "name": meta.name(),
                "is_scalar": meta.isScalar(),
                "is_vector": meta.isVector(),
                "dataset_count": dp.datasetCount(i),
            })

        return {
            "layer_id": layer_id,
            "name": layer.name(),
            "crs": layer.crs().authid(),
            "extent": s.extent_to_dict(layer.extent()),
            "dataset_group_count": dp.datasetGroupCount(),
            "groups": groups,
        }

    def get_point_cloud_info(layer_id: str, **_):
        """Get point cloud layer info: point count, attributes, CRS, extent."""
        layer = s.get_layer_or_raise(layer_id)
        if layer.type() != Qgis.LayerType.PointCloud:
            raise RuntimeError(f"Not a point cloud layer: {layer_id}")

        dp = layer.dataProvider()
        attributes = []
        for attr in dp.attributes().attributes():
            attributes.append({
                "name": attr.name(),
                "type": str(attr.type()),
                "size": attr.size(),
            })

        return {
            "layer_id": layer_id,
            "name": layer.name(),
            "crs": layer.crs().authid(),
            "extent": s.extent_to_dict(layer.extent()),
            "point_count": dp.pointCount(),
            "attributes": attributes,
        }

    # ── Layer Search ─────────────────────────────────────────────

    def find_layer(pattern: str, **_):
        """Search for layers by name using wildcard pattern matching.

        pattern: fnmatch-style pattern (e.g. '*roads*', 'building_*', '*.shp').
        Returns matching layers with their IDs and types.
        """
        import fnmatch
        project = QgsProject.instance()
        matches = []
        for lid, layer in project.mapLayers().items():
            if fnmatch.fnmatch(layer.name().lower(), pattern.lower()):
                matches.append({
                    "id": lid,
                    "name": layer.name(),
                    "type": s.layer_type_str(layer),
                    "crs": layer.crs().authid(),
                })
        return {"pattern": pattern, "matches": matches, "count": len(matches)}

    # ── Memory Layer ──────────────────────────────────────────────

    def create_memory_layer(name: str, geometry_type: str = "Point",
                            crs: str = "EPSG:4326", fields: list = None, **_):
        """Create an in-memory (scratch) vector layer for intermediate results.

        geometry_type: Point, LineString, Polygon, MultiPoint, MultiLineString, MultiPolygon, None.
        crs: CRS authid string.
        fields: list of dicts [{name, type}] where type is String, Integer, Double, Date, etc.

        Example fields: [{"name": "id", "type": "Integer"}, {"name": "label", "type": "String"}]
        """
        # Build URI
        field_defs = ""
        if fields:
            parts = []
            for f in fields:
                ftype = f.get("type", "String").lower()
                type_map = {
                    "string": "string", "integer": "integer", "int": "integer",
                    "double": "double", "float": "double", "date": "date",
                    "datetime": "datetime", "boolean": "integer",
                }
                qt = type_map.get(ftype, "string")
                parts.append(f"field={f['name']}:{qt}")
            field_defs = "&" + "&".join(parts)

        geom = geometry_type if geometry_type and geometry_type.lower() != "none" else "None"
        uri = f"{geom}?crs={crs}{field_defs}"

        layer = QgsVectorLayer(uri, name, "memory")
        if not layer.isValid():
            raise RuntimeError(f"Failed to create memory layer: {uri}")

        QgsProject.instance().addMapLayer(layer)
        return {
            "id": layer.id(),
            "name": layer.name(),
            "type": s.layer_type_str(layer),
            "crs": layer.crs().authid(),
            "fields": [f.name() for f in layer.fields()],
            "geometry_type": geometry_type,
        }

    s._HANDLERS.update({
        "get_layers": get_layers,
        "add_vector_layer": add_vector_layer,
        "add_raster_layer": add_raster_layer,
        "add_wms_layer": add_wms_layer,
        "remove_layer": remove_layer,
        "duplicate_layer": duplicate_layer,
        "rename_layer": rename_layer,
        "get_layer_info": get_layer_info,
        "get_layer_fields": get_layer_fields,
        "get_layer_extent": get_layer_extent,
        "get_layer_features": get_layer_features,
        "set_layer_visibility": set_layer_visibility,
        "set_layer_opacity": set_layer_opacity,
        "reorder_layers": reorder_layers,
        "group_layers": group_layers,
        "zoom_to_layer": zoom_to_layer,
        "set_layer_temporal": set_layer_temporal,
        "set_temporal_range": set_temporal_range,
        "set_map_tip": set_map_tip,
        "get_map_tip": get_map_tip,
        "add_layer_action": add_layer_action,
        "list_layer_actions": list_layer_actions,
        "remove_layer_action": remove_layer_action,
        "set_layer_note": set_layer_note,
        "get_layer_note": get_layer_note,
        "get_mesh_info": get_mesh_info,
        "get_point_cloud_info": get_point_cloud_info,
        "find_layer": find_layer,
        "create_memory_layer": create_memory_layer,
    })
