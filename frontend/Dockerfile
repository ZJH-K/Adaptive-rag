FROM python:3.11-slim-bookworm

ARG UV_VERSION=0.11.7

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/frontend/.venv/bin:${PATH}" \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

RUN python -m pip install --no-cache-dir "uv==${UV_VERSION}" \
    && groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --no-log-init --create-home app

WORKDIR /app/frontend

COPY frontend/pyproject.toml frontend/uv.lock ./
RUN uv sync --frozen --no-dev

COPY --chown=app:app frontend/app.py frontend/api_client.py frontend/sse.py frontend/state.py ./

USER app

EXPOSE 8501

HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=5 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=2).read()"]

CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true"]
