#!/usr/bin/env python3
"""
QGIS MCP Server — socket proxy to QGIS plugin (168 tools)
Connects to the QGIS MCP plugin running inside the desktop container.
"""

import os
import logging
from contextlib import asynccontextmanager
import socket
import json
from typing import AsyncIterator, Dict, Any
from mcp.server.fastmcp import FastMCP, Context

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("QgisMCPServer")

QGIS_HOST = os.environ.get("DESKTOP_HOST", "aec-web")
QGIS_PORT = int(os.environ.get("QGIS_MCP_PORT", "9877"))


class QgisMCPServer:
    def __init__(self, host=QGIS_HOST, port=QGIS_PORT):
        self.host = host
        self.port = port
        self.socket = None

    def connect(self):
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.connect((self.host, self.port))
            return True
        except Exception as e:
            logger.error(f"Error connecting to QGIS: {e}")
            return False

    def disconnect(self):
        if self.socket:
            self.socket.close()
            self.socket = None

    def send_command(self, command_type, params=None):
        """Send a newline-delimited JSON command and read the newline-delimited response."""
        if not self.socket:
            return None
        command = {"type": command_type, "params": params or {}}
        try:
            self.socket.sendall(json.dumps(command).encode('utf-8') + b'\n')
            response_data = b''
            while True:
                chunk = self.socket.recv(65536)
                if not chunk:
                    break
                response_data += chunk
                if b'\n' in response_data:
                    line = response_data.split(b'\n', 1)[0]
                    return json.loads(line.decode('utf-8'))
            if response_data.strip():
                return json.loads(response_data.strip().decode('utf-8'))
            return None
        except Exception as e:
            logger.error(f"Error sending command: {e}")
            return None


_qgis_connection = None

def get_qgis_connection():
    global _qgis_connection
    if _qgis_connection is not None:
        try:
            _qgis_connection.socket.sendall(b'')
            return _qgis_connection
        except Exception:
            try: _qgis_connection.disconnect()
            except Exception: pass
            _qgis_connection = None
    _qgis_connection = QgisMCPServer()
    if not _qgis_connection.connect():
        _qgis_connection = None
        raise Exception(f"Could not connect to QGIS at {QGIS_HOST}:{QGIS_PORT}. Start the plugin first.")
    logger.info(f"Connected to QGIS at {QGIS_HOST}:{QGIS_PORT}")
    return _qgis_connection


def cmd(command_type, params=None):
    """Send command and return JSON string."""
    return json.dumps(get_qgis_connection().send_command(command_type, params), indent=2)


@asynccontextmanager
async def server_lifespan(server: FastMCP) -> AsyncIterator[Dict[str, Any]]:
    logger.info("QGIS MCP server starting")
    try:
        get_qgis_connection()
        logger.info("Connected to QGIS on startup")
    except Exception as e:
        logger.warning(f"Could not connect on startup: {e}")
    yield {}
    global _qgis_connection
    if _qgis_connection:
        _qgis_connection.disconnect()
        _qgis_connection = None


mcp = FastMCP(
    "qgis-mcp",
    instructions="QGIS 4.0 integration through MCP — 168 tools controlling live QGIS desktop with built-in verification and geoprocessing",
    host=os.environ.get("FASTMCP_HOST", "0.0.0.0"),
    port=int(os.environ.get("FASTMCP_PORT", "8081")),
    lifespan=server_lifespan
)


# ═══════════════════════════════════════════════════════════════════
# Project Management
# ═══════════════════════════════════════════════════════════════════

@mcp.tool()
def ping(ctx: Context) -> str:
    """Check connectivity to the running QGIS instance"""
    return cmd("ping")

@mcp.tool()
def get_qgis_info(ctx: Context) -> str:
    """Get QGIS version, Qt version, plugins count, profile path"""
    return cmd("get_qgis_info")

@mcp.tool()
def get_project_info(ctx: Context) -> str:
    """Get current project info: filename, title, CRS, layer list"""
    return cmd("get_project_info")

@mcp.tool()
def load_project(ctx: Context, path: str) -> str:
    """Load a QGIS project file (.qgs/.qgz)"""
    return cmd("load_project", {"path": path})

@mcp.tool()
def create_new_project(ctx: Context, path: str) -> str:
    """Create and save a new empty project"""
    return cmd("create_new_project", {"path": path})

@mcp.tool()
def save_project(ctx: Context, path: str = None) -> str:
    """Save project (optionally to a new path)"""
    return cmd("save_project", {"path": path} if path else {})

@mcp.tool()
def get_project_variables(ctx: Context) -> str:
    """List all project variables (key/value pairs)"""
    return cmd("get_project_variables")

@mcp.tool()
def set_project_variable(ctx: Context, name: str, value: str) -> str:
    """Set a project variable"""
    return cmd("set_project_variable", {"name": name, "value": value})


# ═══════════════════════════════════════════════════════════════════
# Layers
# ═══════════════════════════════════════════════════════════════════

@mcp.tool()
def get_layers(ctx: Context) -> str:
    """List all layers with type, visibility, feature count, CRS"""
    return cmd("get_layers")

@mcp.tool()
def get_layer_info(ctx: Context, layer_id: str) -> str:
    """Detailed info for one layer: CRS, extent, provider, source, fields, renderer type"""
    return cmd("get_layer_info", {"layer_id": layer_id})

@mcp.tool()
def add_vector_layer(ctx: Context, path: str, provider: str = "ogr", name: str = None) -> str:
    """Add a vector layer (shapefile, GeoJSON, GeoPackage, etc.)"""
    p = {"path": path, "provider": provider}
    if name: p["name"] = name
    return cmd("add_vector_layer", p)

@mcp.tool()
def add_raster_layer(ctx: Context, path: str, provider: str = "gdal", name: str = None) -> str:
    """Add a raster layer (GeoTIFF, etc.)"""
    p = {"path": path, "provider": provider}
    if name: p["name"] = name
    return cmd("add_raster_layer", p)

@mcp.tool()
def add_wms_layer(ctx: Context, url: str, layers: str, name: str = None, format: str = "image/png", crs: str = "EPSG:3857") -> str:
    """Add a WMS/WMTS/XYZ tile layer by URL"""
    p = {"url": url, "layers": layers, "format": format, "crs": crs}
    if name: p["name"] = name
    return cmd("add_wms_layer", p)

@mcp.tool()
def remove_layer(ctx: Context, layer_id: str) -> str:
    """Remove a layer by its ID"""
    return cmd("remove_layer", {"layer_id": layer_id})

@mcp.tool()
def duplicate_layer(ctx: Context, layer_id: str) -> str:
    """Duplicate a layer in the project"""
    return cmd("duplicate_layer", {"layer_id": layer_id})

@mcp.tool()
def rename_layer(ctx: Context, layer_id: str, name: str) -> str:
    """Rename a layer"""
    return cmd("rename_layer", {"layer_id": layer_id, "name": name})

@mcp.tool()
def get_layer_fields(ctx: Context, layer_id: str) -> str:
    """Get field definitions: name, type, typeName, length, precision"""
    return cmd("get_layer_fields", {"layer_id": layer_id})

