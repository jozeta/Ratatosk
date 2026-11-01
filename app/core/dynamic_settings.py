"""Runtime-configurable settings, persisted in one DB row and cached in-process.

Each process caches the row, but re-checks the row's `version` counter at
most every REVALIDATE_SECONDS (one primary-key SELECT) and reloads when it
changed. So a change made through any worker, container, or host reaches
every process within about a second (BUG-002); previously only the process
that handled the admin's request ever saw it.
"""
import threading
import time

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.settings import SystemSettings

REVALIDATE_SECONDS = 1.0

_lock = threading.RLock()
_cache: dict | None = None
_cache_version: int | None = None
_last_check = 0.0


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
    global _cache, _cache_version, _last_check
    with _lock:
        db = SessionLocal()
        try:
            row = get_or_create_settings(db)
            _cache = _row_to_dict(row)
            _cache_version = _cache.get("version", 0)
            _last_check = time.monotonic()
            return _cache
        finally:
            db.close()


def _current_db_version() -> int | None:
    db = SessionLocal()
    try:
        return db.execute(select(SystemSettings.version).where(SystemSettings.id == 1)).scalar_one_or_none()
    finally:
        db.close()


def get_settings() -> dict:
    global _last_check
    with _lock:
        if _cache is None:
            return dict(load_cache())
        now = time.monotonic()
        if now - _last_check >= REVALIDATE_SECONDS:
            _last_check = now
            if _current_db_version() != _cache_version:
                load_cache()
        return dict(_cache or {})


def invalidate_cache() -> None:
    """Force the next get_settings() to re-check the database."""
    global _last_check
    with _lock:
        _last_check = 0.0


def reset_settings_to_defaults(db: Session) -> dict:
    """Drops the singleton settings row and recreates it, so every column
    reverts to the model's defaults - used by the admin factory reset. The
    version keeps counting up so other processes notice the reset."""
    with _lock:
        row = db.get(SystemSettings, 1)
        old_version = row.version if row is not None else 0
        if row is not None:
            db.delete(row)
            db.commit()
        new = get_or_create_settings(db)
        new.version = (old_version or 0) + 1
        db.commit()
        return load_cache()


def update_settings(changes: dict) -> dict:
    with _lock:
        db = SessionLocal()
        try:
            row = get_or_create_settings(db)
            for key, value in changes.items():
                if hasattr(row, key) and key not in ("id", "version"):
                    setattr(row, key, value)
            db.flush()
            db.execute(update(SystemSettings).where(SystemSettings.id == 1).values(version=SystemSettings.version + 1))
            db.commit()
        finally:
            db.close()
        return load_cache()
