FROM node:22-alpine AS frontend
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS app
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /usr/local/bin/uv
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/engine/.venv/bin:$PATH"
WORKDIR /app/engine
COPY engine/pyproject.toml engine/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY engine/parable ./parable
COPY --from=frontend /build/frontend/dist /app/frontend/dist
RUN useradd --create-home --uid 10001 parable \
    && mkdir -p /var/data \
    && chown -R parable:parable /var/data /app
USER parable
EXPOSE 10000
CMD ["sh", "-c", "exec uvicorn parable.api:app --host 0.0.0.0 --port ${PORT:-10000} --no-proxy-headers"]