@mcp.tool()
def get_layer_extent(ctx: Context, layer_id: str) -> str:
    """Get bounding box extent of a layer"""
    return cmd("get_layer_extent", {"layer_id": layer_id})

@mcp.tool()
def get_layer_features(ctx: Context, layer_id: str, limit: int = 10, expression: str = None) -> str:
    """Get features with attributes + WKT geometry (with limit, optional expression filter)"""
    p = {"layer_id": layer_id, "limit": limit}
    if expression: p["expression"] = expression
    return cmd("get_layer_features", p)

@mcp.tool()
def set_layer_visibility(ctx: Context, layer_id: str, visible: bool) -> str:
    """Toggle layer visibility"""
    return cmd("set_layer_visibility", {"layer_id": layer_id, "visible": visible})

@mcp.tool()
def set_layer_opacity(ctx: Context, layer_id: str, opacity: float) -> str:
    """Set layer opacity (0.0=transparent, 1.0=opaque)"""
    return cmd("set_layer_opacity", {"layer_id": layer_id, "opacity": opacity})

@mcp.tool()
def reorder_layers(ctx: Context, layer_ids: list) -> str:
    """Reorder layers in the layer tree (first=top)"""
    return cmd("reorder_layers", {"layer_ids": layer_ids})

@mcp.tool()
def group_layers(ctx: Context, group_name: str, layer_ids: list = None) -> str:
    """Create a layer group, optionally adding layers to it"""
    p = {"group_name": group_name}
    if layer_ids: p["layer_ids"] = layer_ids
    return cmd("group_layers", p)

@mcp.tool()
def zoom_to_layer(ctx: Context, layer_id: str) -> str:
    """Zoom canvas to the extent of a layer"""
    return cmd("zoom_to_layer", {"layer_id": layer_id})


# ═══════════════════════════════════════════════════════════════════
# Features
# ═══════════════════════════════════════════════════════════════════

@mcp.tool()
def add_feature(ctx: Context, layer_id: str, attributes: dict = None, wkt: str = None) -> str:
    """Add a feature with attributes dict and/or WKT geometry"""
    p = {"layer_id": layer_id}
    if attributes: p["attributes"] = attributes
    if wkt: p["wkt"] = wkt
    return cmd("add_feature", p)

@mcp.tool()
def edit_feature(ctx: Context, layer_id: str, feature_id: int, attributes: dict = None, wkt: str = None) -> str:
    """Edit a feature's attributes and/or geometry"""
    p = {"layer_id": layer_id, "feature_id": feature_id}
    if attributes: p["attributes"] = attributes
    if wkt: p["wkt"] = wkt
    return cmd("edit_feature", p)

@mcp.tool()
def delete_features(ctx: Context, layer_id: str, feature_ids: list) -> str:
    """Delete features by their IDs"""
    return cmd("delete_features", {"layer_id": layer_id, "feature_ids": feature_ids})

@mcp.tool()
def select_by_expression(ctx: Context, layer_id: str, expression: str) -> str:
    """Select features by QGIS expression (e.g. "population" > 10000)"""
    return cmd("select_by_expression", {"layer_id": layer_id, "expression": expression})

@mcp.tool()
def select_by_location(ctx: Context, layer_id: str, intersect_layer_id: str, predicate: str = "intersects") -> str:
    """Select features by spatial relationship. predicate: intersects, contains, within, touches, crosses, equals, disjoint"""
    return cmd("select_by_location", {"layer_id": layer_id, "intersect_layer_id": intersect_layer_id, "predicate": predicate})

@mcp.tool()
def clear_selection(ctx: Context, layer_id: str) -> str:
    """Clear selection on a layer"""
    return cmd("clear_selection", {"layer_id": layer_id})

@mcp.tool()
def get_selected_features(ctx: Context, layer_id: str, limit: int = 100) -> str:
    """Get currently selected features"""
    return cmd("get_selected_features", {"layer_id": layer_id, "limit": limit})

@mcp.tool()
def set_layer_filter(ctx: Context, layer_id: str, expression: str) -> str:
    """Set a filter (subset string) on a layer. Empty string to clear."""
    return cmd("set_layer_filter", {"layer_id": layer_id, "expression": expression})

@mcp.tool()
def add_field(ctx: Context, layer_id: str, name: str, type: str = "string", length: int = 254) -> str:
    """Add a field to a vector layer. type: string, integer, double, date, datetime, boolean"""
    return cmd("add_field", {"layer_id": layer_id, "name": name, "type": type, "length": length})

@mcp.tool()
def delete_field(ctx: Context, layer_id: str, field_name: str) -> str:
    """Delete a field from a vector layer"""
    return cmd("delete_field", {"layer_id": layer_id, "name": field_name})

@mcp.tool()
def update_field_values(ctx: Context, layer_id: str, field_name: str, expression: str) -> str:
    """Update field values using a QGIS expression (field calculator)"""
    return cmd("update_field_values", {"layer_id": layer_id, "field": field_name, "expression": expression})


# ═══════════════════════════════════════════════════════════════════
# Canvas / Map Control
# ═══════════════════════════════════════════════════════════════════

@mcp.tool()
def get_canvas_info(ctx: Context) -> str:
    """Get map canvas state: extent, CRS, scale, rotation, size"""
    return cmd("get_canvas_info")

@mcp.tool()
def set_canvas_extent(ctx: Context, xmin: float, ymin: float, xmax: float, ymax: float, crs: str = None) -> str:
    """Set map extent. Coords in project CRS unless crs provided (e.g. EPSG:4326)."""
    p = {"xmin": xmin, "ymin": ymin, "xmax": xmax, "ymax": ymax}
    if crs: p["crs"] = crs
    return cmd("set_canvas_extent", p)

@mcp.tool()
def set_project_crs(ctx: Context, crs: str) -> str:
    """Set the project CRS (e.g. EPSG:25832)"""
    return cmd("set_project_crs", {"crs": crs})

@mcp.tool()
def zoom_to_extent(ctx: Context, xmin: float, ymin: float, xmax: float, ymax: float) -> str:
    """Zoom to WGS84 extent (auto-transforms to project CRS)"""
    return cmd("zoom_to_extent", {"xmin": xmin, "ymin": ymin, "xmax": xmax, "ymax": ymax})

@mcp.tool()
def zoom_in(ctx: Context, factor: float = 2.0) -> str:
    """Zoom in by factor"""
    return cmd("zoom_in", {"factor": factor})

@mcp.tool()
def zoom_out(ctx: Context, factor: float = 2.0) -> str:
    """Zoom out by factor"""
    return cmd("zoom_out", {"factor": factor})

@mcp.tool()
def zoom_to_full_extent(ctx: Context) -> str:
    """Zoom to show all layers"""
    return cmd("zoom_to_full_extent")

@mcp.tool()
def set_scale(ctx: Context, scale: float) -> str:
    """Set exact map scale (e.g. 25000 for 1:25000)"""
    return cmd("set_scale", {"scale": scale})

@mcp.tool()
def set_rotation(ctx: Context, rotation: float) -> str:
    """Set map rotation in degrees"""
    return cmd("set_rotation", {"rotation": rotation})

@mcp.tool()
def refresh_canvas(ctx: Context) -> str:
    """Force canvas refresh"""
    return cmd("refresh_canvas")

