"""Runtime-configurable settings, persisted to SQLite and cached in-process.

Any admin update writes through to the DB and immediately refreshes the
in-memory cache, so changes apply across the app without a restart.
"""
import threading

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.settings import SystemSettings

_lock = threading.RLock()
_cache: SystemSettings | None = None


def _row_to_dict(row: SystemSettings) -> dict:
    return {c.name: getattr(row, c.name) for c in row.__table__.columns}


def get_or_create_settings(db: Session) -> SystemSettings:
    row = db.get(SystemSettings, 1)
    if row is None:
        row = SystemSettings(id=1)
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def load_cache() -> dict:
    global _cache
    with _lock:
        db = SessionLocal()
        try:
            row = get_or_create_settings(db)
            _cache = _row_to_dict(row)
            return _cache
        finally:
            db.close()


def get_settings() -> dict:
    with _lock:
        if _cache is None:
            return load_cache()
        return dict(_cache)


def reset_settings_to_defaults(db: Session) -> dict:
    """Drops the singleton settings row and recreates it, so every column
    reverts to the SystemSettings model's own defaults - used by the
    admin "reset everything" flow."""
    with _lock:
        row = db.get(SystemSettings, 1)
        if row is not None:
            db.delete(row)
            db.commit()
        get_or_create_settings(db)
        return load_cache()


def update_settings(changes: dict) -> dict:
    with _lock:
        db = SessionLocal()
        try:
            row = get_or_create_settings(db)
            for key, value in changes.items():
                if hasattr(row, key) and key != "id":
                    setattr(row, key, value)
            db.commit()
            db.refresh(row)
        finally:
            db.close()
        return load_cache()
