FROM python:3.13-slim-trixie

# ============================================================
# QGIS MCP Server — socket proxy to QGIS plugin
# Connects to the QGIS MCP plugin running inside the desktop
# container (aec-web) on port 9877
# ============================================================

WORKDIR /app

# The server imports standalone fastmcp (see requirements.txt). This used to
# install only "mcp[cli]", so a clean build failed on `from fastmcp import ...`.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# The server imports its sibling modules (tool tags, rules), not just itself.
COPY *.py ./

ENV DESKTOP_HOST=aec-web
ENV QGIS_MCP_PORT=9877

# Streamable HTTP transport — accessible from any VPN machine
ENV MCP_TRANSPORT=streamable-http
ENV FASTMCP_HOST=0.0.0.0
ENV FASTMCP_PORT=8081

EXPOSE 8081

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
  CMD python3 -c "import socket; s=socket.socket(); s.settimeout(5); s.connect(('localhost',8081)); s.close()"

CMD ["python3", "/app/qgis_mcp_server.py"]