@mcp.tool()
def render_map(ctx: Context, path: str, width: int = 800, height: int = 600, extent: dict = None, crs: str = None, dpi: int = 96) -> str:
    """Render map view to image file. Optional extent {xmin,ymin,xmax,ymax}, crs, dpi."""
    p = {"path": path, "width": width, "height": height, "dpi": dpi}
    if extent: p["extent"] = extent
    if crs: p["crs"] = crs
    return cmd("render_map", p)


# ═══════════════════════════════════════════════════════════════════
# Styling
# ═══════════════════════════════════════════════════════════════════

@mcp.tool()
def set_layer_style(ctx: Context, layer_id: str, style_type: str, color: str = None, size: float = None,
                    opacity: float = None, field: str = None, categories: list = None,
                    ranges: list = None, rules: list = None) -> str:
    """Set layer symbology. style_type: 'single', 'categorized', 'graduated', 'rule_based'.
    single: color, size, opacity.
    categorized: field, categories [{value, color, label}].
    graduated: field, ranges [{lower, upper, color, label}].
    rule_based: rules [{expression, color, label}]."""
    p = {"layer_id": layer_id, "style_type": style_type}
    for k, v in {"color": color, "size": size, "opacity": opacity, "field": field,
                 "categories": categories, "ranges": ranges, "rules": rules}.items():
        if v is not None: p[k] = v
    return cmd("set_layer_style", p)

@mcp.tool()
def get_layer_style(ctx: Context, layer_id: str) -> str:
    """Get current renderer info (type, field, categories/ranges/rules)"""
    return cmd("get_layer_style", {"layer_id": layer_id})

@mcp.tool()
def set_layer_color(ctx: Context, layer_id: str, color: str) -> str:
    """Quick color change for simple symbol (hex e.g. '#ff0000')"""
    return cmd("set_layer_color", {"layer_id": layer_id, "color": color})

@mcp.tool()
def set_color_ramp(ctx: Context, layer_id: str, field: str = None,
                   color1: str = "#ffffcc", color2: str = "#006837",
                   num_classes: int = 5, method: str = "equal_interval") -> str:
    """Apply a gradient color ramp. method: equal_interval, quantile, jenks, pretty_breaks, std_dev"""
    return cmd("set_color_ramp", {"layer_id": layer_id, "field": field,
               "color1": color1, "color2": color2, "num_classes": num_classes, "method": method})

@mcp.tool()
def apply_style_from_file(ctx: Context, layer_id: str, style_file: str) -> str:
    """Apply a .qml style file to a layer"""
    return cmd("apply_style_from_file", {"layer_id": layer_id, "path": style_file})

@mcp.tool()
def save_style_to_file(ctx: Context, layer_id: str, style_file: str) -> str:
    """Save layer style to a .qml file"""
    return cmd("save_style_to_file", {"layer_id": layer_id, "path": style_file})

@mcp.tool()
def list_style_presets(ctx: Context) -> str:
    """List available styles in the QGIS style library"""
    return cmd("list_style_presets")


# ═══════════════════════════════════════════════════════════════════
# Labeling
# ═══════════════════════════════════════════════════════════════════

@mcp.tool()
def set_layer_labels(ctx: Context, layer_id: str, field: str, enabled: bool = True,
                     font_size: float = 10, color: str = "#000000",
                     buffer_enabled: bool = False, buffer_size: float = 1.0,
                     buffer_color: str = "#ffffff", placement: str = "around_point") -> str:
    """Set labels. placement: around_point, over_point, parallel, curved, horizontal, free"""
    return cmd("set_layer_labels", {
        "layer_id": layer_id, "field": field, "enabled": enabled,
        "font_size": font_size, "color": color,
        "buffer_enabled": buffer_enabled, "buffer_size": buffer_size,
        "buffer_color": buffer_color, "placement": placement
    })

@mcp.tool()
def remove_layer_labels(ctx: Context, layer_id: str) -> str:
    """Disable labels on a layer"""
    return cmd("remove_layer_labels", {"layer_id": layer_id})

@mcp.tool()
def set_data_defined_property(ctx: Context, layer_id: str, property_name: str, expression: str) -> str:
    """Set a data-defined override using an expression (e.g. property='Size', expression='\"population\"/1000')"""
    return cmd("set_data_defined_property", {"layer_id": layer_id, "property_key": property_name, "expression": expression})


# ═══════════════════════════════════════════════════════════════════
# Print Layouts
# ═══════════════════════════════════════════════════════════════════

@mcp.tool()
def list_layouts(ctx: Context) -> str:
    """List all print layouts"""
    return cmd("list_layouts")

@mcp.tool()
def create_layout(ctx: Context, name: str, width: float = 297, height: float = 210, add_map: bool = True) -> str:
    """Create a print layout (default A4 landscape). Optionally adds a full-page map."""
    return cmd("create_layout", {"name": name, "width": width, "height": height, "add_map": add_map})

@mcp.tool()
def delete_layout(ctx: Context, layout_name: str) -> str:
    """Delete a print layout"""
    return cmd("delete_layout", {"name": layout_name})

@mcp.tool()
def add_layout_item(ctx: Context, layout_name: str, item_type: str, x: float = 10, y: float = 10,
                    width: float = 50, height: float = 20, text: str = None, font_size: float = 12) -> str:
    """Add item to layout. item_type: label, legend, scalebar, map, shape, north_arrow, attribute_table"""
    p = {"layout_name": layout_name, "item_type": item_type, "x": x, "y": y,
         "width": width, "height": height, "font_size": font_size}
    if text: p["text"] = text
    return cmd("add_layout_item", p)

@mcp.tool()
def remove_layout_item(ctx: Context, layout_name: str, item_id: str) -> str:
    """Remove an item from a layout by ID"""
    return cmd("remove_layout_item", {"layout_name": layout_name, "item_id": item_id})

@mcp.tool()
def set_layout_item_property(ctx: Context, layout_name: str, item_id: str, **kwargs) -> str:
    """Set properties on a layout item (x, y, width, height, text, font_size, etc.)"""
    p = {"layout_name": layout_name, "item_id": item_id}
    p.update(kwargs)
    return cmd("set_layout_item_property", p)

@mcp.tool()
def set_atlas(ctx: Context, layout_name: str, coverage_layer_id: str, enabled: bool = True,
              filename_expression: str = None) -> str:
    """Configure atlas on a layout"""
    p = {"layout_name": layout_name, "coverage_layer_id": coverage_layer_id, "enabled": enabled}
    if filename_expression: p["filename_expression"] = filename_expression
    return cmd("set_atlas", p)

@mcp.tool()
def export_layout_pdf(ctx: Context, layout_name: str, path: str, dpi: int = 300) -> str:
    """Export layout to PDF"""
    return cmd("export_layout_pdf", {"layout_name": layout_name, "path": path, "dpi": dpi})

@mcp.tool()
def export_layout_image(ctx: Context, layout_name: str, path: str, dpi: int = 150) -> str:
    """Export layout to image (PNG/JPEG)"""
    return cmd("export_layout_image", {"layout_name": layout_name, "path": path, "dpi": dpi})

