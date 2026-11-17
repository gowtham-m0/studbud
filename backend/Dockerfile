FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock alembic.ini ./
COPY migrations ./migrations
COPY src ./src
COPY docker-entrypoint.sh ./docker-entrypoint.sh

RUN uv sync --frozen --no-dev \
    && chmod +x /app/docker-entrypoint.sh

ENV PATH="/app/.venv/bin:$PATH" \
    AUTO_MIGRATE=true \
    FASTEMBED_CACHE_DIR=/app/.fastembed

RUN python -c "from fastembed import TextEmbedding; TextEmbedding(model_name='nomic-ai/nomic-embed-text-v1.5-Q', cache_dir='/app/.fastembed')"

EXPOSE 8000

CMD ["/app/docker-entrypoint.sh"]
