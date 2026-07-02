FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv

# System deps kept minimal; asyncpg/bcrypt ship wheels for slim.
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Install deps first for better layer caching.
COPY pyproject.toml README.md ./
RUN pip install --upgrade pip && pip install .

# App source + migrations.
COPY app ./app
COPY migrations ./migrations
COPY alembic.ini ./

EXPOSE 8000

# Apply migrations, then serve. Overridable in compose.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