@mcp.tool()
def export_atlas(ctx: Context, layout_name: str, output_dir: str, format: str = "pdf", dpi: int = 300) -> str:
    """Export all atlas pages (pdf or image per page)"""
    return cmd("export_atlas", {"layout_name": layout_name, "output_dir": output_dir, "format": format, "dpi": dpi})


# ═══════════════════════════════════════════════════════════════════
# Database
# ═══════════════════════════════════════════════════════════════════

@mcp.tool()
def list_db_connections(ctx: Context) -> str:
    """List configured database connections"""
    return cmd("list_db_connections")

@mcp.tool()
def add_db_layer(ctx: Context, connection_name: str, schema: str, table: str,
                 geometry_column: str = "geom", provider: str = "postgres", name: str = None) -> str:
    """Add a layer from a database connection"""
    p = {"connection_name": connection_name, "schema": schema, "table": table,
         "geometry_column": geometry_column, "provider": provider}
    if name: p["name"] = name
    return cmd("add_db_layer", p)

@mcp.tool()
def list_db_tables(ctx: Context, connection_name: str, schema: str = "public") -> str:
    """List tables in a database connection"""
    return cmd("list_db_tables", {"connection_name": connection_name, "schema": schema})

@mcp.tool()
def execute_sql(ctx: Context, connection_name: str, sql: str) -> str:
    """Execute SQL on a database connection and return results"""
    return cmd("execute_sql", {"connection_name": connection_name, "sql": sql})


# ═══════════════════════════════════════════════════════════════════
# Processing
# ═══════════════════════════════════════════════════════════════════

@mcp.tool()
def list_processing_providers(ctx: Context) -> str:
    """List processing providers (QGIS native, GDAL, GRASS, etc.)"""
    return cmd("list_processing_providers")

@mcp.tool()
def list_algorithms(ctx: Context, provider: str = None, keyword: str = None) -> str:
    """List processing algorithms, optionally filtered by provider or keyword"""
    p = {}
    if provider: p["provider"] = provider
    if keyword: p["keyword"] = keyword
    return cmd("list_algorithms", p)

@mcp.tool()
def algorithm_help(ctx: Context, algorithm: str) -> str:
    """Get description and parameters for a processing algorithm"""
    return cmd("algorithm_help", {"algorithm": algorithm})

@mcp.tool()
def execute_processing(ctx: Context, algorithm: str, parameters: dict) -> str:
    """Run a processing algorithm (e.g. native:buffer, gdal:warp)"""
    return cmd("execute_processing", {"algorithm": algorithm, "parameters": parameters})


# ═══════════════════════════════════════════════════════════════════
# Analysis
# ═══════════════════════════════════════════════════════════════════

@mcp.tool()
def calculate_statistics(ctx: Context, layer_id: str, field_name: str) -> str:
    """Field statistics: min, max, mean, median, stdev, sum, count, unique"""
    return cmd("calculate_statistics", {"layer_id": layer_id, "field": field_name})

@mcp.tool()
def spatial_query(ctx: Context, input_layer_id: str, overlay_layer_id: str, predicate: str = "intersects") -> str:
    """Spatial query: find features matching a spatial relationship"""
    return cmd("spatial_query", {"layer_id": input_layer_id, "intersect_layer_id": overlay_layer_id, "predicate": predicate})

@mcp.tool()
def measure_geometry(ctx: Context, layer_id: str, limit: int = 100) -> str:
    """Measure area/perimeter/length of features"""
    return cmd("measure_geometry", {"layer_id": layer_id, "limit": limit})

@mcp.tool()
def count_features(ctx: Context, layer_id: str, expression: str = None) -> str:
    """Count features, optionally filtered by expression"""
    p = {"layer_id": layer_id}
    if expression: p["expression"] = expression
    return cmd("count_features", p)


# ═══════════════════════════════════════════════════════════════════
# Bookmarks
# ═══════════════════════════════════════════════════════════════════

@mcp.tool()
def list_bookmarks(ctx: Context) -> str:
    """List spatial bookmarks"""
    return cmd("list_bookmarks")

@mcp.tool()
def add_bookmark(ctx: Context, name: str, xmin: float, ymin: float, xmax: float, ymax: float, crs: str = None) -> str:
    """Create a spatial bookmark from extent"""
    p = {"name": name, "xmin": xmin, "ymin": ymin, "xmax": xmax, "ymax": ymax}
    if crs: p["crs"] = crs
    return cmd("add_bookmark", p)

@mcp.tool()
def zoom_to_bookmark(ctx: Context, name: str) -> str:
    """Navigate to a bookmark"""
    return cmd("zoom_to_bookmark", {"name": name})

@mcp.tool()
def delete_bookmark(ctx: Context, bookmark_id: str) -> str:
    """Delete a bookmark by ID"""
    return cmd("delete_bookmark", {"bookmark_id": bookmark_id})


# ═══════════════════════════════════════════════════════════════════
# Sketching / Annotations
# ═══════════════════════════════════════════════════════════════════

@mcp.tool()
def add_annotation(ctx: Context, annotation_type: str, x: float, y: float, text: str = None, crs: str = None) -> str:
    """Add annotation. annotation_type: text, marker, line, polygon"""
    p = {"annotation_type": annotation_type, "x": x, "y": y}
    if text: p["text"] = text
    if crs: p["crs"] = crs
    return cmd("add_annotation", p)

@mcp.tool()
def list_annotations(ctx: Context) -> str:
    """List annotations on the map"""
    return cmd("list_annotations")

@mcp.tool()
def clear_annotations(ctx: Context) -> str:
    """Remove all annotations"""
    return cmd("clear_annotations")

@mcp.tool()
def add_map_decoration(ctx: Context, decoration: str, **kwargs) -> str:
    """Add decoration: grid, north_arrow, scale_bar"""
    p = {"decoration": decoration}
    p.update(kwargs)
    return cmd("add_map_decoration", p)


# ═══════════════════════════════════════════════════════════════════
# History (Undo/Redo)
# ═══════════════════════════════════════════════════════════════════

@mcp.tool()
def undo(ctx: Context, layer_id: str) -> str:
    """Undo last edit operation on a layer"""
    return cmd("undo", {"layer_id": layer_id})

@mcp.tool()
def redo(ctx: Context, layer_id: str) -> str:
    """Redo last undone operation on a layer"""
    return cmd("redo", {"layer_id": layer_id})

@mcp.tool()
def get_undo_stack(ctx: Context, layer_id: str) -> str:
    """List undo/redo stack for a layer"""
    return cmd("get_undo_stack", {"layer_id": layer_id})


# ═══════════════════════════════════════════════════════════════════
# Settings
# ═══════════════════════════════════════════════════════════════════

@mcp.tool()
def get_snapping_config(ctx: Context) -> str:
    """Get current snapping settings"""
    return cmd("get_snapping_config")

@mcp.tool()
def set_snapping_config(ctx: Context, enabled: bool = True, type: str = "vertex", tolerance: float = 12, unit: str = "pixels") -> str:
    """Configure snapping. type: vertex, segment, vertex_and_segment. unit: pixels, map_units"""
    return cmd("set_snapping_config", {"enabled": enabled, "type": type, "tolerance": tolerance, "unit": unit})

