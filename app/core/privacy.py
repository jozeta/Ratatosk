"""Uploader anonymity helpers: header sanitization, IP masking, timestamp fuzzing."""
import datetime
import ipaddress

from fastapi import Request

# Headers that could deanonymize an uploader/downloader; never forwarded to
# internal handlers or persisted verbatim.
SENSITIVE_HEADERS = {"x-forwarded-for", "x-real-ip", "client-ip", "referer", "user-agent", "cf-connecting-ip"}


def get_client_ip(request: Request) -> str | None:
    """Best-effort client IP. Deliberately ignores X-Forwarded-For / X-Real-IP
    to avoid trusting spoofable headers; uses the raw socket peer only."""
    client = request.client
    return client.host if client else None


def mask_ip(ip: str | None, level: str) -> str | None:
    """level: 'none' -> null, 'masked' -> subnet-truncated, 'full' -> untouched."""
    if level == "none" or ip is None:
        return None
    if level == "full":
        return ip
    # masked
    try:
        addr = ipaddress.ip_address(ip)
        if addr.version == 4:
            octets = ip.split(".")
            return ".".join(octets[:2] + ["0", "0"])
        else:
            network = ipaddress.ip_network(f"{ip}/64", strict=False)
            return str(network.network_address)
    except ValueError:
        return None


def fuzz_timestamp(ts: datetime.datetime, mode: str) -> datetime.datetime:
    """mode: 'none' | 'hour' | 'day'."""
    if mode == "hour":
        return ts.replace(minute=0, second=0, microsecond=0)
    if mode == "day":
        return ts.replace(hour=0, minute=0, second=0, microsecond=0)
    return ts


def sanitize_user_agent(raw: str | None, zero_log: bool) -> str | None:
    if zero_log or raw is None:
        return None
    return raw[:256]
