"""Fetching a recipe page politely: robots.txt, cache, SSRF-safe transport."""

from urllib.parse import urlsplit

import httpx2

from app.config import get_settings
from app.services.page_cache import PageCache
from app.services.robots import MAX_ROBOTS_BYTES, RobotsRules, is_allowed
from app.services.safe_fetch import (
    FetchedPage,
    FetchError,
    Resolver,
    safe_get,
    system_resolver,
)

# Errors that mean "this address must not be contacted at all": not a robots.txt problem.
_FATAL_FOR_ROBOTS = frozenset({"invalid_url", "unsupported_site", "blocked_address", "dns_failure"})


class PageFetcher:
    def __init__(
        self,
        cache: PageCache | None = None,
        *,
        resolver: Resolver = system_resolver,
        transport: httpx2.BaseTransport | None = None,
    ):
        self._cache = cache
        self._resolver = resolver
        self._transport = transport

    @property
    def _product_token(self) -> str:
        return get_settings().fetch_user_agent.split("/", 1)[0]

    def fetch(self, url: str, *, refresh: bool = False) -> FetchedPage:
        """Fetch `url` (already normalized). `refresh=True` skips the cache read."""
        if self._cache is not None and not refresh:
            cached = self._cache.get_page(url)
            if cached is not None:
                return cached

        page = safe_get(
            url,
            accept="text/html,application/xhtml+xml;q=0.9,*/*;q=0.1",
            before_hop=self._check_robots,
            resolver=self._resolver,
            transport=self._transport,
        )
        if self._cache is not None:
            self._cache.set_page(url, page)
        return page

    def fetch_image(self, url: str, *, timeout: float | None = None) -> FetchedPage:
        """Fetch one picture (step or cover): SSRF-safe transport, its own size limit, no cache.
        The type is NOT checked here (a header can lie); see media.detect_image.
        robots.txt is not consulted: the page was allowed and its pictures are part of it."""
        return safe_get(
            url,
            accept="image/jpeg,image/png,image/webp,image/gif;q=0.9",
            content_types=None,
            max_bytes=get_settings().image_max_bytes,
            resolver=self._resolver,
            transport=self._transport,
            total_timeout=timeout,
        )

    def _check_robots(self, hop_url: str) -> None:
        parts = urlsplit(hop_url)
        origin = f"{parts.scheme}://{parts.netloc}"

        rules = self._cache.get_robots(origin) if self._cache else None
        if rules is None:
            rules = self._load_robots(origin)
            if self._cache is not None:
                self._cache.set_robots(origin, rules)

        if rules.status == "error":
            raise FetchError(
                "robots_unavailable",
                "The site's robots.txt could not be read, so automated access is not assumed "
                "to be allowed. Try again later.",
            )
        if not is_allowed(rules, hop_url, self._product_token):
            raise FetchError(
                "robots_disallowed",
                "The site's robots.txt does not allow automated access to this page.",
            )

    def _load_robots(self, origin: str) -> RobotsRules:
        try:
            page = safe_get(
                origin + "/robots.txt",
                accept="text/plain,*/*;q=0.1",
                content_types=None,
                max_bytes=MAX_ROBOTS_BYTES,
                truncate=True,
                raise_on_status=False,
                resolver=self._resolver,
                transport=self._transport,
            )
        except FetchError as exc:
            if exc.code in _FATAL_FOR_ROBOTS:
                raise
            return RobotsRules("error")  # timeout, network failure, ...: assume disallowed

        if 200 <= page.status < 300:
            return RobotsRules("ok", page.body.decode("utf-8", errors="replace"))
        if 400 <= page.status < 500:
            return RobotsRules("missing")  # RFC 9309: no robots.txt means no restrictions
        return RobotsRules("error")  # 5xx and anything unexpected
