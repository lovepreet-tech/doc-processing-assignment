FROM python:3.12-slim

WORKDIR /app

# system deps needed by pymupdf/docling for pdf handling
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
RUN pip install --no-cache-dir -e ".[dev]"

RUN mkdir -p uploaded_files

COPY . .

# Refresh editable package discovery now that the source exists. The earlier
# install caches dependencies, but cannot discover packages before COPY.
RUN pip install --no-cache-dir --no-deps -e . \
    && python -I -c "import api, core, extraction, ingestion, progress, storage.object_store"

CMD ["sh", "-c", "alembic upgrade head && exec uvicorn api.main:app --host 0.0.0.0 --port 8000"]
