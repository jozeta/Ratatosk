"""User lifecycle rules shared by every endpoint that deletes, demotes, or
deactivates accounts. The same cascade used to exist in three places that had
drifted apart (ARCH-003): only one refused to delete the last admin
(BUG-003), and none cleared server-held share keys (SEC-018)."""
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.api_key import ApiKey
from app.models.file import FileObject
from app.models.file_share import FileShare
from app.models.ops import LoginThrottle
from app.models.password_reset_token import PasswordResetToken
from app.models.user import User


def active_admin_count(db: Session, excluding: list[str] | None = None) -> int:
    q = db.query(User).filter(User.is_admin == True, User.is_active == True)  # noqa: E712
    if excluding:
        q = q.filter(User.id.notin_(excluding))
    return q.count()


def assert_not_last_admin(db: Session, user_ids: list[str], action: str) -> None:
    """Refuse an action that would leave the instance with no active admin."""
    affected_admins = db.query(User).filter(User.id.in_(user_ids), User.is_admin == True, User.is_active == True).count()  # noqa: E712
    if affected_admins and active_admin_count(db, excluding=user_ids) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot {action}: that would leave no active administrator",
        )


def release_unneeded_share_keys(db: Session, file_ids: set[str]) -> None:
    """Drop the server-held decryption key of any file that no longer has a
    legacy share needing it (end-to-end shares never use it)."""
    if not file_ids:
        return
    still_shared = {
        fid for (fid,) in db.query(FileShare.file_id)
        .filter(FileShare.file_id.in_(file_ids), FileShare.wrapped_key.is_(None)).distinct()
    }
    orphaned = file_ids - still_shared
    if orphaned:
        db.query(FileObject).filter(FileObject.id.in_(orphaned)).update(
            {"shared_decryption_key": None}, synchronize_session=False
        )


def delete_users(db: Session, user_ids: list[str]) -> list[str]:
    """Delete accounts. Their files are orphaned, not deleted, so links that
    were already handed out keep working. Returns the deleted usernames."""
    if not user_ids:
        return []
    assert_not_last_admin(db, user_ids, "delete this account")
    users = db.query(User).filter(User.id.in_(user_ids)).all()
    ids = [u.id for u in users]
    names = [u.username for u in users]
    affected_files = {
        fid for (fid,) in db.query(FileShare.file_id).filter(
            (FileShare.recipient_id.in_(ids)) | (FileShare.owner_id.in_(ids))
        )
    }
    # Request-link submissions are encrypted to the deleted user's key - no one
    # else can ever open them, so they go too, along with the links.
    from app.models.upload_request import UploadRequest
    from app.services.files import delete_files

    delete_files(db, db.query(FileObject).filter(FileObject.owner_id.in_(ids), FileObject.request_id.is_not(None),
                                                 FileObject.is_deleted == False).all())  # noqa: E712
    db.query(UploadRequest).filter(UploadRequest.owner_id.in_(ids)).delete(synchronize_session=False)
    db.query(FileObject).filter(FileObject.owner_id.in_(ids)).update({"owner_id": None}, synchronize_session=False)
    db.query(FileShare).filter(FileShare.recipient_id.in_(ids)).delete(synchronize_session=False)
    db.query(FileShare).filter(FileShare.owner_id.in_(ids)).delete(synchronize_session=False)
    db.query(ApiKey).filter(ApiKey.user_id.in_(ids)).delete(synchronize_session=False)
    db.query(PasswordResetToken).filter(PasswordResetToken.user_id.in_(ids)).delete(synchronize_session=False)
    db.query(LoginThrottle).filter(LoginThrottle.user_id.in_(ids)).delete(synchronize_session=False)
    release_unneeded_share_keys(db, affected_files)
    db.query(User).filter(User.id.in_(ids)).delete(synchronize_session=False)
    db.commit()
    return names
