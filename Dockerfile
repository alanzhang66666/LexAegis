FROM node:24-bookworm-slim AS frontend
WORKDIR /src/frontend
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./
RUN npm install -g pnpm@11.19.0 && pnpm install --frozen-lockfile
COPY frontend ./
RUN pnpm build

FROM python:3.12-slim
ARG TARGETARCH
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY lexaegis ./lexaegis
COPY packs ./packs
COPY --from=frontend /src/frontend/dist ./frontend/dist
RUN useradd --uid 10001 --create-home lex && mkdir /data && chown lex:lex /data
USER lex
CMD ["python", "-m", "uvicorn", "lexaegis.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8765", "--no-access-log"]
