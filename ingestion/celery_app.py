"""Celery app for the ingestion worker pool, scaled independently from extraction's."""

from celery import Celery

from core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "ingestion",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

celery_app.conf.task_routes = {"ingestion.tasks.*": {"queue": "ingestion"}}

# registers the task module explicitly since it isn't at the path autodiscover_tasks expects
import ingestion.tasks.ingest_file  # noqa: E402,F401
