FROM node:24-bookworm-slim AS frontend
WORKDIR /src/frontend
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./
RUN npm install -g pnpm@11.19.0 && pnpm install --frozen-lockfile
COPY frontend ./
RUN pnpm build

FROM ghcr.io/ggml-org/llama.cpp:server AS llama

FROM ubuntu:24.04
ARG TARGETARCH
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-venv python3-pip libgomp1 ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && python3 -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY lexaegis ./lexaegis
COPY packs ./packs
COPY container/docker-entrypoint.sh /docker-entrypoint.sh
COPY --from=frontend /src/frontend/dist ./frontend/dist
COPY --from=llama /app /opt/llama
RUN useradd --uid 10001 --create-home lex \
    && mkdir -p /data/app /data/gateway \
    && chown -R lex:lex /data \
    && chmod 0755 /docker-entrypoint.sh /opt/llama/llama-server
# Single-container submission runtime: the launcher starts gateway -> api -> worker
# in one container. App and gateway data roots stay separate so bind_runtime can
# mark empty directories. LEX_BIND_HOST=0.0.0.0 is required because `docker run -p`
# maps the container's eth0, not its loopback. Publish to the host loopback only:
# -p 127.0.0.1:8765:8765. Mount ./models to /models to start the bundled GGUF in
# this same container. Ubuntu 24.04 matches the llama.cpp server glibc. This mode
# is `native`: it makes no verifiable network-isolation claim and formal outbound
# dispatch stays blocked. Compose remains the isolated-deployment reference.
ENV LEX_DATA_DIR=/data/app \
    LEX_GATEWAY_DIR=/data/gateway \
    LEX_API_PORT=8765 \
    LEX_GATEWAY_PORT=8766 \
    LEX_BIND_HOST=0.0.0.0 \
    LEX_RUN_PROFILE=demo \
    LEX_EDGE_BIN=/opt/llama/llama-server \
    LEX_EDGE_GGUF=/models/edge/qwen3-4b-grpo/runtime/Qwen3-4B-GRPO.Q4_K_M.gguf \
    LEX_EDGE_URL=http://127.0.0.1:8080/v1 \
    LEX_EDGE_MODEL=lexaegis-qwen3-4b-grpo \
    LEX_EDGE_OUTBOUND_REVIEW=1 \
    LEX_EDGE_CTX_SIZE=4096 \
    LEX_EDGE_BATCH_SIZE=512 \
    LEX_EDGE_UBATCH_SIZE=256 \
    LEX_EDGE_N_GPU_LAYERS=0 \
    LEX_EDGE_FLASH_ATTN=off \
    LEX_EDGE_PID_FILE=/tmp/llama-server.pid \
    LEX_EDGE_START_WAIT=120 \
    LD_LIBRARY_PATH=/opt/llama
VOLUME /data
EXPOSE 8765
USER lex
HEALTHCHECK --interval=15s --timeout=5s --start-period=90s --retries=6 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/api/v1/health')"]
ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["python", "-m", "lexaegis.cli", "start"]
