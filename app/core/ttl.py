import datetime

UNIT_SECONDS = {"m": 60, "h": 3600, "d": 86400}


def parse_ttl(code: str) -> datetime.timedelta:
    code = code.strip().lower()
    if len(code) < 2 or code[-1] not in UNIT_SECONDS:
        raise ValueError(f"Invalid TTL code: {code}")
    amount = int(code[:-1])
    return datetime.timedelta(seconds=amount * UNIT_SECONDS[code[-1]])


def is_allowed_ttl(code: str, allowed_csv: str) -> bool:
    allowed = {c.strip().lower() for c in allowed_csv.split(",") if c.strip()}
    return code.strip().lower() in allowed
