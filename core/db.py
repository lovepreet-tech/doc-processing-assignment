"""SQLAlchemy engine/session setup, plus the tenant-scoping helper used by RLS."""

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from core.config import get_settings

settings = get_settings()

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    """FastAPI dependency - yields a request-scoped DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Plain context manager for use outside FastAPI, e.g. in Celery tasks."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def set_tenant_context(db: Session, tenant_id: str) -> None:
    """Sets the Postgres session var that RLS policies check against.

    Must run on this connection before any tenant-scoped query.
    """
    db.execute(text("SELECT set_config('app.tenant_id', :tenant_id, false)"), {"tenant_id": tenant_id})
