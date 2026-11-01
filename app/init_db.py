"""One-time initializer: creates tables, seeds default system settings and a
default admin account. Safe to re-run (idempotent)."""
import secrets

from app.core.config import settings as static_settings
from app.core.database import SessionLocal
from app.core.dynamic_settings import get_or_create_settings
from app.core.migrate import run_migrations
from app.core.security import hash_password
from app.models.user import User


def main():
    run_migrations()

    db = SessionLocal()
    try:
        get_or_create_settings(db)

        existing_admin = db.query(User).filter(User.username == static_settings.default_admin_username).first()
        if existing_admin is None:
            password = static_settings.default_admin_password or secrets.token_urlsafe(16)
            admin = User(
                username=static_settings.default_admin_username,
                password_hash=hash_password(password),
                is_admin=True,
            )
            db.add(admin)
            db.commit()
            print("=" * 60)
            print("Created default admin account:")
            print(f"  username: {static_settings.default_admin_username}")
            print(f"  password: {password}")
            print("Store this password securely - it will not be shown again.")
            print("=" * 60)
        else:
            print(f"Admin account '{static_settings.default_admin_username}' already exists; skipping.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
