FROM python:3.14.0-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

RUN groupadd --system orderflow \
    && useradd --system --gid orderflow --home-dir /app orderflow

COPY --from=ghcr.io/astral-sh/uv:0.11.33 /uv /uvx /bin/
COPY pyproject.toml uv.lock README.md ./
COPY src ./src

RUN uv sync --frozen --no-dev --no-editable

COPY alembic.ini ./
COPY migrations ./migrations
COPY scripts ./scripts
RUN chmod +x scripts/docker-entrypoint.sh \
    && chown -R orderflow:orderflow /app

USER orderflow

EXPOSE 8000

ENTRYPOINT ["./scripts/docker-entrypoint.sh"]
CMD ["uvicorn", "orderflow.main:app", "--host", "0.0.0.0", "--port", "8000"]

