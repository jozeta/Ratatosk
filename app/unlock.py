"""Out-of-band account unlock (SEC-012), for when every admin is locked out:

    python -m app.unlock <username>      # clear that account's lockouts
    python -m app.unlock --all           # clear every login lockout
"""
import sys

from app.core.database import SessionLocal
from app.core.migrate import run_migrations
from app.models.user import User
from app.services.lockout import clear_login_throttles


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    run_migrations()
    db = SessionLocal()
    try:
        if argv[0] == "--all":
            n = clear_login_throttles(db)
            db.query(User).update({"failed_login_attempts": 0, "login_locked_until": None})
            db.commit()
            print(f"Cleared {n} lockout record(s) for all accounts.")
            return 0
        user = db.query(User).filter(User.username == argv[0]).first()
        if user is None:
            print(f"No such user: {argv[0]}", file=sys.stderr)
            return 1
        n = clear_login_throttles(db, user.id)
        user.failed_login_attempts = 0
        user.login_locked_until = None
        db.commit()
        print(f"Unlocked '{user.username}' ({n} lockout record(s) cleared).")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
