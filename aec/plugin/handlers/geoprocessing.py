"""
Geoprocessing handlers — common spatial operations with built-in verification.

Wraps processing algorithms in user-friendly tools with proper error handling,
result verification, and auto-adding output layers to the project.
"""

import os

from qgis.core import (
    Qgis,
    QgsProject,
    QgsVectorLayer,
)


def register(server):
    """Register geoprocessing handlers."""
    s = server

    def _run_and_add(algorithm: str, params: dict, output_key: str = "OUTPUT",
                     name: str = None, add_to_project: bool = True):
        """Run a processing algorithm and optionally add output to project.

        Returns the output layer info with verification.
        """
        import processing
        result = processing.run(algorithm, params)

        output = result.get(output_key)
        if output is None:
            return {
                "algorithm": algorithm,
                "result": {k: str(v) for k, v in result.items()},
            }

        # If output is a layer path, load it
        if isinstance(output, str):
            layer = QgsVectorLayer(output, name or os.path.basename(output), "ogr")
        elif isinstance(output, QgsVectorLayer):
            layer = output
        else:
            return {
                "algorithm": algorithm,
                "output": str(output),
                "result": {k: str(v) for k, v in result.items()},
            }

        if layer and layer.isValid():
            if name:
                layer.setName(name)
            if add_to_project:
                QgsProject.instance().addMapLayer(layer)
            return {
                "algorithm": algorithm,
                "output_layer_id": layer.id() if add_to_project else None,
                "output_name": layer.name(),
                "feature_count": layer.featureCount(),
                "crs": layer.crs().authid(),
                "is_valid": layer.isValid(),
            }
        else:
            raise RuntimeError(f"Processing output is invalid: {algorithm}")

    def buffer(layer_id: str, distance: float, segments: int = 8,
               dissolve: bool = False, name: str = None, **_):
        """Create buffer zones around features.

        distance: buffer distance in layer CRS units (use negative for inward buffer on polygons).
        segments: number of segments for circular approximation (higher = smoother).
        dissolve: if True, dissolve all buffers into a single feature.
        name: name for the output layer. Default: '{layer_name}_buffer'.
        """
        import processing
        layer = s.get_layer_or_raise(layer_id)
        output_name = name or f"{layer.name()}_buffer"

        return _run_and_add("native:buffer", {
            "INPUT": layer,
            "DISTANCE": distance,
            "SEGMENTS": segments,
            "DISSOLVE": dissolve,
            "OUTPUT": "TEMPORARY_OUTPUT",
        }, name=output_name)

    def clip(input_layer_id: str, overlay_layer_id: str,
             name: str = None, **_):
        """Clip features from input layer using overlay layer as a cookie cutter.

        Only parts of input features that fall within the overlay are kept.
        """
        import processing
        input_layer = s.get_layer_or_raise(input_layer_id)
        overlay_layer = s.get_layer_or_raise(overlay_layer_id)
        output_name = name or f"{input_layer.name()}_clipped"

        return _run_and_add("native:clip", {
            "INPUT": input_layer,
            "OVERLAY": overlay_layer,
            "OUTPUT": "TEMPORARY_OUTPUT",
        }, name=output_name)

    def intersection(input_layer_id: str, overlay_layer_id: str,
                     name: str = None, **_):
        """Calculate the geometric intersection of input and overlay layers.

        Output contains only the parts where both layers overlap,
        with attributes from both layers.
        """
        import processing
        input_layer = s.get_layer_or_raise(input_layer_id)
        overlay_layer = s.get_layer_or_raise(overlay_layer_id)
        output_name = name or f"{input_layer.name()}_intersection"

        return _run_and_add("native:intersection", {
            "INPUT": input_layer,
            "OVERLAY": overlay_layer,
            "OUTPUT": "TEMPORARY_OUTPUT",
        }, name=output_name)

    def union(input_layer_id: str, overlay_layer_id: str = None,
              name: str = None, **_):
        """Union of input and overlay layers. If no overlay, dissolve input.

        Combines all features from both layers.
        """
        import processing
        input_layer = s.get_layer_or_raise(input_layer_id)
        output_name = name or f"{input_layer.name()}_union"

        params = {
            "INPUT": input_layer,
            "OUTPUT": "TEMPORARY_OUTPUT",
        }
        if overlay_layer_id:
            overlay_layer = s.get_layer_or_raise(overlay_layer_id)
            params["OVERLAY"] = overlay_layer

        return _run_and_add("native:union", params, name=output_name)

    def dissolve(layer_id: str, field: str = None,
                 name: str = None, **_):
        """Dissolve features, optionally grouping by a field.

        field: field name to group by (features with same value merge).
               Omit to dissolve everything into one feature.
        """
        import processing
        layer = s.get_layer_or_raise(layer_id)
        output_name = name or f"{layer.name()}_dissolved"

        params = {
            "INPUT": layer,
            "OUTPUT": "TEMPORARY_OUTPUT",
        }
        if field:
            params["FIELD"] = [field]

        return _run_and_add("native:dissolve", params, name=output_name)

    def difference(input_layer_id: str, overlay_layer_id: str,
                   name: str = None, **_):
        """Subtract overlay from input (erase operation).

        Keeps parts of input features that do NOT overlap with overlay.
        """
        import processing
        input_layer = s.get_layer_or_raise(input_layer_id)
        overlay_layer = s.get_layer_or_raise(overlay_layer_id)
        output_name = name or f"{input_layer.name()}_difference"

        return _run_and_add("native:difference", {
            "INPUT": input_layer,
            "OVERLAY": overlay_layer,
            "OUTPUT": "TEMPORARY_OUTPUT",
        }, name=output_name)

    def centroid(layer_id: str, name: str = None, **_):
        """Create point layer from polygon/line centroids."""
        import processing
        layer = s.get_layer_or_raise(layer_id)
        output_name = name or f"{layer.name()}_centroids"

        return _run_and_add("native:centroids", {
            "INPUT": layer,
            "ALL_PARTS": True,
            "OUTPUT": "TEMPORARY_OUTPUT",
        }, name=output_name)

    def convex_hull(layer_id: str, name: str = None, **_):
        """Create convex hull polygon for each feature or for all features."""
        import processing
        layer = s.get_layer_or_raise(layer_id)
        output_name = name or f"{layer.name()}_hull"

        return _run_and_add("native:convexhull", {
            "INPUT": layer,
            "OUTPUT": "TEMPORARY_OUTPUT",
        }, name=output_name)

    def voronoi(layer_id: str, buffer_pct: float = 0.0,
                name: str = None, **_):
        """Create Voronoi polygons from a point layer.

        buffer_pct: buffer percentage to extend the extent (0-100).
        """
        import processing
        layer = s.get_layer_or_raise(layer_id)
        if layer.geometryType() != Qgis.GeometryType.Point:
            raise RuntimeError("Voronoi requires a point layer")
        output_name = name or f"{layer.name()}_voronoi"

        return _run_and_add("qgis:voronoipolygons", {
            "INPUT": layer,
            "BUFFER": buffer_pct,
            "OUTPUT": "TEMPORARY_OUTPUT",
        }, name=output_name)

    def simplify(layer_id: str, tolerance: float = 1.0,
                 method: str = "douglas_peucker", name: str = None, **_):
        """Simplify geometries to reduce vertex count.

        method: 'douglas_peucker' (default), 'visvalingam', 'snap_to_grid'.
        tolerance: simplification threshold in layer CRS units.
        """
        import processing
        layer = s.get_layer_or_raise(layer_id)
        output_name = name or f"{layer.name()}_simplified"

        method_map = {
            "douglas_peucker": 0,
            "visvalingam": 2,
            "snap_to_grid": 1,
        }
        method_code = method_map.get(method.lower(), 0)

        return _run_and_add("native:simplifygeometries", {
            "INPUT": layer,
            "METHOD": method_code,
            "TOLERANCE": tolerance,
            "OUTPUT": "TEMPORARY_OUTPUT",
        }, name=output_name)

    def reproject(layer_id: str, target_crs: str,
                  name: str = None, **_):
        """Reproject a layer to a different CRS.

        target_crs: e.g. 'EPSG:4326', 'EPSG:25832'.
        Creates a new layer in the target CRS.
        """
        import processing
        layer = s.get_layer_or_raise(layer_id)
        output_name = name or f"{layer.name()}_{target_crs.replace(':', '_')}"

        return _run_and_add("native:reprojectlayer", {
            "INPUT": layer,
            "TARGET_CRS": target_crs,
            "OUTPUT": "TEMPORARY_OUTPUT",
        }, name=output_name)

    def merge_layers(layer_ids: list, name: str = "merged", **_):
        """Merge multiple vector layers into one.

        All layers should have compatible geometry types.
        """
        import processing
        layers = [s.get_layer_or_raise(lid) for lid in layer_ids]
        return _run_and_add("native:mergevectorlayers", {
            "LAYERS": layers,
            "OUTPUT": "TEMPORARY_OUTPUT",
        }, name=name)

    def join_by_location(input_layer_id: str, join_layer_id: str,
                         predicate: str = "intersects",
                         join_type: str = "one_to_many",
                         name: str = None, **_):
        """Spatial join: attach attributes from join_layer to input_layer based on spatial relationship.

        predicate: intersects, contains, within, crosses, touches, overlaps, equals.
        join_type: 'one_to_many' (default) or 'one_to_one' (takes first match).
        """
        import processing
        input_layer = s.get_layer_or_raise(input_layer_id)
        join_layer = s.get_layer_or_raise(join_layer_id)
        output_name = name or f"{input_layer.name()}_joined"

        predicate_map = {
            "intersects": 0, "contains": 1, "equals": 2,
            "touches": 3, "overlaps": 4, "within": 5, "crosses": 6,
        }
        pred_val = predicate_map.get(predicate.lower(), 0)

        join_type_map = {
            "one_to_many": 0,
            "one_to_one": 1,
        }
        join_val = join_type_map.get(join_type.lower(), 0)

        return _run_and_add("native:joinattributesbylocation", {
            "INPUT": input_layer,
            "JOIN": join_layer,
            "PREDICATE": [pred_val],
            "JOIN_FIELDS": [],
            "METHOD": join_val,
            "PREFIX": "",
            "OUTPUT": "TEMPORARY_OUTPUT",
        }, name=output_name)

    def create_grid(extent: dict, grid_type: str = "rectangle",
                    h_spacing: float = 1000, v_spacing: float = 1000,
                    crs: str = None, name: str = "grid", **_):
        """Create a grid layer covering an extent.

        extent: {xmin, ymin, xmax, ymax}
        grid_type: 'point', 'line', 'rectangle', 'diamond', 'hexagon'.
        h_spacing/v_spacing: grid cell size in CRS units.
        crs: CRS for the grid (default: project CRS).
        """
        import processing

        type_map = {
            "point": 0, "line": 1, "rectangle": 2,
            "diamond": 3, "hexagon": 4,
        }
        grid_type_val = type_map.get(grid_type.lower(), 2)

        project = QgsProject.instance()
        grid_crs = crs or project.crs().authid()
        extent_str = f"{extent['xmin']},{extent['xmax']},{extent['ymin']},{extent['ymax']} [{grid_crs}]"

        return _run_and_add("native:creategrid", {
            "TYPE": grid_type_val,
            "EXTENT": extent_str,
            "HSPACING": h_spacing,
            "VSPACING": v_spacing,
            "HOVERLAY": 0,
            "VOVERLAY": 0,
            "CRS": grid_crs,
            "OUTPUT": "TEMPORARY_OUTPUT",
        }, name=name)

    def random_points(extent: dict = None, layer_id: str = None,
                      count: int = 100, min_distance: float = 0,
                      crs: str = None, name: str = "random_points", **_):
        """Generate random points within an extent or polygon layer.

        Either extent {xmin, ymin, xmax, ymax} or layer_id (polygon) required.
        min_distance: minimum distance between points.
        """
        import processing

        if layer_id:
            layer = s.get_layer_or_raise(layer_id)
            return _run_and_add("native:randompointsinpolygons", {
                "INPUT": layer,
                "POINTS_NUMBER": count,
                "MIN_DISTANCE": min_distance,
                "OUTPUT": "TEMPORARY_OUTPUT",
            }, name=name)
        elif extent:
            project = QgsProject.instance()
            grid_crs = crs or project.crs().authid()
            extent_str = f"{extent['xmin']},{extent['xmax']},{extent['ymin']},{extent['ymax']} [{grid_crs}]"
            return _run_and_add("native:randompointsinextent", {
                "EXTENT": extent_str,
                "POINTS_NUMBER": count,
                "MIN_DISTANCE": min_distance,
                "TARGET_CRS": grid_crs,
                "OUTPUT": "TEMPORARY_OUTPUT",
            }, name=name)
        else:
            raise RuntimeError("Provide either extent or layer_id")

    def heatmap(layer_id: str, radius: float = 100, pixel_size: float = 10,
                weight_field: str = None, name: str = None, path: str = None, **_):
        """Generate a heatmap (kernel density) raster from a point layer.

        radius: search radius in map units.
        pixel_size: output raster pixel size.
        weight_field: optional field to weight points by.
        path: output raster file path (default: temporary).
        """
        import processing
        layer = s.get_layer_or_raise(layer_id)
        if layer.geometryType() != Qgis.GeometryType.Point:
            raise RuntimeError("Heatmap requires a point layer")

        output_name = name or f"{layer.name()}_heatmap"
        output_path = path or "TEMPORARY_OUTPUT"

        params = {
            "INPUT": layer,
            "RADIUS": radius,
            "PIXEL_SIZE": pixel_size,
            "OUTPUT": output_path,
        }
        if weight_field:
            params["WEIGHT_FIELD"] = weight_field

        import processing
        result = processing.run("native:heatmapkerneldensityestimation", params)

        output = result.get("OUTPUT")
        if output and os.path.exists(str(output)):
            from qgis.core import QgsRasterLayer
            raster = QgsRasterLayer(str(output), output_name)
            if raster.isValid():
                QgsProject.instance().addMapLayer(raster)
                return {
                    "algorithm": "native:heatmapkerneldensityestimation",
                    "output_layer_id": raster.id(),
                    "output_name": raster.name(),
                    "path": str(output),
                    "radius": radius,
                    "pixel_size": pixel_size,
                }
        return {
            "algorithm": "native:heatmapkerneldensityestimation",
            "result": {k: str(v) for k, v in result.items()},
        }

    s._HANDLERS.update({
        "buffer": buffer,
        "clip": clip,
        "intersection": intersection,
        "union": union,
        "dissolve": dissolve,
        "difference": difference,
        "centroid": centroid,
        "convex_hull": convex_hull,
        "voronoi": voronoi,
        "simplify": simplify,
        "reproject": reproject,
        "merge_layers": merge_layers,
        "join_by_location": join_by_location,
        "create_grid": create_grid,
        "random_points": random_points,
        "heatmap": heatmap,
    })
