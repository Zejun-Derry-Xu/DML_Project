FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app
RUN pip install --no-cache-dir uv==0.8.22

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY app ./app
COPY migrations ./migrations
COPY scripts ./scripts
COPY data ./data
COPY alembic.ini README.md ./
RUN uv sync --frozen --no-dev

RUN addgroup --system returnflow && adduser --system --ingroup returnflow returnflow \
    && chown -R returnflow:returnflow /app
USER returnflow

EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && python -m scripts.seed_data && uvicorn app.main:app --host 0.0.0.0 --port 8000"]

