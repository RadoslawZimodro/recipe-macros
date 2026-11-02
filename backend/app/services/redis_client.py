from functools import lru_cache

from redis import Redis

from app.config import get_settings


@lru_cache
def get_redis() -> Redis:
    """One shared client (it owns a connection pool). Values are bytes, not decoded strings."""
    return Redis.from_url(get_settings().redis_url, socket_timeout=2, socket_connect_timeout=2)
