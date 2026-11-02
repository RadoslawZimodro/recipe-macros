import time

from redis import Redis


class RateLimitExceeded(Exception):
    def __init__(self, retry_after: int):
        super().__init__("rate limit exceeded")
        self.retry_after = retry_after


def check_rate_limit(client: Redis, key: str, limit: int, window_sec: int = 60) -> None:
    """Fixed-window counter in Redis: allow `limit` calls per `window_sec` for `key`.

    Unlike the in-memory login limiter this is shared by all workers. INCR and EXPIRE run in
    one transaction (MULTI/EXEC), so a crash cannot leave a counter without an expiry.
    """
    now = time.time()
    bucket = int(now // window_sec)
    redis_key = f"ratelimit:{key}:{bucket}"
    with client.pipeline(transaction=True) as pipe:
        pipe.incr(redis_key)
        pipe.expire(redis_key, window_sec + 1)
        count, _ = pipe.execute()
    if count > limit:
        raise RateLimitExceeded(retry_after=max(1, int(window_sec - (now % window_sec))))
