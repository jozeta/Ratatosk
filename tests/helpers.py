"""Shared test helpers (imported as tests.helpers - not from conftest, since
there is more than one conftest.py in the tree)."""


def make_user(db, username, password, is_admin=False, email=None):
    from app.core.security import hash_password
    from app.models.user import User

    user = User(username=username, password_hash=hash_password(password), is_admin=is_admin, email=email)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
