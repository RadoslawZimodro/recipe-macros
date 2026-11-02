"""Redis cache for fetched pages and robots.txt files.

A cache is an optimization, never a dependency: every Redis error is logged and treated as a
miss (or a skipped write), so imports keep working when Redis is down.
"""

import hashlib
import json
import logging
import zlib

from redis import Redis
from redis.exceptions import RedisError

from app.config import get_settings
from app.services.robots import RobotsRules
from app.services.safe_fetch import FetchedPage

logger = logging.getLogger(__name__)


class PageCache:
    def __init__(self, client: Redis):
        self._redis = client

    @staticmethod
    def _page_key(url: str) -> str:
        return "page:v1:" + hashlib.sha256(url.encode()).hexdigest()

    @staticmethod
    def _robots_key(origin: str) -> str:
        return "robots:v1:" + origin

    # --- pages: the whole HTML, compressed, so a parser change or the AI step (Step 4)
    # can reuse it without fetching the site again ---
    def get_page(self, url: str) -> FetchedPage | None:
        try:
            data = self._redis.hgetall(self._page_key(url))
            if not data:
                return None
            return FetchedPage(
                url=url,
                final_url=data[b"final_url"].decode(),
                status=int(data[b"status"]),
                content_type=data[b"content_type"].decode(),
                body=zlib.decompress(data[b"body"]),
            )
        except (RedisError, KeyError, ValueError, zlib.error):
            logger.warning("Page cache read failed for %s", url, exc_info=True)
            return None

    def set_page(self, url: str, page: FetchedPage) -> None:
        key = self._page_key(url)
        try:
            with self._redis.pipeline(transaction=True) as pipe:
                pipe.hset(
                    key,
                    mapping={
                        "final_url": page.final_url,
                        "status": page.status,
                        "content_type": page.content_type,
                        "body": zlib.compress(page.body, 6),
                    },
                )
                pipe.expire(key, get_settings().page_cache_ttl_sec)
                pipe.execute()
        except RedisError:
            logger.warning("Page cache write failed for %s", url, exc_info=True)

    # --- robots.txt: one entry per origin ---
    def get_robots(self, origin: str) -> RobotsRules | None:
        try:
            raw = self._redis.get(self._robots_key(origin))
            if raw is None:
                return None
            data = json.loads(raw)
            return RobotsRules(status=data["status"], body=data["body"])
        except (RedisError, KeyError, ValueError):
            logger.warning("Robots cache read failed for %s", origin, exc_info=True)
            return None

    def set_robots(self, origin: str, rules: RobotsRules) -> None:
        settings = get_settings()
        # An unreachable robots.txt is remembered briefly, so a short outage is not sticky.
        ttl = (
            settings.robots_error_cache_ttl_sec
            if rules.status == "error"
            else settings.robots_cache_ttl_sec
        )
        try:
            self._redis.set(
                self._robots_key(origin),
                json.dumps({"status": rules.status, "body": rules.body}),
                ex=ttl,
            )
        except RedisError:
            logger.warning("Robots cache write failed for %s", origin, exc_info=True)