@mcp.tool()
def get_settings(ctx: Context, key: str) -> str:
    """Read a QGIS setting by key"""
    return cmd("get_settings", {"key": key})

@mcp.tool()
def set_settings(ctx: Context, key: str, value: str) -> str:
    """Write a QGIS setting"""
    return cmd("set_settings", {"key": key, "value": value})


# ═══════════════════════════════════════════════════════════════════
# Code Execution
# ═══════════════════════════════════════════════════════════════════

@mcp.tool()
def execute_code(ctx: Context, code: str) -> str:
    """Execute arbitrary PyQGIS code. Namespace includes ~150 QGIS/Qt classes — no imports needed.
    Available: QgsProject, QgsVectorLayer, QgsRasterLayer, QgsGeometry, QgsFeature,
    QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsRectangle, QgsPointXY,
    QgsMapSettings, QgsSymbol, QgsMarkerSymbol, QgsLineSymbol, QgsFillSymbol,
    QgsPrintLayout, QgsLayoutExporter, QgsLayoutItemMap, QgsPalLayerSettings,
    QgsTextFormat, QgsProperty, QgsExpression, processing, iface, canvas, and many more."""
    return cmd("execute_code", {"code": code})


# ═══════════════════════════════════════════════════════════════════
# Map Themes
# ═══════════════════════════════════════════════════════════════════

@mcp.tool()
def list_map_themes(ctx: Context) -> str:
    """List all map themes (visibility presets)"""
    return cmd("list_map_themes")

@mcp.tool()
def apply_map_theme(ctx: Context, theme_name: str) -> str:
    """Apply a map theme (restores layer visibility + styles)"""
    return cmd("apply_map_theme", {"name": theme_name})

@mcp.tool()
def create_map_theme(ctx: Context, theme_name: str) -> str:
    """Save current layer visibility and styles as a named map theme"""
    return cmd("create_map_theme", {"name": theme_name})

@mcp.tool()
def delete_map_theme(ctx: Context, theme_name: str) -> str:
    """Delete a map theme"""
    return cmd("delete_map_theme", {"name": theme_name})


# ═══════════════════════════════════════════════════════════════════
# Relations & Joins
# ═══════════════════════════════════════════════════════════════════

@mcp.tool()
def list_relations(ctx: Context) -> str:
    """List project relations"""
    return cmd("list_relations")

@mcp.tool()
def add_relation(ctx: Context, name: str, parent_layer_id: str, child_layer_id: str,
                 parent_field: str, child_field: str) -> str:
    """Create a relation between two layers (child has the foreign key)"""
    return cmd("add_relation", {"name": name, "referenced_layer_id": parent_layer_id,
               "referencing_layer_id": child_layer_id, "referenced_field": parent_field,
               "referencing_field": child_field})

@mcp.tool()
def remove_relation(ctx: Context, relation_id: str) -> str:
    """Delete a relation"""
    return cmd("remove_relation", {"relation_id": relation_id})

@mcp.tool()
def list_layer_joins(ctx: Context, layer_id: str) -> str:
    """List joins on a vector layer"""
    return cmd("list_layer_joins", {"layer_id": layer_id})

@mcp.tool()
def add_layer_join(ctx: Context, layer_id: str, join_layer_id: str, join_field: str, target_field: str,
                   prefix: str = None) -> str:
    """Join two layers by field"""
    p = {"layer_id": layer_id, "join_layer_id": join_layer_id, "join_field": join_field, "target_field": target_field}
    if prefix: p["prefix"] = prefix
    return cmd("add_layer_join", p)

@mcp.tool()
def remove_layer_join(ctx: Context, layer_id: str, join_layer_id: str) -> str:
    """Remove a join from a layer"""
    return cmd("remove_layer_join", {"layer_id": layer_id, "join_layer_id": join_layer_id})


# ═══════════════════════════════════════════════════════════════════
# Raster Operations
# ═══════════════════════════════════════════════════════════════════

@mcp.tool()
def get_raster_info(ctx: Context, layer_id: str) -> str:
    """Get raster layer info: band count, data type, statistics, nodata, pixel size"""
    return cmd("get_raster_info", {"layer_id": layer_id})

@mcp.tool()
def set_raster_renderer(ctx: Context, layer_id: str, renderer_type: str, **kwargs) -> str:
    """Set raster renderer. renderer_type: singleband_gray, singleband_pseudocolor, multiband, hillshade.
    pseudocolor: color_ramp, min, max. multiband: red_band, green_band, blue_band. hillshade: altitude, azimuth, z_factor"""
    p = {"layer_id": layer_id, "renderer_type": renderer_type}
    p.update(kwargs)
    return cmd("set_raster_renderer", p)

@mcp.tool()
def set_raster_brightness_contrast(ctx: Context, layer_id: str, brightness: int = 0, contrast: int = 0) -> str:
    """Set raster brightness (-255 to 255) and contrast (-100 to 100)"""
    return cmd("set_raster_brightness_contrast", {"layer_id": layer_id, "brightness": brightness, "contrast": contrast})

@mcp.tool()
def get_raster_statistics(ctx: Context, layer_id: str, band: int = 1) -> str:
    """Get statistics for a raster band (min, max, mean, stdev)"""
    return cmd("get_raster_statistics", {"layer_id": layer_id, "band": band})


# ═══════════════════════════════════════════════════════════════════
# Temporal
# ═══════════════════════════════════════════════════════════════════

@mcp.tool()
def set_layer_temporal(ctx: Context, layer_id: str, enabled: bool = True, field: str = None,
                       mode: str = "SingleField", start_field: str = None, end_field: str = None) -> str:
    """Enable temporal filtering. mode: FixedRange, SingleField, DualField"""
    p = {"layer_id": layer_id, "enabled": enabled, "mode": mode}
    if field: p["field"] = field
    if start_field: p["start_field"] = start_field
    if end_field: p["end_field"] = end_field
    return cmd("set_layer_temporal", p)

@mcp.tool()
def set_temporal_range(ctx: Context, start: str, end: str) -> str:
    """Set project temporal range (ISO datetime strings)"""
    return cmd("set_temporal_range", {"start": start, "end": end})


# ═══════════════════════════════════════════════════════════════════
# Layer Extras (map tips, actions, notes)
# ═══════════════════════════════════════════════════════════════════

@mcp.tool()
def set_map_tip(ctx: Context, layer_id: str, html_template: str) -> str:
    """Set HTML map tip template (e.g. '<b>[% \"name\" %]</b>')"""
    return cmd("set_map_tip", {"layer_id": layer_id, "html_template": html_template})

@mcp.tool()
def get_map_tip(ctx: Context, layer_id: str) -> str:
    """Get current map tip template for a layer"""
    return cmd("get_map_tip", {"layer_id": layer_id})

@mcp.tool()
def add_layer_action(ctx: Context, layer_id: str, name: str, action_text: str,
                     action_type: str = "Generic") -> str:
    """Add an action to a layer. action_type: Generic, Python, OpenURL"""
    return cmd("add_layer_action", {"layer_id": layer_id, "name": name,
               "action_text": action_text, "action_type": action_type})

