import csv
import io

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dynamic_settings import get_settings
from app.core.password_policy import validate_password
from app.core.security import hash_password, require_admin
from app.models.api_key import ApiKey
from app.models.file import FileObject
from app.models.file_share import FileShare
from app.models.user import User
from app.schemas.common import BatchIds
from app.schemas.users import AdminCreateUser, AdminResetPassword, AdminUpdateUser, UserSummary
from app.services.audit_service import log_event

router = APIRouter(prefix="/api/admin/users", tags=["admin"])

MAX_IMPORT_ROWS = 1000
MAX_IMPORT_BYTES = 1 * 1024 * 1024

_TRUE_STRINGS = {"1", "true", "yes", "y"}


def _require_enabled():
    if not get_settings()["enable_user_management"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User management is disabled in settings")


@router.get("", response_model=list[UserSummary])
def list_users(db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    _require_enabled()
    return db.query(User).order_by(User.created_at.desc()).all()


@router.post("", response_model=UserSummary)
def create_user(payload: AdminCreateUser, request: Request, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    _require_enabled()
    cfg = get_settings()

    if db.query(User).filter(User.username == payload.username).first():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already taken")

    email = (payload.email or "").strip().lower() or None
    if email and db.query(User).filter(User.email == email).first():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already in use")

    errors = validate_password(payload.password, cfg)
    if errors:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=" ".join(errors))

    user = User(username=payload.username, email=email, password_hash=hash_password(payload.password), is_admin=payload.is_admin)
    db.add(user)
    db.commit()
    db.refresh(user)
    log_event(db, "ADMIN_USER_CREATED", request=request, user_id=admin.id, detail=f"created={user.username}")
    return user


@router.get("/export")
def export_users_csv(db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    _require_enabled()
    users = db.query(User).order_by(User.created_at.desc()).all()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["username", "email", "is_admin", "is_active", "mfa_enabled", "created_at"])
    for u in users:
        writer.writerow([u.username, u.email or "", str(u.is_admin).lower(), str(u.is_active).lower(), str(u.mfa_enabled).lower(), u.created_at.isoformat()])

    return StreamingResponse(
        io.BytesIO(buf.getvalue().encode()),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=users.csv"},
    )


@router.post("/import")
def import_users_csv(
    request: Request,
    file: UploadFile,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    _require_enabled()
    cfg = get_settings()

    raw = file.file.read(MAX_IMPORT_BYTES + 1)
    if len(raw) > MAX_IMPORT_BYTES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="CSV file must be under 1MB")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="CSV file must be UTF-8 encoded")

    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="CSV file is empty")
    fields = {(f or "").strip().lower(): f for f in reader.fieldnames}
    if "username" not in fields or "password" not in fields:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="CSV must have 'username' and 'password' columns")

    rows = list(reader)
    if len(rows) > MAX_IMPORT_ROWS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"CSV must have at most {MAX_IMPORT_ROWS} rows")

    existing_usernames = {u for (u,) in db.query(User.username).all()}
    existing_emails = {e for (e,) in db.query(User.email).filter(User.email.is_not(None)).all()}
    created = []
    errors = []

    for idx, row in enumerate(rows, start=2):  # row 1 is the header
        username = (row.get(fields["username"]) or "").strip()
        password = row.get(fields["password"]) or ""
        email = ((row.get(fields.get("email", "")) or "").strip().lower() or None) if "email" in fields else None
        is_admin_val = (row.get(fields.get("is_admin", "")) or "").strip().lower() if "is_admin" in fields else ""
        is_admin_flag = is_admin_val in _TRUE_STRINGS

        if not username or len(username) < 3 or len(username) > 64:
            errors.append({"row": idx, "username": username, "error": "Username must be 3-64 characters"})
            continue
        if username in existing_usernames:
            errors.append({"row": idx, "username": username, "error": "Username already taken"})
            continue
        if email and email in existing_emails:
            errors.append({"row": idx, "username": username, "error": "Email already in use"})
            continue
        pw_errors = validate_password(password, cfg)
        if pw_errors:
            errors.append({"row": idx, "username": username, "error": " ".join(pw_errors)})
            continue

        user = User(username=username, email=email, password_hash=hash_password(password), is_admin=is_admin_flag)
        db.add(user)
        existing_usernames.add(username)
        if email:
            existing_emails.add(email)
        created.append(username)

    db.commit()
    log_event(
        db,
        "ADMIN_USER_CREATED",
        request=request,
        user_id=admin.id,
        detail=f"csv import: created={len(created)} errors={len(errors)}",
    )
    return {"created": created, "errors": errors}


