"""Tiny pub/sub wrapper so pipeline steps can tell the FE what they're doing right now.

A LangGraph node (or a plain Celery task, during stage 1 before the graph exists)
calls `publish_step` after each step; `stream_steps` is what the SSE route in
api/routers/files.py and api/routers/extractions.py reads from.
"""

import json
import time

import redis

from core.config import get_settings

settings = get_settings()
_redis = redis.from_url(settings.redis_url)

# a FastAPI `def` route's generator gets iterated via Starlette's threadpool, which
# is a small FIXED-size pool shared by every sync endpoint in the app - an
# unbounded pubsub.listen() blocks its thread forever for a stream that never
# gets another message (job finished before the client connected and the
# ":latest" cache key since expired, or the job was abandoned). Given enough of
# those (long-lived pages, EventSource's own auto-reconnect-forever behavior),
# every thread in the pool ends up permanently pinned and EVERY other sync route
# in the app - including unrelated ones like list/delete session - hangs forever
# waiting for a free thread. Bounding each poll and the overall idle window
# guarantees this generator always returns the thread to the pool eventually.
POLL_TIMEOUT_SECONDS = 5
IDLE_TIMEOUT_SECONDS = 60


def _channel(kind: str, entity_id: str) -> str:
    # kind is "file" or "extraction_job" - keeps the two progress streams from colliding
    return f"progress:{kind}:{entity_id}"


def publish_step(kind: str, entity_id: str, step: str, status: str, detail: str | None = None) -> None:
    payload = {"step": step, "status": status, "detail": detail, "ts": time.time()}
    _redis.publish(_channel(kind, entity_id), json.dumps(payload))
    # also keep the latest step around so a page refresh can show "where we're at"
    # without waiting for the next pub/sub message
    _redis.set(f"{_channel(kind, entity_id)}:latest", json.dumps(payload), ex=3600)


def get_latest_step(kind: str, entity_id: str) -> dict | None:
    raw = _redis.get(f"{_channel(kind, entity_id)}:latest")
    return json.loads(raw) if raw else None


def stream_steps(kind: str, entity_id: str):
    """Generator of progress events, for the SSE route to iterate over.

    Subscribes first, then replays the latest cached step before listening -
    otherwise a client that connects after the pipeline already finished (the
    common case locally, where the worker runs the whole thing in well under a
    second) never sees any message and the FE just sits on "running" forever.

    Polls with a timeout instead of blocking on pubsub.listen() forever, and
    gives up after IDLE_TIMEOUT_SECONDS with no new message - see the module-level
    comment on why an unbounded block here is a whole-app availability bug, not
    just a leaked connection. A client that still wants updates (EventSource
    auto-reconnects on its own) just opens a fresh stream, which replays whatever
    ":latest" says at that point.
    """
    pubsub = _redis.pubsub()
    pubsub.subscribe(_channel(kind, entity_id))
    try:
        latest = get_latest_step(kind, entity_id)
        if latest is not None:
            yield json.dumps(latest)
            if latest.get("status") in ("done", "failed"):
                return

        deadline = time.monotonic() + IDLE_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            message = pubsub.get_message(timeout=POLL_TIMEOUT_SECONDS)
            if message is None or message["type"] != "message":
                continue
            yield message["data"]
            deadline = time.monotonic() + IDLE_TIMEOUT_SECONDS
            data = json.loads(message["data"])
            if data.get("status") in ("done", "failed"):
                return
    finally:
        pubsub.close()
