FROM python:3.12-slim-bookworm@sha256:e697c81897302a4c4333bade000d98038fbb21eb064f8ee1fd42d02ebcd9d337
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/opt/deployment:/opt/cloud_gateway:/app
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
RUN apt-get update && apt-get install -y --no-install-recommends iproute2 && rm -rf /var/lib/apt/lists/*
COPY lexaegis ./lexaegis
COPY packs ./packs
COPY frontend/dist ./frontend/dist
COPY deploy/workbench_demo/workbench.py deploy/workbench_demo/public_proxy.py deploy/workbench_demo/poll_events.js deploy/workbench_demo/edge_connector.py deploy/workbench_demo/model_route_guard.py deploy/workbench_demo/local_ingress.py /opt/deployment/
COPY deploy/cloud_gateway/cloud_runtime.py deploy/cloud_gateway/ds_gateway.py deploy/cloud_gateway/shared_budget.py deploy/cloud_gateway/provider_egress.py deploy/cloud_gateway/route_guard.py /opt/cloud_gateway/
RUN useradd --uid 10001 --create-home lex && mkdir -p /data/workbench /data/gateway /quota && chown -R lex:lex /data /quota
USER 10001:10001
CMD ["python","/opt/deployment/workbench.py"]
