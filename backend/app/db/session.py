"""SQLAlchemy engine/session wiring. Works against SQLite (local dev, no
server required) or Postgres (production) purely via DATABASE_URL."""
from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

settings = get_settings()
_is_sqlite = settings.database_url.startswith("sqlite")

_connect_args = {"check_same_thread": False} if _is_sqlite else {}

engine = create_engine(settings.database_url, connect_args=_connect_args, future=True)

if _is_sqlite:
    # SQLite does not enforce foreign keys unless told to per-connection.
    # Leaving this off let local dev silently accept states Postgres/Neon
    # rejects outright (see delete_session in api/v1/sessions.py, which
    # 500'd with a real ForeignKeyViolation the first time it ran against
    # Neon despite passing every test here) -- turning it on makes SQLite
    # behave like production instead of masking the bug.
    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

_tables_initialized = False


def init_db_tables() -> None:
    global _tables_initialized
    if not _tables_initialized:
        try:
            from app.db.base import Base
            Base.metadata.create_all(bind=engine)
            _tables_initialized = True
        except Exception:
            pass


def get_db() -> Generator[Session, None, None]:
    init_db_tables()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
