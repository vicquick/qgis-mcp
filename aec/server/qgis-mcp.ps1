# qgis-mcp: QGIS MCP server. HTTP :8081 <-> QGIS plugin TCP :9877.
# QGIS must be running with QGIS-MCP plugin Started.
#
# Runs in a self-bootstrapping venv: the server moved from the mcp SDK's
# bundled FastMCP to standalone fastmcp 3.x, which must not be installed into
# system Python (QGIS and other tools share it).

param(
    [string]$LogPath = "$env:LOCALAPPDATA\bridge-win\logs\qgis-mcp.log"
)

$qgisHome     = "$env:USERPROFILE\.local\share\qgis-mcp"
$serverScript = "$qgisHome\qgis_mcp_server.py"
$venv         = "$qgisHome\.venv"
if (-not (Test-Path $serverScript)) {
    throw "qgis-mcp server script not found at $serverScript"
}

# one-time venv bootstrap (idempotent)
if (-not (Test-Path "$venv\Scripts\python.exe")) {
    Write-Host "[qgis-mcp] First run: creating venv + installing fastmcp ..."
    & python -m venv $venv
    & "$venv\Scripts\python.exe" -m pip install --upgrade pip
    & "$venv\Scripts\python.exe" -m pip install -r "$qgisHome\requirements.txt"
}

$env:DESKTOP_HOST    = "127.0.0.1"
$env:QGIS_MCP_PORT   = "9877"
$env:MCP_TRANSPORT   = "streamable-http"
$env:FASTMCP_HOST    = "127.0.0.1"
$env:FASTMCP_PORT    = "8081"
# Optional toolset filter: full | cartography | data | geoprocess | minimal
if (-not $env:QGIS_TOOLSET) { $env:QGIS_TOOLSET = "full" }

$proc = Start-Process -FilePath "$venv\Scripts\python.exe" `
    -ArgumentList "`"$serverScript`"" `
    -RedirectStandardOutput $LogPath `
    -RedirectStandardError "$LogPath.err" `
    -WindowStyle Hidden `
    -PassThru
return $proc
