"""
Export & file I/O handlers — save layers to files, export formats, import data.
"""

import os

from qgis.core import (
    Qgis,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsProject,
    QgsVectorFileWriter,
    QgsVectorLayer,
)


def register(server):
    """Register export handlers."""
    s = server

    def export_layer(layer_id: str, path: str, format: str = "GPKG",
                     crs: str = None, selected_only: bool = False, **_):
        """Export a vector layer to a file.

        format: GPKG (GeoPackage), GeoJSON, ESRI Shapefile, CSV, KML, DXF,
                SQLite, MapInfo File, etc.
        crs: target CRS (e.g. 'EPSG:4326'). Omit to keep layer CRS.
        selected_only: if True, export only selected features.

        Returns the path to the exported file.
        """
        layer = s.get_layer_or_raise(layer_id)
        if layer.type() != Qgis.LayerType.Vector:
            raise RuntimeError(f"Not a vector layer: {layer_id}")

        # Determine target CRS
        if crs:
            target_crs = QgsCoordinateReferenceSystem(crs)
            if not target_crs.isValid():
                raise RuntimeError(f"Invalid target CRS: {crs}")
            transform = QgsCoordinateTransform(
                layer.crs(), target_crs, QgsProject.instance()
            )
        else:
            target_crs = layer.crs()
            transform = QgsCoordinateTransform()

        # Detect format from extension if format not recognized
        format_map = {
            ".gpkg": "GPKG",
            ".geojson": "GeoJSON",
            ".json": "GeoJSON",
            ".shp": "ESRI Shapefile",
            ".csv": "CSV",
            ".kml": "KML",
            ".gml": "GML",
            ".dxf": "DXF",
            ".sqlite": "SQLite",
            ".tab": "MapInfo File",
        }
        ext = os.path.splitext(path)[1].lower()
        if format == "GPKG" and ext in format_map:
            format = format_map[ext]

        # Build options
        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = format
        options.fileEncoding = "UTF-8"
        if selected_only:
            options.onlySelectedFeatures = True
        if crs:
            options.ct = transform

        error, error_msg, new_path, new_layer = QgsVectorFileWriter.writeAsVectorFormatV3(
            layer, path, QgsProject.instance().transformContext(), options
        )

        if error != QgsVectorFileWriter.WriterError.NoError:
            raise RuntimeError(f"Export failed: {error_msg}")

        # Verify export
        verify_layer = QgsVectorLayer(path, "verify", "ogr")
        exported_count = verify_layer.featureCount() if verify_layer.isValid() else -1

        return {
            "layer_id": layer_id,
            "path": new_path or path,
            "format": format,
            "crs": target_crs.authid(),
            "feature_count": exported_count,
            "selected_only": selected_only,
            "file_size_bytes": os.path.getsize(path) if os.path.exists(path) else None,
        }

    def import_and_add_layer(path: str, name: str = None, provider: str = "ogr",
                             crs_override: str = None, **_):
        """Import a data file and add it to the project. Auto-detects format.

        Supports: GeoPackage, Shapefile, GeoJSON, CSV, KML, GML, DXF, GPX, etc.
        crs_override: set CRS if the file doesn't have one defined.

        Returns layer info with validation status.
        """
        if not os.path.exists(path):
            raise RuntimeError(f"File not found: {path}")

        display_name = name or os.path.splitext(os.path.basename(path))[0]

        # Handle CSV with coordinates
        ext = os.path.splitext(path)[1].lower()
        if ext == ".csv" and provider == "ogr":
            # Try to detect if it has coordinate columns
            provider = "delimitedtext"
            uri = f"file:///{path}?delimiter=,&detectTypes=yes"
            layer = QgsVectorLayer(uri, display_name, provider)
        else:
            layer = QgsVectorLayer(path, display_name, provider)

        if not layer.isValid():
            raise RuntimeError(
                f"Failed to load: {path}. "
                f"Provider '{provider}' could not read this file. "
                "Check the file format and path."
            )

        # Override CRS if specified
        if crs_override:
            crs = QgsCoordinateReferenceSystem(crs_override)
            if crs.isValid():
                layer.setCrs(crs)

        QgsProject.instance().addMapLayer(layer)

        result = {
            "id": layer.id(),
            "name": layer.name(),
            "type": s.layer_type_str(layer),
            "feature_count": layer.featureCount(),
            "crs": layer.crs().authid(),
            "is_valid": layer.isValid(),
            "provider": layer.providerType(),
            "fields": [f.name() for f in layer.fields()],
            "field_count": layer.fields().count(),
        }

        # CRS warning
        if not layer.crs().isValid():
            result["warning"] = "Layer has no CRS defined — set one with set_project_crs or diagnose_crs"

        return result

    def list_supported_formats(**_):
        """List supported vector file formats for export."""
        formats = []
        for driver in QgsVectorFileWriter.supportedFiltersAndFormats():
            formats.append({
                "driver": driver.driverName,
                "filter": driver.filterString,
            })
        return {"formats": formats[:50], "total": len(formats)}

    s._HANDLERS.update({
        "export_layer": export_layer,
        "import_and_add_layer": import_and_add_layer,
        "list_supported_formats": list_supported_formats,
    })
