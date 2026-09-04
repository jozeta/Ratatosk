from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dynamic_settings import get_settings
from app.core.security import generate_api_key, require_user
from app.models.api_key import ApiKey
from app.models.user import User
from app.schemas.api_keys import ApiKeySummary, CreateApiKeyRequest, CreateApiKeyResponse
from app.services.audit_service import log_event

router = APIRouter(prefix="/api/account/api-keys", tags=["api-keys"])


def _require_enabled():
    if not get_settings()["enable_api_keys"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="API keys are disabled in settings")


@router.get("", response_model=list[ApiKeySummary])
def list_keys(db: Session = Depends(get_db), user: User = Depends(require_user)):
    _require_enabled()
    return db.query(ApiKey).filter(ApiKey.user_id == user.id).order_by(ApiKey.created_at.desc()).all()


@router.post("", response_model=CreateApiKeyResponse)
def create_key(payload: CreateApiKeyRequest, request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)):
    _require_enabled()
    raw, key_hash, prefix = generate_api_key()
    record = ApiKey(user_id=user.id, name=payload.name, key_hash=key_hash, prefix=prefix, scope=payload.scope)
    db.add(record)
    db.commit()
    db.refresh(record)
    log_event(db, "API_KEY_CREATED", request=request, user_id=user.id, detail=f"name={payload.name} scope={payload.scope}")
    return CreateApiKeyResponse(id=record.id, name=record.name, key=raw)


@router.delete("/{key_id}")
def revoke_key(key_id: str, request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)):
    record = db.get(ApiKey, key_id)
    if record is None or record.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")
    name = record.name
    db.delete(record)
    db.commit()
    log_event(db, "API_KEY_REVOKED", request=request, user_id=user.id, detail=f"name={name}")
    return {"ok": True}
