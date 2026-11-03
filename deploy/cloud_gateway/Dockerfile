FROM python:3.12-slim-bookworm@sha256:e697c81897302a4c4333bade000d98038fbb21eb064f8ee1fd42d02ebcd9d337
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/opt/cloud_gateway
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
# Only original backend/package code and cloud deployment files enter this image.
COPY lexaegis ./lexaegis
COPY packs ./packs
COPY deploy/cloud_gateway/cloud_runtime.py deploy/cloud_gateway/provider_egress.py deploy/cloud_gateway/tcp_ingress.py deploy/cloud_gateway/route_guard.py deploy/cloud_gateway/ds_gateway.py deploy/cloud_gateway/shared_budget.py /opt/cloud_gateway/
RUN apt-get update && apt-get install -y --no-install-recommends iproute2 && rm -rf /var/lib/apt/lists/*
RUN useradd --uid 10001 --create-home lex && mkdir -p /data/gateway && chown -R lex:lex /data
USER 10001:10001
CMD ["python","-m","uvicorn","cloud_runtime:create_app","--factory","--host","0.0.0.0","--port","8766","--no-access-log"]
