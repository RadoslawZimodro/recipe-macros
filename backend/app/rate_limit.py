"""A tiny in-memory, per-key sliding-window rate limiter for the login endpoint.

Deliberately dependency-free: it only has to blunt password brute-forcing. State is
process-local, so it resets on restart and is not shared between workers (run a single
uvicorn worker, or move the counters to Redis before scaling out).
"""

import threading
import time

from fastapi import HTTPException, status

from app.config import get_settings

_lock = threading.Lock()
# key -> monotonic timestamps of attempts still inside the current window.
_hits: dict[str, list[float]] = {}


def check_and_increment(key: str) -> None:
    """Record an attempt for `key`; raise 429 if it exceeds the configured limit."""
    settings = get_settings()
    window = settings.login_rate_limit_window_sec
    limit = settings.login_rate_limit_attempts
    now = time.monotonic()
    with _lock:
        recent = [t for t in _hits.get(key, []) if t > now - window]
        recent.append(now)
        _hits[key] = recent
        if len(recent) > limit:
            retry_after = max(1, int(window - (now - recent[0])))
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many login attempts. Try again later.",
                headers={"Retry-After": str(retry_after)},
            )


def reset(key: str) -> None:
    """Clear a key's counter, called after a successful login so earlier typos don't count."""
    with _lock:
        _hits.pop(key, None)


def clear() -> None:
    """Wipe all counters (used by tests to isolate cases)."""
    with _lock:
        _hits.clear()
