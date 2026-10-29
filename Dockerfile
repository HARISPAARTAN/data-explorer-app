# syntax=docker/dockerfile:1
# Base and uv images pinned by digest (multi-arch index, resolved 2026-10-29 from the registries' manifest API, the value docker buildx imagetools inspect prints).
# python:3.12-slim@sha256:aa943ce411423c7582288f18707ff66eddcbaeb510502d747a72aeb34f30d159
# ghcr.io/astral-sh/uv:0.11.8@sha256:3b7b60a81d3c57ef471703e5c83fd4aaa33abcd403596fb22ab07db85ae91347
FROM python:3.12-slim@sha256:aa943ce411423c7582288f18707ff66eddcbaeb510502d747a72aeb34f30d159 AS base

# --- Python dependencies from uv.lock (the set the tests ran), then the project itself, both non-editable
FROM base AS deps
COPY --from=ghcr.io/astral-sh/uv:0.11.8@sha256:3b7b60a81d3c57ef471703e5c83fd4aaa33abcd403596fb22ab07db85ae91347 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project --no-editable
COPY README.md LICENSE ./
COPY src ./src
RUN uv sync --locked --no-dev --no-editable

# --- Runtime: the venv, the sources and the server config under /app, as an unprivileged user
FROM base
WORKDIR /app
COPY --from=deps /app/.venv /app/.venv
COPY src ./src
COPY .streamlit/config.toml ./.streamlit/config.toml
RUN useradd --system --create-home --uid 10001 app
USER app

ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    DATA_EXPLORER_LOG_LEVEL=INFO
EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=4).status == 200 else 1)"
ENTRYPOINT ["streamlit", "run", "src/data_explorer/app/streamlit_app.py", "--server.port=8501", "--server.address=0.0.0.0", "--server.headless=true"]