@mcp.tool()
def list_layer_actions(ctx: Context, layer_id: str) -> str:
    """List actions configured on a layer"""
    return cmd("list_layer_actions", {"layer_id": layer_id})

@mcp.tool()
def remove_layer_action(ctx: Context, layer_id: str, action_index: int) -> str:
    """Remove a layer action by index"""
    return cmd("remove_layer_action", {"layer_id": layer_id, "index": action_index})

@mcp.tool()
def set_layer_note(ctx: Context, layer_id: str, note_html: str) -> str:
    """Set a layer note (HTML)"""
    return cmd("set_layer_note", {"layer_id": layer_id, "note_html": note_html})

@mcp.tool()
def get_layer_note(ctx: Context, layer_id: str) -> str:
    """Get layer note"""
    return cmd("get_layer_note", {"layer_id": layer_id})

@mcp.tool()
def get_mesh_info(ctx: Context, layer_id: str) -> str:
    """Get mesh layer info (dataset groups, timesteps)"""
    return cmd("get_mesh_info", {"layer_id": layer_id})

@mcp.tool()
def get_point_cloud_info(ctx: Context, layer_id: str) -> str:
    """Get point cloud layer info (point count, attributes, CRS)"""
    return cmd("get_point_cloud_info", {"layer_id": layer_id})


# ═══════════════════════════════════════════════════════════════════
# Layout Extras (DD overrides, multi-page, overview, themes, SVG, DXF)
# ═══════════════════════════════════════════════════════════════════

@mcp.tool()
def set_layout_item_dd_property(ctx: Context, layout_name: str, item_id: str,
                                property_name: str, expression: str) -> str:
    """Set data-defined override on a layout item (e.g. MapScale, MapRotation, Text, ItemWidth)"""
    return cmd("set_layout_item_dd_property", {"layout_name": layout_name, "item_id": item_id,
               "property_name": property_name, "expression": expression})

@mcp.tool()
def add_layout_page(ctx: Context, layout_name: str, width: float = None, height: float = None) -> str:
    """Add a page to a print layout"""
    p = {"layout_name": layout_name}
    if width: p["width"] = width
    if height: p["height"] = height
    return cmd("add_layout_page", p)

@mcp.tool()
def set_map_overview(ctx: Context, layout_name: str, map_item_id: str,
                     overview_map_item_id: str, frame_color: str = "#ff0000") -> str:
    """Add an overview frame to a map item"""
    return cmd("set_map_overview", {"layout_name": layout_name, "map_item_id": map_item_id,
               "overview_map_item_id": overview_map_item_id, "frame_color": frame_color})

@mcp.tool()
def set_map_theme_for_item(ctx: Context, layout_name: str, item_id: str, theme_name: str) -> str:
    """Set which map theme a layout map item uses"""
    return cmd("set_map_theme_for_item", {"layout_name": layout_name, "item_id": item_id, "theme_name": theme_name})

@mcp.tool()
def export_layout_svg(ctx: Context, layout_name: str, path: str, dpi: int = 300) -> str:
    """Export a print layout to SVG"""
    return cmd("export_layout_svg", {"layout_name": layout_name, "path": path, "dpi": dpi})

@mcp.tool()
def import_idml(ctx: Context, path: str, layout_name: str = None, add_map: bool = True, unit: str = "points") -> str:
    """Parse an InDesign IDML file and recreate it as a QGIS print layout.
    Extracts page size, text frames, rectangles, images, ovals.
    Upload .idml to /data/ first. unit: 'points' (zero-loss, default) or 'mm'.
    Returns summary of created items with IDs for data-defined overrides."""
    p = {"path": path, "add_map": add_map, "unit": unit}
    if layout_name: p["layout_name"] = layout_name
    return cmd("import_idml", p)

@mcp.tool()
def export_dxf(ctx: Context, path: str, layer_ids: list = None, crs: str = None) -> str:
    """Export project layers to DXF file"""
    p = {"path": path}
    if layer_ids: p["layer_ids"] = layer_ids
    if crs: p["crs"] = crs
    return cmd("export_dxf", p)


# ═══════════════════════════════════════════════════════════════════
# Database Extras
# ═══════════════════════════════════════════════════════════════════

@mcp.tool()
def get_db_table_info(ctx: Context, connection_name: str, schema: str, table: str) -> str:
    """Get table columns, types, geometry column, geometry type, SRID, row count"""
    return cmd("get_db_table_info", {"connection_name": connection_name, "schema": schema, "table": table})


# ═══════════════════════════════════════════════════════════════════
# Rule-Based Labeling
# ═══════════════════════════════════════════════════════════════════

@mcp.tool()
def set_rule_based_labels(ctx: Context, layer_id: str, rules: list) -> str:
    """Set rule-based labeling. rules: [{expression, field, font_size, color, label, min_scale, max_scale}]"""
    return cmd("set_rule_based_labels", {"layer_id": layer_id, "rules": rules})


# ═══════════════════════════════════════════════════════════════════
# Form Configuration
# ═══════════════════════════════════════════════════════════════════

@mcp.tool()
def set_form_config(ctx: Context, layer_id: str, layout_type: str = "auto", suppress_on_add: bool = False) -> str:
    """Set attribute form layout type: auto, drag_and_drop, custom"""
    return cmd("set_form_config", {"layer_id": layer_id, "layout_type": layout_type, "suppress_on_add": suppress_on_add})

@mcp.tool()
def set_field_widget(ctx: Context, layer_id: str, field_name: str, widget_type: str, config: dict = None) -> str:
    """Set edit widget for a field. widget_type: TextEdit, Range, DateTime, ValueMap, CheckBox, UniqueValues"""
    p = {"layer_id": layer_id, "field_name": field_name, "widget_type": widget_type}
    if config: p["config"] = config
    return cmd("set_field_widget", p)


# ═══════════════════════════════════════════════════════════════════
# Plugin Management
# ═══════════════════════════════════════════════════════════════════

@mcp.tool()
def list_plugins(ctx: Context) -> str:
    """List installed QGIS plugins with enabled/disabled status"""
    return cmd("list_plugins")

@mcp.tool()
def enable_plugin(ctx: Context, plugin_name: str) -> str:
    """Enable a QGIS plugin"""
    return cmd("enable_plugin", {"name": plugin_name})

@mcp.tool()
def disable_plugin(ctx: Context, plugin_name: str) -> str:
    """Disable a QGIS plugin"""
    return cmd("disable_plugin", {"name": plugin_name})


# ═══════════════════════════════════════════════════════════════════
# Validation & Verification
# ═══════════════════════════════════════════════════════════════════

@mcp.tool()
def validate_geometry(ctx: Context, layer_id: str, limit: int = 100,
                      fix: bool = False, method: str = "structure") -> str:
    """Validate geometries in a vector layer. Reports invalid features with error details.
    method: 'structure' (GEOS) or 'qgis' (OGC rules). fix=True attempts makeValid().
    ALWAYS run this after bulk geometry operations to ensure data integrity."""
    return cmd("validate_geometry", {
        "layer_id": layer_id, "limit": limit, "fix": fix, "method": method
    })

