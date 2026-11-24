"""Separate Celery app for the extraction worker pool."""

from celery import Celery

from core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "extraction",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

celery_app.conf.task_routes = {"extraction.tasks.*": {"queue": "extraction"}}

# registers the task module explicitly since it isn't at the path autodiscover_tasks expects
import extraction.tasks.run_extraction  # noqa: E402,F401
