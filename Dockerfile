# Namma Agent — headless server image (Phase 6b).
# Multi-stage: the React UI builds in a Node stage so the runtime image stays
# a slim Python. x86-64 first (the Oracle E2.1.Micro reference box); ARM64
# builds the same way (docker buildx --platform linux/arm64).
#
#   docker compose up -d          # (see docker-compose.yml)
#   docker build -t namma-agent . && docker run --env-file .env -p 8000:8000 -v namma_data:/app/data namma-agent

FROM node:20-alpine AS webui
WORKDIR /build
COPY namma_agent/webui/package*.json ./
RUN npm ci --no-audit --no-fund
COPY namma_agent/webui/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app

# Core + providers + comms — no GUI/desktop extras in a container.
RUN pip install --no-cache-dir \
    fastapi "uvicorn[standard]" websockets pydantic PyYAML \
    anthropic openai google-genai \
    ddgs requests python-multipart

COPY namma_agent/ namma_agent/
COPY deploy/config.server-lite.yaml namma_agent/config.local.yaml
COPY --from=webui /build/dist namma_agent/webui/dist

# Non-root; /app/data is the single state volume (NAMMA_DATA_DIR points at it).
RUN useradd --system --uid 1001 namma \
    && mkdir -p /app/data /app/logs \
    && chown -R namma:namma /app
USER namma
VOLUME ["/app/data"]

# In a container the server must bind all interfaces — the mapped port is the
# boundary. Set NAMMA_AUTH_TOKEN via --env-file when you publish that port
# beyond localhost.
ENV NAMMA_HOST=0.0.0.0 \
    NAMMA_DATA_DIR=/app/data \
    PYTHONUNBUFFERED=1
EXPOSE 8000

# stdlib probe — curl isn't in slim, and /api/health is auth-exempt by design.
HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
  CMD ["python", "-c", "import urllib.request,sys;sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status==200 else 1)"]

CMD ["python", "-m", "namma_agent", "--server"]