@mcp.tool()
def validate_wkt(ctx: Context, wkt: str, expected_type: str = None) -> str:
    """Validate a WKT geometry string BEFORE using it in add_feature/edit_feature.
    Returns validity, type, vertex count, bounding box.
    expected_type: 'point', 'line', 'polygon' to check type matches the target layer."""
    p = {"wkt": wkt}
    if expected_type: p["expected_type"] = expected_type
    return cmd("validate_wkt", p)

@mcp.tool()
def check_layer_health(ctx: Context, layer_id: str) -> str:
    """Comprehensive health check for a layer: data source, CRS, fields, renderer,
    editing state, spatial index, feature count. Run this to diagnose layer problems."""
    return cmd("check_layer_health", {"layer_id": layer_id})

@mcp.tool()
def verify_project(ctx: Context) -> str:
    """Full project health check. Validates ALL layers, CRS consistency, relations,
    and unsaved changes. Run this periodically or after major operations."""
    return cmd("verify_project")

@mcp.tool()
def diagnose_crs(ctx: Context, crs_string: str = None, layer_id: str = None) -> str:
    """Diagnose a CRS: validity, units, bounds, description, proj4, compatibility with project.
    Pass either a CRS string (e.g. 'EPSG:4326') or a layer_id."""
    p = {}
    if crs_string: p["crs_string"] = crs_string
    if layer_id: p["layer_id"] = layer_id
    return cmd("diagnose_crs", p)

@mcp.tool()
def validate_expression(ctx: Context, expression: str, layer_id: str = None) -> str:
    """Validate a QGIS expression BEFORE using it. Checks syntax, referenced columns/functions.
    If layer_id provided, checks field references exist in the layer.
    ALWAYS validate complex expressions before select_by_expression/update_field_values."""
    p = {"expression": expression}
    if layer_id: p["layer_id"] = layer_id
    return cmd("validate_expression", p)

@mcp.tool()
def check_data_integrity(ctx: Context, layer_id: str, checks: list = None, limit: int = 1000) -> str:
    """Run data integrity checks on a vector layer.
    checks: ['nulls', 'duplicates', 'empty_geometries', 'type_consistency', 'extent_outliers'].
    Default: all checks. Returns detailed report of issues found."""
    p = {"layer_id": layer_id, "limit": limit}
    if checks: p["checks"] = checks
    return cmd("check_data_integrity", p)

@mcp.tool()
def check_topology(ctx: Context, layer_id: str, checks: list = None) -> str:
    """Run topology validation using QGIS processing algorithms.
    Checks geometry validity using GEOS rules. Returns valid/invalid counts and error details."""
    p = {"layer_id": layer_id}
    if checks: p["checks"] = checks
    return cmd("check_topology", p)

@mcp.tool()
def verify_operation(ctx: Context, layer_id: str, operation: str,
                     expected_count: int = None, feature_id: int = None,
                     field_name: str = None) -> str:
    """Verify the result of a previous operation. ALWAYS call after mutating operations.
    operation: 'feature_added', 'feature_deleted', 'feature_edited',
    'field_added', 'field_deleted', 'filter_applied', 'style_applied', 'label_applied'.
    Pass feature_id/expected_count/field_name as relevant."""
    p = {"layer_id": layer_id, "operation": operation}
    if expected_count is not None: p["expected_count"] = expected_count
    if feature_id is not None: p["feature_id"] = feature_id
    if field_name: p["field_name"] = field_name
    return cmd("verify_operation", p)

@mcp.tool()
def layer_diff(ctx: Context, layer_id: str, field_name: str = None) -> str:
    """Get a snapshot of the current layer state: feature count, fields, extent, CRS.
    Optionally includes value distribution for a field. Useful for before/after comparison."""
    p = {"layer_id": layer_id}
    if field_name: p["field_name"] = field_name
    return cmd("layer_diff", p)

@mcp.tool()
def measure_geodesic(ctx: Context, layer_id: str, feature_ids: list = None, limit: int = 100) -> str:
    """Measure features using geodesic (ellipsoidal) calculations — accurate real-world
    measurements in meters/sq meters regardless of CRS. Unlike measure_geometry which
    uses planar CRS units. Returns area_m2, area_ha, area_km2 or length_m, length_km."""
    p = {"layer_id": layer_id, "limit": limit}
    if feature_ids: p["feature_ids"] = feature_ids
    return cmd("measure_geodesic", p)

@mcp.tool()
def transform_coordinates(ctx: Context, x: float, y: float,
                          source_crs: str, target_crs: str) -> str:
    """Transform coordinates between CRS. Also computes round-trip error to verify accuracy.
    Useful for verifying coordinate values are in the expected CRS."""
    return cmd("transform_coordinates", {
        "x": x, "y": y, "source_crs": source_crs, "target_crs": target_crs
    })


# ═══════════════════════════════════════════════════════════════════
# Layer Search & Memory Layers
# ═══════════════════════════════════════════════════════════════════

@mcp.tool()
def find_layer(ctx: Context, pattern: str) -> str:
    """Search for layers by name using wildcards (e.g. '*roads*', 'building_*').
    Returns matching layer IDs. Use this instead of scanning get_layers output."""
    return cmd("find_layer", {"pattern": pattern})

@mcp.tool()
def create_memory_layer(ctx: Context, name: str, geometry_type: str = "Point",
                        crs: str = "EPSG:4326", fields: list = None) -> str:
    """Create an in-memory scratch layer for intermediate results.
    geometry_type: Point, LineString, Polygon, MultiPoint, MultiLineString, MultiPolygon, None.
    fields: [{name, type}] where type: String, Integer, Double, Date."""
    p = {"name": name, "geometry_type": geometry_type, "crs": crs}
    if fields: p["fields"] = fields
    return cmd("create_memory_layer", p)


# ═══════════════════════════════════════════════════════════════════
# Canvas Extras (screenshot, message log)
# ═══════════════════════════════════════════════════════════════════

@mcp.tool()
def get_canvas_screenshot(ctx: Context, path: str) -> str:
    """Fast canvas screenshot (QWidget.grab) — much faster than render_map.
    Captures canvas as-is including decorations and selections. No re-render."""
    return cmd("get_canvas_screenshot", {"path": path})

@mcp.tool()
def get_message_log(ctx: Context, level: str = None, tag: str = None, limit: int = 50) -> str:
    """Get QGIS message log entries for debugging"""
    p = {"limit": limit}
    if level: p["level"] = level
    if tag: p["tag"] = tag
    return cmd("get_message_log", p)


# ═══════════════════════════════════════════════════════════════════
# Export & File I/O
# ═══════════════════════════════════════════════════════════════════

@mcp.tool()
def export_layer(ctx: Context, layer_id: str, path: str, format: str = "GPKG",
                 crs: str = None, selected_only: bool = False) -> str:
    """Export a vector layer to a file. format: GPKG, GeoJSON, 'ESRI Shapefile', CSV, KML, DXF.
    crs: target CRS for reprojection. selected_only: export only selected features.
    Verifies export by checking output file and feature count."""
    p = {"layer_id": layer_id, "path": path, "format": format, "selected_only": selected_only}
    if crs: p["crs"] = crs
    return cmd("export_layer", p)

