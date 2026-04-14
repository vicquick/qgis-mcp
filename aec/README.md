# QGIS MCP — aec-web edition

Modular QGIS MCP plugin + Docker-ready MCP server for AEC / GIS workflows on **QGIS 4.0 / Qt6**.

**Fork of** [jjsantos01/qgis_mcp](https://github.com/jjsantos01/qgis_mcp) — original plugin preserved at repo root. This directory (`aec/`) contains additions by [@vicquick](https://github.com/vicquick), built for the [aec-web](https://github.com/vicquick/aec-web) browser-accessible AEC desktop.

## What's different from upstream

| Feature | Upstream | This fork (`aec/`) |
|---|---|---|
| QGIS version | 3.x (Qt5) | **QGIS 4.0 / Qt6** |
| Plugin structure | Single file (`qgis_mcp_plugin.py`) | Modular package, 21 handler modules |
| Tools | ~15 core | **168** (project, layers, features, geoprocessing, layouts, labeling, styling, analysis, database, raster, …) |
| Database tools | No | Yes (PostGIS, GeoPackage, SpatiaLite via `db_manager`) |
| Layouts / printing | No | Full (create, add items, export PDF/image/SVG, atlas) |
| MCP transport | stdio (local) | streamable-HTTP (Docker + Traefik reverse proxy) |
| Deployment | Manual local | Docker + Coolify |
| JSON framing | Single payload | Newline-delimited (prevents socket corruption on large responses) |

## Quick install

### 1. Install the QGIS plugin

Copy `aec/plugin/` into QGIS's plugins folder, rename to `qgis_mcp_plugin`:

```bash
# Linux
cp -r aec/plugin ~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/qgis_mcp_plugin

# macOS
cp -r aec/plugin ~/Library/Application\ Support/QGIS/QGIS3/profiles/default/python/plugins/qgis_mcp_plugin

# Windows
# Copy to %APPDATA%\QGIS\QGIS3\profiles\default\python\plugins\qgis_mcp_plugin
```

In QGIS:
1. Plugins → Manage and Install Plugins → Installed
2. Enable "QGIS MCP"
3. Server auto-starts on QGIS load (port 9877 by default)
4. Or manually: Plugins → QGIS MCP → Start Server

Verify in QGIS Python Console:
```python
from qgis_mcp_plugin.plugin import QgisMCPPlugin
# Should import without errors
```

### 2. Run the MCP server (Docker)

```bash
cd aec/server
docker build -t qgis-mcp .
docker run -d --name qgis-mcp \
  -p 8081:8081 \
  -e DESKTOP_HOST=host.docker.internal \
  -e QGIS_MCP_PORT=9877 \
  qgis-mcp
```

MCP endpoint: `http://localhost:8081/mcp` (streamable-HTTP)

### 3. Connect Claude

Add to your `~/.claude.json` or MCP client config:

```json
{
  "mcpServers": {
    "qgis-mcp": {
      "type": "streamable-http",
      "url": "http://localhost:8081/mcp"
    }
  }
}
```

## Architecture

```
Claude (MCP client)
    │
    │ streamable-HTTP :8081
    ▼
Docker container: qgis-mcp
    │
    │ TCP socket :9877 (newline-delimited JSON)
    ▼
QGIS (running qgis_mcp_plugin)
    │
    │ QTimer polling (main thread)
    ▼
PyQGIS + Qt6 API calls
```

Non-blocking socket server polled by `QTimer.singleShot` (main thread) — no background threads touch QGIS project data.

## Tool categories

21 handler modules covering:

- **project** — new/load/save/info, CRS, variables
- **layers** — add (vector/raster/WMS/DB), remove, visibility, opacity, filters, temporal, duplicate, join, health checks
- **features** — add/edit/delete, select, attributes, field operations
- **geoprocessing** — buffer, clip, intersection, union, difference, dissolve, centroid, convex hull, voronoi, heatmap, merge, reproject, simplify
- **layouts** — create, add items, maps, legends, scales, arrows, tables, PDF/SVG/image export, atlas
- **labeling** — set/remove labels, rule-based, prevent overlap
- **styling** — single/categorized/graduated/rule-based symbology, color ramps, data-defined properties
- **analysis** — statistics, topology checks, spatial queries, measures
- **database** — PostGIS/GeoPackage/SpatiaLite connections, tables, SQL, db layers
- **canvas** — extent, zoom, scale, rotation, screenshots, themes, decorations
- **code** — execute arbitrary PyQGIS Python
- **raster** — info, statistics, brightness/contrast, renderer
- **export** — DXF, IDML, multiple formats
- **relations** — add/list/remove layer relations
- **bookmarks** — add/list/zoom/delete
- **history** — undo/redo
- **sketching** — annotations, memory layers
- **validation** — geometry, WKT, expressions, layer health
- **processing_tools** — run any QGIS Processing algorithm
- **settings** — get/set QGIS settings, snapping

Full tool list: see `aec/server/qgis_mcp_server.py`.

## Requirements

- QGIS 4.0+ (Qt6, PyQt6) — **not compatible with QGIS 3.x / Qt5**
- Python 3.11+ (ships with QGIS 4.0)
- Docker + Docker Compose for MCP server deployment

For QGIS 3.x, use upstream [jjsantos01/qgis_mcp](https://github.com/jjsantos01/qgis_mcp).

## Development

Plugin handlers live in `aec/plugin/handlers/`. Each module registers tools via a handler dispatch table. Adding a new handler:

1. Create `aec/plugin/handlers/my_handler.py`
2. Register in `aec/plugin/handlers/__init__.py`
3. Restart QGIS (Plugin Reloader supported)

MCP server proxy is in `aec/server/qgis_mcp_server.py` — expose each plugin tool via `FastMCP`.

## Credits

- **Upstream concept**: [jjsantos01/qgis_mcp](https://github.com/jjsantos01/qgis_mcp) — the original QGIS + MCP socket integration that made this possible. 900+ stars, 143+ forks at time of writing.
- **Additions**: [@vicquick](https://github.com/vicquick), AI-assisted with Claude Sonnet 4.6 / Opus 4.6 (Anthropic)
- **QGIS**: [QGIS.org](https://qgis.org/) — the free and open-source GIS

See [`NOTICE`](../NOTICE) and [`LICENSE.md`](../LICENSE.md) at repo root for full attribution and licensing.
