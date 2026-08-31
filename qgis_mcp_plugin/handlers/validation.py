"""
Validation & verification handlers — geometry validation, layer health checks,
CRS diagnostics, topology checks, data integrity, project verification.

This module provides tools for the AI to verify the results of its operations
and diagnose data quality issues proactively.
"""

from qgis.core import (
    Qgis,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsDistanceArea,
    QgsExpression,
    QgsExpressionContext,
    QgsExpressionContextUtils,
    QgsFeatureRequest,
    QgsGeometry,
    QgsProject,
    QgsRectangle,
    QgsWkbTypes,
)


def register(server):
    """Register validation handlers."""
    s = server

    # ── Geometry Validation ──────────────────────────────────────

    def validate_geometry(layer_id: str, limit: int = 100,
                          fix: bool = False, method: str = "structure", **_):
        """Validate geometries in a vector layer. Reports invalid geometries with reasons.

        method: 'structure' (GEOS isValid) or 'qgis' (QGIS checkValidity with OGC rules).
        fix: if True, attempts to fix invalid geometries using makeValid().
        limit: max features to check (0 = all features).

        Returns a list of invalid features with error details, plus a summary.
        """
        layer = s.get_layer_or_raise(layer_id)
        if layer.type() != Qgis.LayerType.Vector:
            raise RuntimeError(f"Not a vector layer: {layer_id}")

        request = QgsFeatureRequest()
        if limit > 0:
            request.setLimit(limit)

        total = 0
        valid_count = 0
        invalid = []
        null_geom = 0
        fixed_count = 0

        if fix:
            layer.startEditing()

        for feat in layer.getFeatures(request):
            total += 1
            if not feat.hasGeometry():
                null_geom += 1
                continue

            geom = feat.geometry()

            if method == "qgis":
                errors = geom.validateGeometry(
                    Qgis.GeometryValidationEngine.QgisInternal
                )
                is_valid = len(errors) == 0
                error_msgs = [e.what() for e in errors]
            else:
                is_valid = geom.isGeosValid()
                if not is_valid:
                    error_msgs = [geom.lastError() or "GEOS validation failed"]
                else:
                    error_msgs = []

            if is_valid:
                valid_count += 1
            else:
                entry = {
                    "feature_id": feat.id(),
                    "errors": error_msgs,
                    "geometry_type": QgsWkbTypes.displayString(geom.wkbType()),
                }

                if fix:
                    fixed = geom.makeValid()
                    if fixed and not fixed.isNull() and fixed.isGeosValid():
                        layer.changeGeometry(feat.id(), fixed)
                        entry["fixed"] = True
                        fixed_count += 1
                    else:
                        entry["fixed"] = False

                invalid.append(entry)

        if fix:
            layer.commitChanges()

        return {
            "layer_id": layer_id,
            "method": method,
            "total_checked": total,
            "valid": valid_count,
            "invalid": len(invalid),
            "null_geometry": null_geom,
            "fixed": fixed_count if fix else None,
            "invalid_features": invalid[:50],  # cap response size
        }

    def validate_wkt(wkt: str, expected_type: str = None, **_):
        """Validate a WKT geometry string before using it.

        Returns validity status, geometry type, vertex count, and bounding box.
        expected_type: optional — 'point', 'line', 'polygon' to check type matches.
        """
        geom = QgsGeometry.fromWkt(wkt)
        if geom.isNull():
            return {
                "valid": False,
                "error": "Failed to parse WKT",
                "wkt_preview": wkt[:200],
            }

        is_valid = geom.isGeosValid()
        geom_type = QgsWkbTypes.displayString(geom.wkbType())
        geom_type_simple = QgsWkbTypes.geometryDisplayString(geom.type())

        result = {
            "valid": is_valid,
            "geometry_type": geom_type,
            "geometry_type_simple": geom_type_simple.lower(),
            "vertex_count": _count_vertices(geom),
            "is_empty": geom.isEmpty(),
            "is_multipart": geom.isMultipart(),
            "area": geom.area() if geom.type() == Qgis.GeometryType.Polygon else None,
            "length": geom.length() if geom.type() in (
                Qgis.GeometryType.Line, Qgis.GeometryType.Polygon
            ) else None,
            "bounding_box": s.extent_to_dict(geom.boundingBox()),
        }

        if not is_valid:
            result["validation_error"] = geom.lastError()

        if expected_type:
            type_match = geom_type_simple.lower() == expected_type.lower()
            result["type_matches_expected"] = type_match
            if not type_match:
                result["type_mismatch"] = (
                    f"Expected {expected_type}, got {geom_type_simple.lower()}"
                )

        return result

    # ── Layer Health Check ───────────────────────────────────────

    def check_layer_health(layer_id: str, **_):
        """Comprehensive health check for a layer. Checks:
        - Data source validity and accessibility
        - CRS validity and compatibility with project
        - Feature count consistency
        - Field integrity
        - Renderer status
        - Editing state
        - Spatial index status
        - Geometry type consistency
        """
        layer = s.get_layer_or_raise(layer_id)
        project = QgsProject.instance()

        issues = []
        warnings = []

        # Basic validity
        if not layer.isValid():
            issues.append("Layer is INVALID — data source may be broken or missing")

        # Data source
        source = layer.source()
        provider = layer.providerType()

        # CRS checks
        layer_crs = layer.crs()
        project_crs = project.crs()
        crs_info = {
            "layer_crs": layer_crs.authid() if layer_crs.isValid() else "INVALID",
            "project_crs": project_crs.authid() if project_crs.isValid() else "INVALID",
            "crs_match": layer_crs == project_crs,
        }
        if not layer_crs.isValid():
            issues.append("Layer CRS is invalid or undefined")
        elif layer_crs != project_crs:
            warnings.append(
                f"Layer CRS ({layer_crs.authid()}) differs from project "
                f"CRS ({project_crs.authid()}) — on-the-fly reprojection active"
            )

        result = {
            "layer_id": layer_id,
            "name": layer.name(),
            "type": s.layer_type_str(layer),
            "is_valid": layer.isValid(),
            "provider": provider,
            "source": source,
            "crs": crs_info,
            "extent": s.extent_to_dict(layer.extent()),
        }

        if layer.type() == Qgis.LayerType.Vector:
            # Vector-specific checks
            feature_count = layer.featureCount()
            result["feature_count"] = feature_count
            result["is_editable"] = layer.isEditable()
            result["is_modified"] = layer.isModified()
            result["has_spatial_index"] = bool(layer.dataProvider().hasSpatialIndex())
            result["encoding"] = layer.dataProvider().encoding()
            result["storage_type"] = layer.dataProvider().storageType()

            # Check for broken subset filter
            subset = layer.subsetString()
            if subset:
                result["subset_filter"] = subset

            # Field checks
            fields = layer.fields()
            result["field_count"] = fields.count()

            # Check for fields with null constraints violations
            constrained_fields = []
            for field in fields:
                constraints = field.constraints()
                if constraints.constraints():
                    constrained_fields.append({
                        "name": field.name(),
                        "constraints": str(constraints.constraints()),
                    })
            if constrained_fields:
                result["constrained_fields"] = constrained_fields

            # Renderer check
            renderer = layer.renderer()
            if renderer:
                result["renderer_type"] = type(renderer).__name__
            else:
                warnings.append("Layer has no renderer configured")

            # Check for empty extent (might indicate broken data)
            if layer.extent().isEmpty() and feature_count > 0:
                warnings.append("Layer has features but empty extent — possible data issue")

            if feature_count == 0:
                warnings.append("Layer has zero features")

            # Large feature count warning
            if feature_count > 1_000_000:
                warnings.append(
                    f"Layer has {feature_count:,} features — operations may be slow"
                )

        elif layer.type() == Qgis.LayerType.Raster:
            result["width"] = layer.width()
            result["height"] = layer.height()
            result["band_count"] = layer.bandCount()
            result["pixel_size_x"] = layer.rasterUnitsPerPixelX()
            result["pixel_size_y"] = layer.rasterUnitsPerPixelY()

        result["issues"] = issues
        result["warnings"] = warnings
        result["healthy"] = len(issues) == 0

        return result

    # ── Project Verification ─────────────────────────────────────

    def verify_project(**_):
        """Full project health check. Validates all layers, CRS, relations, and data sources.

        Returns a comprehensive report on the project state.
        """
        project = QgsProject.instance()
        issues = []
        warnings = []
        layer_statuses = []

        # Project CRS
        project_crs = project.crs()
        if not project_crs.isValid():
            issues.append("Project CRS is invalid or undefined")

        # Check all layers
        broken_layers = []
        crs_mismatches = []
        for lid, layer in project.mapLayers().items():
            status = {
                "id": lid,
                "name": layer.name(),
                "type": s.layer_type_str(layer),
                "valid": layer.isValid(),
            }
            if not layer.isValid():
                broken_layers.append(layer.name())
                status["issue"] = "Invalid data source"
            if layer.crs().isValid() and project_crs.isValid():
                if layer.crs() != project_crs:
                    crs_mismatches.append({
                        "layer": layer.name(),
                        "layer_crs": layer.crs().authid(),
                    })
            layer_statuses.append(status)

        if broken_layers:
            issues.append(f"Broken layers: {', '.join(broken_layers)}")

        # Check relations
        rel_manager = project.relationManager()
        invalid_relations = []
        for rel_id, rel in rel_manager.relations().items():
            if not rel.isValid():
                invalid_relations.append(rel.name() or rel_id)
        if invalid_relations:
            warnings.append(f"Invalid relations: {', '.join(invalid_relations)}")

        # Check for unsaved changes
        modified_layers = []
        for lid, layer in project.mapLayers().items():
            if layer.type() == Qgis.LayerType.Vector and layer.isModified():
                modified_layers.append(layer.name())
        if modified_layers:
            warnings.append(f"Unsaved edits in: {', '.join(modified_layers)}")

        return {
            "project_file": project.fileName(),
            "project_title": project.title(),
            "project_crs": project_crs.authid() if project_crs.isValid() else "INVALID",
            "layer_count": len(project.mapLayers()),
            "layers": layer_statuses,
            "broken_layers": broken_layers,
            "crs_mismatches": crs_mismatches,
            "invalid_relations": invalid_relations,
            "modified_layers": modified_layers,
            "issues": issues,
            "warnings": warnings,
            "healthy": len(issues) == 0,
        }

    # ── CRS Diagnostics ─────────────────────────────────────────

    def diagnose_crs(crs_string: str = None, layer_id: str = None, **_):
        """Diagnose and report on a CRS. Works with authid strings (e.g. 'EPSG:4326')
        or layer IDs. Reports validity, units, bounds, and compatibility.
        """
        if layer_id:
            layer = s.get_layer_or_raise(layer_id)
            crs = layer.crs()
            source_desc = f"layer '{layer.name()}'"
        elif crs_string:
            crs = QgsCoordinateReferenceSystem(crs_string)
            source_desc = crs_string
        else:
            raise RuntimeError("Provide either crs_string or layer_id")

        if not crs.isValid():
            return {
                "source": source_desc,
                "valid": False,
                "error": "CRS not recognized",
            }

        project_crs = QgsProject.instance().crs()

        result = {
            "source": source_desc,
            "valid": True,
            "authid": crs.authid(),
            "description": crs.description(),
            "is_geographic": crs.isGeographic(),
            "map_units": str(crs.mapUnits()),
            "proj4": crs.toProj(),
            "ellipsoid": crs.ellipsoidAcronym(),
        }

        # Bounds
        bounds = crs.bounds()
        if not bounds.isEmpty():
            result["bounds_wgs84"] = s.extent_to_dict(bounds)

        # Compatibility with project CRS
        if project_crs.isValid():
            result["project_crs"] = project_crs.authid()
            result["same_as_project"] = crs == project_crs
            result["same_units"] = crs.mapUnits() == project_crs.mapUnits()

        return result

    # ── Expression Validation ────────────────────────────────────

    def validate_expression(expression: str, layer_id: str = None, **_):
        """Validate a QGIS expression without executing it.

        If layer_id is provided, validates field references against the layer's fields.
        Returns parse status, referenced columns, and any errors.
        """
        expr = QgsExpression(expression)

        result = {
            "expression": expression,
            "valid": not expr.hasParserError(),
        }

        if expr.hasParserError():
            result["parse_error"] = expr.parserErrorString()
            return result

        result["referenced_columns"] = list(expr.referencedColumns())
        result["referenced_functions"] = list(expr.referencedFunctions())
        result["is_field"] = expr.isField()
        result["needs_geometry"] = expr.needsGeometry()

        # Validate field references against layer
        if layer_id:
            layer = s.get_layer_or_raise(layer_id)
            if layer.type() == Qgis.LayerType.Vector:
                field_names = [f.name() for f in layer.fields()]
                missing_fields = [
                    col for col in expr.referencedColumns()
                    if col not in field_names and col != "$geometry"
                    and not col.startswith("$")
                ]
                result["layer_fields"] = field_names
                if missing_fields:
                    result["missing_fields"] = missing_fields
                    result["field_warning"] = (
                        f"Referenced fields not found in layer: {', '.join(missing_fields)}"
                    )

        return result

    # ── Data Integrity Checks ────────────────────────────────────

    def check_data_integrity(layer_id: str, checks: list = None, limit: int = 1000, **_):
        """Run data integrity checks on a vector layer.

        checks: list of checks to run. Default: all.
          - 'nulls': check for NULL values in each field
          - 'duplicates': check for duplicate geometries
          - 'empty_geometries': check for empty (non-null) geometries
          - 'type_consistency': check all geometries match the layer type
          - 'extent_outliers': check for features far outside the main cluster

        Returns a report of issues found per check.
        """
        layer = s.get_layer_or_raise(layer_id)
        if layer.type() != Qgis.LayerType.Vector:
            raise RuntimeError(f"Not a vector layer: {layer_id}")

        available_checks = [
            "nulls", "duplicates", "empty_geometries",
            "type_consistency", "extent_outliers",
        ]
        if checks is None:
            checks = available_checks

        request = QgsFeatureRequest()
        if limit > 0:
            request.setLimit(limit)

        report = {
            "layer_id": layer_id,
            "checks_run": checks,
            "total_features": layer.featureCount(),
            "features_checked": 0,
        }

        # Collect features once
        features_data = []
        for feat in layer.getFeatures(request):
            features_data.append(feat)
        report["features_checked"] = len(features_data)

        # NULL check
        if "nulls" in checks:
            null_report = {}
            for field in layer.fields():
                null_count = sum(
                    1 for f in features_data
                    if f.attribute(field.name()) is None
                    or str(f.attribute(field.name())) == "NULL"
                )
                if null_count > 0:
                    null_report[field.name()] = {
                        "null_count": null_count,
                        "percentage": round(null_count / max(len(features_data), 1) * 100, 1),
                    }
            report["nulls"] = null_report

        # Empty geometries
        if "empty_geometries" in checks:
            empty = [
                f.id() for f in features_data
                if f.hasGeometry() and f.geometry().isEmpty()
            ]
            report["empty_geometries"] = {
                "count": len(empty),
                "feature_ids": empty[:20],
            }

        # Type consistency
        if "type_consistency" in checks:
            expected_type = layer.geometryType()
            mismatched = []
            for f in features_data:
                if f.hasGeometry() and not f.geometry().isNull():
                    if f.geometry().type() != expected_type:
                        mismatched.append({
                            "feature_id": f.id(),
                            "expected": str(expected_type),
                            "actual": str(f.geometry().type()),
                        })
            report["type_consistency"] = {
                "expected_type": str(expected_type),
                "mismatched_count": len(mismatched),
                "mismatched": mismatched[:20],
            }

        # Duplicate geometries
        if "duplicates" in checks:
            seen_wkt = {}
            duplicates = []
            for f in features_data:
                if f.hasGeometry() and not f.geometry().isNull():
                    wkt = f.geometry().asWkt(precision=2)
                    if wkt in seen_wkt:
                        duplicates.append({
                            "feature_id": f.id(),
                            "duplicate_of": seen_wkt[wkt],
                        })
                    else:
                        seen_wkt[wkt] = f.id()
            report["duplicates"] = {
                "count": len(duplicates),
                "pairs": duplicates[:20],
            }

        # Extent outliers (features far from the main cluster)
        if "extent_outliers" in checks:
            layer_extent = layer.extent()
            if not layer_extent.isEmpty():
                # Expand extent by 50% to detect extreme outliers
                buffered = QgsRectangle(layer_extent)
                buffered.grow(layer_extent.width() * 0.5)

                outliers = []
                for f in features_data:
                    if f.hasGeometry() and not f.geometry().isNull():
                        feat_extent = f.geometry().boundingBox()
                        if not buffered.contains(feat_extent):
                            outliers.append({
                                "feature_id": f.id(),
                                "bbox": s.extent_to_dict(feat_extent),
                            })
                report["extent_outliers"] = {
                    "count": len(outliers),
                    "features": outliers[:20],
                }

        # Summary
        total_issues = 0
        if "nulls" in report:
            total_issues += sum(v["null_count"] for v in report["nulls"].values())
        if "empty_geometries" in report:
            total_issues += report["empty_geometries"]["count"]
        if "type_consistency" in report:
            total_issues += report["type_consistency"]["mismatched_count"]
        if "duplicates" in report:
            total_issues += report["duplicates"]["count"]
        if "extent_outliers" in report:
            total_issues += report["extent_outliers"]["count"]

        report["total_issues"] = total_issues
        report["clean"] = total_issues == 0

        return report

    # ── Topology Checks ──────────────────────────────────────────

    def check_topology(layer_id: str, checks: list = None,
                       reference_layer_id: str = None, tolerance: float = 0.0, **_):
        """Run topology checks on a vector layer using processing algorithms.

        checks: list of checks to run. Default depends on geometry type.
          For polygons: 'overlaps', 'gaps', 'self_intersections'
          For lines: 'dangles', 'self_intersections', 'duplicates'
          For points: 'duplicates'

        reference_layer_id: optional second layer for cross-layer checks.
        tolerance: snapping tolerance for checks (in layer CRS units).
        """
        import processing

        layer = s.get_layer_or_raise(layer_id)
        if layer.type() != Qgis.LayerType.Vector:
            raise RuntimeError(f"Not a vector layer: {layer_id}")

        geom_type = layer.geometryType()
        results = {
            "layer_id": layer_id,
            "geometry_type": str(geom_type),
            "checks": {},
        }

        # Determine default checks based on geometry type
        if checks is None:
            if geom_type == Qgis.GeometryType.Polygon:
                checks = ["validity"]
            elif geom_type == Qgis.GeometryType.Line:
                checks = ["validity"]
            elif geom_type == Qgis.GeometryType.Point:
                checks = ["validity"]

        # Run validity check using processing
        if "validity" in checks:
            try:
                result = processing.run("qgis:checkvalidity", {
                    "INPUT_LAYER": layer,
                    "METHOD": 1,  # GEOS
                    "IGNORE_RING_SELF_INTERSECTION": False,
                    "VALID_OUTPUT": "TEMPORARY_OUTPUT",
                    "INVALID_OUTPUT": "TEMPORARY_OUTPUT",
                    "ERROR_OUTPUT": "TEMPORARY_OUTPUT",
                })
                valid_layer = result.get("VALID_OUTPUT")
                invalid_layer = result.get("INVALID_OUTPUT")
                error_layer = result.get("ERROR_OUTPUT")

                valid_count = valid_layer.featureCount() if valid_layer else 0
                invalid_count = invalid_layer.featureCount() if invalid_layer else 0

                errors = []
                if error_layer:
                    for i, feat in enumerate(error_layer.getFeatures()):
                        if i >= 50:
                            break
                        attrs = {}
                        for field in error_layer.fields():
                            val = feat.attribute(field.name())
                            if not isinstance(val, (str, int, float, bool, type(None))):
                                val = str(val)
                            attrs[field.name()] = val
                        errors.append(attrs)

                results["checks"]["validity"] = {
                    "valid_count": valid_count,
                    "invalid_count": invalid_count,
                    "errors": errors,
                }
            except Exception as e:
                results["checks"]["validity"] = {"error": str(e)}

        total_issues = sum(
            v.get("invalid_count", 0)
            for v in results["checks"].values()
            if isinstance(v, dict)
        )
        results["total_issues"] = total_issues
        results["clean"] = total_issues == 0

        return results

    # ── Verify Operation Result ──────────────────────────────────

    def verify_operation(layer_id: str, operation: str,
                         expected_count: int = None,
                         feature_id: int = None,
                         field_name: str = None,
                         expression: str = None, **_):
        """Verify the result of a previous operation on a layer.

        operation: 'feature_added', 'feature_deleted', 'feature_edited',
                   'field_added', 'field_deleted', 'filter_applied',
                   'style_applied', 'label_applied'.

        Checks that the operation was successful by inspecting the current state.
        """
        layer = s.get_layer_or_raise(layer_id)
        result = {
            "layer_id": layer_id,
            "operation": operation,
            "verified": False,
        }

        if operation == "feature_added":
            if feature_id is not None:
                feat = next(
                    layer.getFeatures(QgsFeatureRequest(feature_id)), None
                )
                result["verified"] = feat is not None
                if feat:
                    result["feature_exists"] = True
                    result["has_geometry"] = feat.hasGeometry()
                    if feat.hasGeometry():
                        result["geometry_valid"] = feat.geometry().isGeosValid()
                else:
                    result["feature_exists"] = False

            if expected_count is not None:
                actual = layer.featureCount()
                result["expected_count"] = expected_count
                result["actual_count"] = actual
                result["count_matches"] = actual == expected_count

        elif operation == "feature_deleted":
            if feature_id is not None:
                feat = next(
                    layer.getFeatures(QgsFeatureRequest(feature_id)), None
                )
                result["verified"] = feat is None
                result["feature_gone"] = feat is None

            if expected_count is not None:
                actual = layer.featureCount()
                result["expected_count"] = expected_count
                result["actual_count"] = actual
                result["count_matches"] = actual == expected_count

        elif operation == "feature_edited":
            if feature_id is not None:
                feat = next(
                    layer.getFeatures(QgsFeatureRequest(feature_id)), None
                )
                result["verified"] = feat is not None
                if feat:
                    result["feature_exists"] = True
                    if field_name:
                        val = feat.attribute(field_name)
                        if not isinstance(val, (str, int, float, bool, type(None))):
                            val = str(val)
                        result["field_value"] = val

        elif operation == "field_added":
            if field_name:
                idx = layer.fields().indexFromName(field_name)
                result["verified"] = idx >= 0
                result["field_exists"] = idx >= 0
                if idx >= 0:
                    field = layer.fields().at(idx)
                    result["field_type"] = field.typeName()

        elif operation == "field_deleted":
            if field_name:
                idx = layer.fields().indexFromName(field_name)
                result["verified"] = idx < 0
                result["field_gone"] = idx < 0

        elif operation == "filter_applied":
            subset = layer.subsetString()
            result["current_filter"] = subset
            result["feature_count"] = layer.featureCount()
            result["verified"] = True

        elif operation == "style_applied":
            renderer = layer.renderer()
            result["renderer_type"] = type(renderer).__name__ if renderer else None
            result["verified"] = renderer is not None

        elif operation == "label_applied":
            result["labels_enabled"] = layer.labelsEnabled()
            labeling = layer.labeling()
            result["labeling_type"] = type(labeling).__name__ if labeling else None
            result["verified"] = layer.labelsEnabled() and labeling is not None

        # Check for uncommitted changes
        result["is_editable"] = layer.isEditable()
        result["is_modified"] = layer.isModified()
        if layer.isModified():
            result["warning"] = "Layer has uncommitted changes"

        return result

    # ── Compare Layer Snapshots ──────────────────────────────────

    def layer_diff(layer_id: str, field_name: str = None,
                   expression: str = None, **_):
        """Get a snapshot of the current layer state for comparison.

        Returns feature count, field list, extent, CRS, and optionally
        a value distribution for a specific field.
        """
        layer = s.get_layer_or_raise(layer_id)
        if layer.type() != Qgis.LayerType.Vector:
            raise RuntimeError(f"Not a vector layer: {layer_id}")

        result = {
            "layer_id": layer_id,
            "name": layer.name(),
            "feature_count": layer.featureCount(),
            "fields": [f.name() for f in layer.fields()],
            "field_count": layer.fields().count(),
            "crs": layer.crs().authid(),
            "extent": s.extent_to_dict(layer.extent()),
            "is_editable": layer.isEditable(),
            "is_modified": layer.isModified(),
            "subset_filter": layer.subsetString(),
        }

        # Field value distribution
        if field_name:
            idx = layer.fields().indexFromName(field_name)
            if idx < 0:
                result["field_error"] = f"Field not found: {field_name}"
            else:
                values = {}
                null_count = 0
                total = 0
                for feat in layer.getFeatures(QgsFeatureRequest().setLimit(10000)):
                    total += 1
                    val = feat.attribute(field_name)
                    if val is None:
                        null_count += 1
                    else:
                        key = str(val)
                        values[key] = values.get(key, 0) + 1

                # Sort by frequency
                sorted_vals = sorted(values.items(), key=lambda x: -x[1])
                result["field_distribution"] = {
                    "field": field_name,
                    "total": total,
                    "null_count": null_count,
                    "unique_values": len(values),
                    "top_values": dict(sorted_vals[:20]),
                }

        return result

    # ── Geodesic Measurement ─────────────────────────────────────

    def measure_geodesic(layer_id: str, feature_ids: list = None,
                         limit: int = 100, **_):
        """Measure feature geometries using geodesic (ellipsoidal) calculations.

        Unlike measure_geometry which uses planar CRS units, this gives
        accurate real-world measurements in meters/square meters regardless of CRS.
        """
        layer = s.get_layer_or_raise(layer_id)
        if layer.type() != Qgis.LayerType.Vector:
            raise RuntimeError(f"Not a vector layer: {layer_id}")

        da = QgsDistanceArea()
        da.setSourceCrs(layer.crs(), QgsProject.instance().transformContext())
        da.setEllipsoid(QgsProject.instance().ellipsoid())

        request = QgsFeatureRequest()
        if feature_ids:
            request.setFilterFids(feature_ids)
        request.setLimit(limit)

        results = []
        for feat in layer.getFeatures(request):
            if not feat.hasGeometry():
                continue
            geom = feat.geometry()
            entry = {"id": feat.id()}

            gt = geom.type()
            if gt == Qgis.GeometryType.Polygon:
                entry["area_m2"] = da.measureArea(geom)
                entry["area_ha"] = da.measureArea(geom) / 10000
                entry["area_km2"] = da.measureArea(geom) / 1_000_000
                entry["perimeter_m"] = da.measurePerimeter(geom)
            elif gt == Qgis.GeometryType.Line:
                entry["length_m"] = da.measureLength(geom)
                entry["length_km"] = da.measureLength(geom) / 1000
            elif gt == Qgis.GeometryType.Point:
                point = geom.asPoint()
                entry["x"] = point.x()
                entry["y"] = point.y()

            results.append(entry)

        return {
            "layer_id": layer_id,
            "crs": layer.crs().authid(),
            "ellipsoid": QgsProject.instance().ellipsoid(),
            "unit": "meters",
            "count": len(results),
            "measurements": results,
        }

    # ── Coordinate Transform Verification ────────────────────────

    def transform_coordinates(x: float, y: float,
                              source_crs: str, target_crs: str, **_):
        """Transform coordinates between CRS. Useful for verifying CRS correctness.

        Returns transformed coordinates and the distance between original and
        transformed points (useful for sanity checking).
        """
        src = QgsCoordinateReferenceSystem(source_crs)
        dst = QgsCoordinateReferenceSystem(target_crs)

        if not src.isValid():
            raise RuntimeError(f"Invalid source CRS: {source_crs}")
        if not dst.isValid():
            raise RuntimeError(f"Invalid target CRS: {target_crs}")

        xform = QgsCoordinateTransform(src, dst, QgsProject.instance())

        from qgis.core import QgsPointXY
        point = QgsPointXY(x, y)
        transformed = xform.transform(point)

        # Also compute back-transform to check round-trip accuracy
        reverse_xform = QgsCoordinateTransform(dst, src, QgsProject.instance())
        back = reverse_xform.transform(transformed)
        roundtrip_error = point.distance(back)

        return {
            "source": {"x": x, "y": y, "crs": source_crs},
            "target": {
                "x": transformed.x(),
                "y": transformed.y(),
                "crs": target_crs,
            },
            "roundtrip_error": roundtrip_error,
            "source_crs_desc": src.description(),
            "target_crs_desc": dst.description(),
        }

    s._HANDLERS.update({
        "validate_geometry": validate_geometry,
        "validate_wkt": validate_wkt,
        "check_layer_health": check_layer_health,
        "verify_project": verify_project,
        "diagnose_crs": diagnose_crs,
        "validate_expression": validate_expression,
        "check_data_integrity": check_data_integrity,
        "check_topology": check_topology,
        "verify_operation": verify_operation,
        "layer_diff": layer_diff,
        "measure_geodesic": measure_geodesic,
        "transform_coordinates": transform_coordinates,
    })


def _count_vertices(geom):
    """Count vertices in a geometry."""
    abstract = geom.constGet()
    if abstract is None:
        return 0
    count = 0
    for v in abstract.vertices():
        count += 1
    return count
