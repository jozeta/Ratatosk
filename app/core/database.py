import datetime

from sqlalchemy import DateTime, create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.types import TypeDecorator

from app.core.config import settings

_is_sqlite = settings.database_url.startswith("sqlite")
connect_args = {"check_same_thread": False, "timeout": 15} if _is_sqlite else {}
engine = create_engine(settings.database_url, connect_args=connect_args)

if _is_sqlite:

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _record):
        # WAL lets readers proceed during a write and makes commits cheaper;
        # busy_timeout makes concurrent writers wait instead of failing with
        # "database is locked" (PERF-009).
        cur = dbapi_connection.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA busy_timeout=15000")
        cur.execute("PRAGMA foreign_keys=OFF")
        cur.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class UTCDateTime(TypeDecorator):
    """Stores naive UTC (same on-disk format as before, so no data migration),
    always hands back timezone-aware UTC datetimes - so callers never have to
    remember `.replace(tzinfo=utc)` again (ARCH-006)."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is not None:
            value = value.astimezone(datetime.UTC).replace(tzinfo=None)
        return value

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=datetime.UTC) if value.tzinfo is None else value


def rowcount(result) -> int:
    """Rows affected by an UPDATE/DELETE (SQLAlchemy's Result type hints
    don't expose rowcount, though the CursorResult behind it does)."""
    return int(getattr(result, "rowcount", 0) or 0)


def utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
