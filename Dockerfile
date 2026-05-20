# Builder stage
FROM python:3.12.8-alpine AS builder

# Install only necessary build dependencies
RUN apk add --no-cache git gcc musl-dev

WORKDIR /app
COPY requirements.txt .

# Install requirements
RUN pip install --user --no-cache-dir -r requirements.txt

# Final stage
FROM python:3.12.8-alpine
WORKDIR /app

# Copy built packages and app code
COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH
COPY server.py ./
COPY socketServer.py ./
COPY mcp_server.py ./
COPY validator.py ./
COPY rate_limiter.py ./
COPY start_servers.py ./
COPY stockmap.json ./
COPY updateStocksMap.py ./
COPY test_mcp.py ./
COPY test_rate_limiting.py ./
COPY test_update.py ./
COPY quick_update.py ./


# Healthcheck for REST API (port 8000)
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import http.client; conn = http.client.HTTPConnection('localhost:8000'); conn.request('GET', '/health'); response = conn.getresponse(); exit(0) if response.status == 200 else exit(1)"

# Healthcheck for MCP server (port 9000 or 8080, depending on config)
# Uncomment and adjust if you want to check MCP health as well
# HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
#     CMD python -c "import socket; s=socket.socket(); s.settimeout(5); s.connect(('localhost',9000)); s.close()"

EXPOSE 8000 5555 9000

CMD ["python", "start_servers.py"]