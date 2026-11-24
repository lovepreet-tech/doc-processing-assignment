FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
RUN pip install --no-cache-dir -e ".[dev]"

COPY . .

# Refresh editable package discovery now that the source exists. The earlier
# install caches dependencies, but cannot discover packages before COPY.
RUN pip install --no-cache-dir --no-deps -e . \
    && python -I -c "import api, core, extraction, ingestion, progress, storage.object_store"

# which celery app to run is picked with the CMD override in docker-compose.yml
# (ingestion.celery_app vs extraction.celery_app)
CMD ["celery", "-A", "ingestion.celery_app", "worker", "--loglevel=info"]
