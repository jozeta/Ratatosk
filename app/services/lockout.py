"""Brute-force protection with atomic attempt reservation.

The old code read a failure counter, ran bcrypt (~250ms), then wrote the
counter back. Every request in flight during that window got a free guess:
32 parallel guesses against a limit of 5 were all checked (SEC-005). Here an
attempt is *reserved* with a single conditional UPDATE before any password
work happens, so at most `max_attempts` guesses can ever be in progress or
completed per lockout window, however many arrive at once.
"""
import datetime

from fastapi import HTTPException, Request, status
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import rowcount, utcnow
from app.core.ratelimit import network_key
from app.models.file import FileObject
from app.models.ops import LoginThrottle


def _locked(minutes_left: float) -> HTTPException:
    mins = max(1, int(minutes_left) + 1)
    return HTTPException(status_code=status.HTTP_423_LOCKED, detail=f"Too many failed attempts. Try again in {mins} minute(s).")


# ---------------------------------------------------------------- files ---

def reserve_file_attempt(db: Session, file_id: str, cfg: dict) -> None:
    """Claim one passphrase attempt for a file, or raise 423 while locked."""
    now = utcnow()
    max_attempts = cfg["max_login_attempts"]
    f = db.get(FileObject, file_id)
    if f is not None and f.locked and f.locked_until is None:
        # Legacy permanent lock (pre-SEC-006): convert to a timed one.
        db.execute(update(FileObject).where(FileObject.id == file_id).values(
            locked=False, locked_until=now + datetime.timedelta(minutes=cfg["login_lockout_minutes"])))
        db.commit()
    # An expired lock starts a fresh window.
    db.execute(update(FileObject).where(FileObject.id == file_id, FileObject.locked_until <= now)
               .values(locked_until=None, failed_attempts=0))
    res = db.execute(
        update(FileObject)
        .where(FileObject.id == file_id, FileObject.failed_attempts < max_attempts, FileObject.locked_until.is_(None))
        .values(failed_attempts=FileObject.failed_attempts + 1)
    )
    db.commit()
    if rowcount(res) == 0:
        until = db.execute(select(FileObject.locked_until).where(FileObject.id == file_id)).scalar_one_or_none()
        if until is None:
            # Limit reached by the attempts in flight: lock now.
            until = now + datetime.timedelta(minutes=cfg["login_lockout_minutes"])
            db.execute(update(FileObject).where(FileObject.id == file_id, FileObject.locked_until.is_(None)).values(locked_until=until))
            db.commit()
        raise _locked((until - now).total_seconds() / 60)


def record_file_attempt(db: Session, file_id: str, ok: bool, cfg: dict) -> None:
    if ok:
        db.execute(update(FileObject).where(FileObject.id == file_id).values(failed_attempts=0, locked_until=None))
    else:
        db.execute(
            update(FileObject)
            .where(FileObject.id == file_id, FileObject.failed_attempts >= cfg["max_login_attempts"], FileObject.locked_until.is_(None))
            .values(locked_until=utcnow() + datetime.timedelta(minutes=cfg["login_lockout_minutes"]))
        )
    db.commit()


def unlock_file(db: Session, file_id: str) -> None:
    db.execute(update(FileObject).where(FileObject.id == file_id).values(failed_attempts=0, locked_until=None, locked=False))
    db.commit()


# --------------------------------------------------------------- logins ---

def reserve_login_attempt(db: Session, user_id: str, request: Request, cfg: dict) -> None:
    """Claim one login guess for (account, client network), or raise 423.

    Keyed by network (SEC-012): someone hammering an account only locks
    *their own* network out of it - the real owner can still sign in."""
    if not cfg["enable_login_rate_limit"]:
        return
    now = utcnow()
    net = network_key(request)
    try:
        db.add(LoginThrottle(user_id=user_id, net_key=net, failures=0))
        db.commit()
    except IntegrityError:
        db.rollback()
    base = (LoginThrottle.user_id == user_id) & (LoginThrottle.net_key == net)
    db.execute(update(LoginThrottle).where(base, LoginThrottle.locked_until <= now).values(locked_until=None, failures=0))
    res = db.execute(
        update(LoginThrottle)
        .where(base, LoginThrottle.failures < cfg["max_login_attempts"], LoginThrottle.locked_until.is_(None))
        .values(failures=LoginThrottle.failures + 1, updated_at=now)
    )
    db.commit()
    if rowcount(res) == 0:
        until = db.execute(select(LoginThrottle.locked_until).where(base)).scalar_one_or_none()
        if until is None:
            until = now + datetime.timedelta(minutes=cfg["login_lockout_minutes"])
            db.execute(update(LoginThrottle).where(base, LoginThrottle.locked_until.is_(None)).values(locked_until=until))
            db.commit()
        raise _locked((until - now).total_seconds() / 60)


def record_login_attempt(db: Session, user_id: str, request: Request, ok: bool, cfg: dict) -> bool:
    """Returns True if this failure triggered a lockout."""
    if not cfg["enable_login_rate_limit"]:
        return False
    net = network_key(request)
    base = (LoginThrottle.user_id == user_id) & (LoginThrottle.net_key == net)
    if ok:
        db.execute(delete(LoginThrottle).where(base))
        db.commit()
        return False
    res = db.execute(
        update(LoginThrottle)
        .where(base, LoginThrottle.failures >= cfg["max_login_attempts"], LoginThrottle.locked_until.is_(None))
        .values(locked_until=utcnow() + datetime.timedelta(minutes=cfg["login_lockout_minutes"]))
    )
    db.commit()
    return rowcount(res) > 0


def clear_login_throttles(db: Session, user_id: str | None = None) -> int:
    q = delete(LoginThrottle)
    if user_id is not None:
        q = q.where(LoginThrottle.user_id == user_id)
    res = db.execute(q)
    db.commit()
    return rowcount(res)