@router.post("/batch-delete")
def batch_delete_users(payload: BatchIds, request: Request, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    _require_enabled()
    ids = [i for i in payload.ids if i != admin.id]
    targets = db.query(User).filter(User.id.in_(ids)).all()
    deleted_ids = [t.id for t in targets]
    usernames = [t.username for t in targets]

    if deleted_ids:
        db.query(FileObject).filter(FileObject.owner_id.in_(deleted_ids)).update({"owner_id": None}, synchronize_session=False)
        db.query(FileShare).filter(FileShare.recipient_id.in_(deleted_ids)).delete(synchronize_session=False)
        db.query(FileShare).filter(FileShare.owner_id.in_(deleted_ids)).delete(synchronize_session=False)
        db.query(ApiKey).filter(ApiKey.user_id.in_(deleted_ids)).delete(synchronize_session=False)
        db.query(User).filter(User.id.in_(deleted_ids)).delete(synchronize_session=False)
        db.commit()
        log_event(
            db,
            "ADMIN_USER_DELETED",
            request=request,
            user_id=admin.id,
            detail=f"batch deleted {len(deleted_ids)} user(s): {','.join(usernames)}",
        )

    skipped = [i for i in payload.ids if i not in deleted_ids]
    return {"deleted": len(deleted_ids), "skipped": skipped}


@router.patch("/{user_id}", response_model=UserSummary)
def update_user(user_id: str, payload: AdminUpdateUser, request: Request, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    _require_enabled()
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if payload.username is not None and payload.username != target.username:
        if db.query(User).filter(User.username == payload.username, User.id != target.id).first():
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already taken")
        old_username = target.username
        target.username = payload.username
        log_event(db, "ADMIN_USER_RENAMED", request=request, user_id=admin.id, detail=f"{old_username} -> {payload.username}")
    if "email" in payload.model_fields_set:
        email = (payload.email or "").strip().lower() or None
        if email and db.query(User).filter(User.email == email, User.id != target.id).first():
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already in use")
        target.email = email
    if payload.is_admin is not None:
        if target.id == admin.id and not payload.is_admin:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot remove your own admin privileges")
        target.is_admin = payload.is_admin
    if payload.is_active is not None:
        if target.id == admin.id and not payload.is_active:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot deactivate your own account")
        target.is_active = payload.is_active

    db.commit()
    db.refresh(target)
    log_event(db, "ADMIN_USER_UPDATED", request=request, user_id=admin.id, detail=f"target={target.username}")
    return target


@router.post("/{user_id}/reset-password")
def reset_password(user_id: str, payload: AdminResetPassword, request: Request, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    _require_enabled()
    cfg = get_settings()
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    errors = validate_password(payload.new_password, cfg)
    if errors:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=" ".join(errors))

    target.password_hash = hash_password(payload.new_password)
    target.token_version += 1
    db.commit()
    log_event(db, "ADMIN_PASSWORD_RESET", request=request, user_id=admin.id, detail=f"target={target.username}")
    return {"ok": True}


@router.post("/{user_id}/mfa-reset")
def admin_reset_mfa(user_id: str, request: Request, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    """Turns MFA off for a user who lost their authenticator device. They'll
    need to set it up again from scratch - there's no way to recover the old
    secret, by design."""
    _require_enabled()
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    target.mfa_enabled = False
    target.mfa_secret = None
    target.mfa_backup_codes = None
    db.commit()
    log_event(db, "ADMIN_MFA_RESET", request=request, user_id=admin.id, detail=f"target={target.username}")
    return {"ok": True}


@router.delete("/{user_id}")
def delete_user(user_id: str, request: Request, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    _require_enabled()
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if target.id == admin.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot delete your own account here")

    db.query(FileObject).filter(FileObject.owner_id == target.id).update({"owner_id": None})
    db.query(FileShare).filter(FileShare.recipient_id == target.id).delete()
    db.query(FileShare).filter(FileShare.owner_id == target.id).delete()
    db.query(ApiKey).filter(ApiKey.user_id == target.id).delete()
    username = target.username
    db.delete(target)
    db.commit()
    log_event(db, "ADMIN_USER_DELETED", request=request, user_id=admin.id, detail=f"target={username}")
    return {"ok": True}