@mcp.tool()
def import_and_add_layer(ctx: Context, path: str, name: str = None,
                         provider: str = "ogr", crs_override: str = None) -> str:
    """Import a data file and add to project. Auto-detects format.
    Supports: GeoPackage, Shapefile, GeoJSON, CSV, KML, GML, DXF, GPX.
    Returns full layer info with validation status."""
    p = {"path": path, "provider": provider}
    if name: p["name"] = name
    if crs_override: p["crs_override"] = crs_override
    return cmd("import_and_add_layer", p)

@mcp.tool()
def list_supported_formats(ctx: Context) -> str:
    """List all supported vector file formats for export"""
    return cmd("list_supported_formats")


# ═══════════════════════════════════════════════════════════════════
# Geoprocessing (common spatial operations with verification)
# ═══════════════════════════════════════════════════════════════════

@mcp.tool()
def buffer(ctx: Context, layer_id: str, distance: float, segments: int = 8,
           dissolve: bool = False, name: str = None) -> str:
    """Create buffer zones. distance in CRS units (negative for inward on polygons).
    dissolve=True merges all buffers. Output auto-added to project with verification."""
    p = {"layer_id": layer_id, "distance": distance, "segments": segments, "dissolve": dissolve}
    if name: p["name"] = name
    return cmd("buffer", p)

@mcp.tool()
def clip(ctx: Context, input_layer_id: str, overlay_layer_id: str, name: str = None) -> str:
    """Clip input layer using overlay as cookie cutter. Keeps only overlapping parts."""
    p = {"input_layer_id": input_layer_id, "overlay_layer_id": overlay_layer_id}
    if name: p["name"] = name
    return cmd("clip", p)

@mcp.tool()
def intersection(ctx: Context, input_layer_id: str, overlay_layer_id: str, name: str = None) -> str:
    """Geometric intersection of two layers. Output has attributes from both."""
    p = {"input_layer_id": input_layer_id, "overlay_layer_id": overlay_layer_id}
    if name: p["name"] = name
    return cmd("intersection", p)

@mcp.tool()
def union(ctx: Context, input_layer_id: str, overlay_layer_id: str = None, name: str = None) -> str:
    """Union of two layers. Combines all features. If no overlay, dissolves input."""
    p = {"input_layer_id": input_layer_id}
    if overlay_layer_id: p["overlay_layer_id"] = overlay_layer_id
    if name: p["name"] = name
    return cmd("union", p)

@mcp.tool()
def dissolve(ctx: Context, layer_id: str, field: str = None, name: str = None) -> str:
    """Dissolve/merge features. field: group by field (same values merge). Omit to merge all."""
    p = {"layer_id": layer_id}
    if field: p["field"] = field
    if name: p["name"] = name
    return cmd("dissolve", p)

@mcp.tool()
def difference(ctx: Context, input_layer_id: str, overlay_layer_id: str, name: str = None) -> str:
    """Erase: subtract overlay from input. Keeps non-overlapping parts of input."""
    p = {"input_layer_id": input_layer_id, "overlay_layer_id": overlay_layer_id}
    if name: p["name"] = name
    return cmd("difference", p)

@mcp.tool()
def centroid(ctx: Context, layer_id: str, name: str = None) -> str:
    """Create point layer from polygon/line centroids"""
    p = {"layer_id": layer_id}
    if name: p["name"] = name
    return cmd("centroid", p)

@mcp.tool()
def convex_hull(ctx: Context, layer_id: str, name: str = None) -> str:
    """Create convex hull polygon for each feature"""
    p = {"layer_id": layer_id}
    if name: p["name"] = name
    return cmd("convex_hull", p)

@mcp.tool()
def voronoi(ctx: Context, layer_id: str, buffer_pct: float = 0.0, name: str = None) -> str:
    """Create Voronoi polygons from a point layer"""
    p = {"layer_id": layer_id, "buffer_pct": buffer_pct}
    if name: p["name"] = name
    return cmd("voronoi", p)

@mcp.tool()
def simplify(ctx: Context, layer_id: str, tolerance: float = 1.0,
             method: str = "douglas_peucker", name: str = None) -> str:
    """Simplify geometries. method: douglas_peucker, visvalingam, snap_to_grid.
    tolerance in CRS units."""
    p = {"layer_id": layer_id, "tolerance": tolerance, "method": method}
    if name: p["name"] = name
    return cmd("simplify", p)

@mcp.tool()
def reproject(ctx: Context, layer_id: str, target_crs: str, name: str = None) -> str:
    """Reproject layer to a different CRS. Creates a new layer."""
    p = {"layer_id": layer_id, "target_crs": target_crs}
    if name: p["name"] = name
    return cmd("reproject", p)

@mcp.tool()
def merge_layers(ctx: Context, layer_ids: list, name: str = "merged") -> str:
    """Merge multiple vector layers into one"""
    return cmd("merge_layers", {"layer_ids": layer_ids, "name": name})

@mcp.tool()
def join_by_location(ctx: Context, input_layer_id: str, join_layer_id: str,
                     predicate: str = "intersects", join_type: str = "one_to_many",
                     name: str = None) -> str:
    """Spatial join: attach attributes from join_layer based on spatial relationship.
    predicate: intersects, contains, within, crosses, touches, overlaps.
    join_type: one_to_many or one_to_one."""
    p = {"input_layer_id": input_layer_id, "join_layer_id": join_layer_id,
         "predicate": predicate, "join_type": join_type}
    if name: p["name"] = name
    return cmd("join_by_location", p)

@mcp.tool()
def create_grid(ctx: Context, extent: dict, grid_type: str = "rectangle",
                h_spacing: float = 1000, v_spacing: float = 1000,
                crs: str = None, name: str = "grid") -> str:
    """Create a grid layer. grid_type: point, line, rectangle, diamond, hexagon.
    extent: {xmin, ymin, xmax, ymax}. spacing in CRS units."""
    p = {"extent": extent, "grid_type": grid_type, "h_spacing": h_spacing,
         "v_spacing": v_spacing, "name": name}
    if crs: p["crs"] = crs
    return cmd("create_grid", p)

@mcp.tool()
def random_points(ctx: Context, count: int = 100, extent: dict = None,
                  layer_id: str = None, min_distance: float = 0,
                  name: str = "random_points") -> str:
    """Generate random points in an extent or polygon layer.
    Either extent {xmin,ymin,xmax,ymax} or layer_id (polygon) required."""
    p = {"count": count, "min_distance": min_distance, "name": name}
    if extent: p["extent"] = extent
    if layer_id: p["layer_id"] = layer_id
    return cmd("random_points", p)

@mcp.tool()
def heatmap(ctx: Context, layer_id: str, radius: float = 100, pixel_size: float = 10,
            weight_field: str = None, name: str = None, path: str = None) -> str:
    """Generate a heatmap (kernel density) raster from a point layer.
    radius: search radius in map units. pixel_size: output pixel size."""
    p = {"layer_id": layer_id, "radius": radius, "pixel_size": pixel_size}
    if weight_field: p["weight_field"] = weight_field
    if name: p["name"] = name
    if path: p["path"] = path
    return cmd("heatmap", p)


def main():
    transport = os.environ.get("MCP_TRANSPORT", "stdio")
    mcp.run(transport=transport)

if __name__ == "__main__":
    main()
