# syntax=docker/dockerfile:1

FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DASH_DATA_DIR=/data \
    PATH=/app/.venv/bin:$PATH

# Build tooling + the unprivileged runtime user.
RUN pip install --no-cache-dir uv && \
    addgroup --system dashboard && \
    adduser --system --ingroup dashboard --no-create-home --shell /usr/sbin/nologin dashboard

WORKDIR /app

# Project metadata first (layer caching), then the sources.
COPY pyproject.toml uv.lock ./
COPY src/ ./src/

# Runtime deps strictly from uv.lock into /app/.venv; the application itself
# is built as a regular (non-editable) wheel and installed into the same venv.
RUN uv venv --python /usr/local/bin/python3 .venv && \
    uv sync --frozen --no-dev --no-install-project && \
    uv build --wheel --out-dir /dist && \
    uv pip install --python /app/.venv/bin/python --no-deps /dist/dashboard-*.whl && \
    pip uninstall --yes uv && \
    rm -rf /dist

# Data volume location (SQLite DB + generated .secret key).
RUN mkdir -p /data && \
    chown dashboard:dashboard /data && \
    rm -rf /app/src

USER dashboard

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"]

CMD ["uvicorn", "dashboard.main:app", "--host", "0.0.0.0", "--port", "8000"]
