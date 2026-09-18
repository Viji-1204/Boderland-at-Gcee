"""Engine, sessions and the declarative base.

Works with SQLite (default, zero setup, file at ``backend/data/round2.db``)
and Postgres (``DATABASE_URL=postgresql+psycopg2://...``, used by
docker-compose). Nothing here ever drops tables - schema changes go through
Alembic migrations.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterator

from sqlalchemy import MetaData, create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def _sqlite_path(url: str) -> str | None:
    if "///" not in url:
        return None
    path = url.split("///", 1)[1].split("?", 1)[0]
    return None if path in ("", ":memory:") else path


def make_engine(url: str) -> Engine:
    kwargs: dict = {"pool_pre_ping": True}
    is_sqlite = url.startswith("sqlite")
    if is_sqlite:
        path = _sqlite_path(url)
        if path:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
    eng = create_engine(url, **kwargs)
    if is_sqlite:

        @event.listens_for(eng, "connect")
        def _sqlite_pragmas(dbapi_conn, _record):  # pragma: no cover - trivial
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.execute("PRAGMA busy_timeout=10000")
            cur.close()

    return eng


engine = make_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one session per request."""
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Real-time messages are queued on the session and only sent once the
# transaction commits, so a client is never told about a change that was
# rolled back.
# ---------------------------------------------------------------------------


def queue_publish(db: Session, channel: str, message: dict) -> None:
    db.info.setdefault("publish_queue", []).append((channel, message))


@event.listens_for(SessionLocal, "after_commit")
def _flush_publish_queue(session: Session) -> None:
    queue = session.info.pop("publish_queue", None)
    if not queue:
        return
    from app.services.websocket_service import hub

    for channel, message in queue:
        hub.publish(channel, message)


@event.listens_for(SessionLocal, "after_rollback")
def _drop_publish_queue(session: Session) -> None:
    session.info.pop("publish_queue", None)
