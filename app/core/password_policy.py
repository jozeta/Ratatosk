import re

SPECIAL_CHARS = re.compile(r"[!\"#$%&'()*+,\-./:;<=>?@\[\\\]^_`{|}~]")


def validate_password(password: str, cfg: dict) -> list[str]:
    """Returns a list of human-readable policy violations (empty if valid)."""
    errors = []
    min_len = cfg.get("password_min_length", 8)
    if len(password) < min_len:
        errors.append(f"Password must be at least {min_len} characters long.")
    if cfg.get("password_require_uppercase") and not re.search(r"[A-Z]", password):
        errors.append("Password must contain an uppercase letter.")
    if cfg.get("password_require_lowercase") and not re.search(r"[a-z]", password):
        errors.append("Password must contain a lowercase letter.")
    if cfg.get("password_require_number") and not re.search(r"[0-9]", password):
        errors.append("Password must contain a number.")
    if cfg.get("password_require_special") and not SPECIAL_CHARS.search(password):
        errors.append("Password must contain a special character.")
    return errors
