# One image for the API, Celery worker, Celery beat and the Streamlit console.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

RUN pip install --no-cache-dir uv==0.13.5

WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
COPY config ./config
COPY mcp_servers ./mcp_servers
COPY tests/fixtures ./tests/fixtures
COPY scripts ./scripts
COPY ui ./ui
RUN uv sync --frozen --no-dev

EXPOSE 8000 8501
CMD ["uvicorn", "aos.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
