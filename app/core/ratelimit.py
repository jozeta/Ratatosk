"""Per-network rate limiting and privacy-preserving client network keys.

Buckets live in process memory only - nothing about a client's address is
ever written to disk for rate limiting. Keys are an HMAC of the *masked*
network (/24 for IPv4, /48 for IPv6) under the server secret, so even the
in-memory key isn't an address (SEC-011).
"""
import hashlib
import hmac
import ipaddress
import threading
import time

from fastapi import HTTPException, Request, status

from app.core.config import settings
from app.core.privacy import get_client_ip

_lock = threading.Lock()
_buckets: dict[tuple[str, str], tuple[float, float]] = {}  # (name, net) -> (tokens, last_refill)
_MAX_BUCKETS = 50_000


def network_key(request: Request | None) -> str:
    ip = get_client_ip(request) if request is not None else None
    net = "unknown"
    if ip:
        try:
            addr = ipaddress.ip_address(ip)
            prefix = 24 if addr.version == 4 else 48
            net = str(ipaddress.ip_network(f"{ip}/{prefix}", strict=False))
        except ValueError:
            net = "unknown"
    return hmac.new(settings.secret_key.encode(), net.encode(), hashlib.sha256).hexdigest()


def check_rate(request: Request, name: str, cfg: dict, cost: float = 1.0, per_minute: int | None = None) -> None:
    """Token bucket: `per_minute` tokens refilled continuously, burst of the
    same size. Raises 429 when exhausted."""
    if not cfg.get("rate_limit_enabled", True):
        return
    rate = float(per_minute or cfg.get("rate_limit_per_minute", 30))
    key = (name, network_key(request))
    now = time.monotonic()
    with _lock:
        tokens, last = _buckets.get(key, (rate, now))
        tokens = min(rate, tokens + (now - last) * rate / 60.0)
        if tokens < cost:
            _buckets[key] = (tokens, now)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests - please wait a minute and try again",
            )
        _buckets[key] = (tokens - cost, now)
        if len(_buckets) > _MAX_BUCKETS:
            # Bounded memory: drop the oldest half (an attacker cycling
            # networks can only ever evict buckets, never grow them unbounded).
            for k in sorted(_buckets, key=lambda k: _buckets[k][1])[: _MAX_BUCKETS // 2]:
                _buckets.pop(k, None)


def reset() -> None:
    with _lock:
        _buckets.clear()
