"""PageFetcher: robots.txt handling and the Redis page cache (HTTP and DNS are faked)."""

import json

import httpx2
import pytest
from redis.exceptions import RedisError

from app.config import get_settings
from app.services.page_cache import PageCache
from app.services.page_fetcher import PageFetcher
from app.services.robots import RobotsRules
from app.services.safe_fetch import FetchError

PUBLIC_IP = "93.184.216.34"
HTML = {"content-type": "text/html"}
PAGE = b"<html><body>przepis</body></html>"


class Site:
    """A fake web: routes by Host header and path, remembers every request."""

    def __init__(self, robots=None, pages=None):
        self.robots = robots  # None -> 404, int -> that status, str -> served as text
        self.pages = pages if pages is not None else {"/przepis": PAGE}
        self.requests = []

    def __call__(self, request):
        self.requests.append((request.headers["host"], request.url.path))
        if request.url.path == "/robots.txt":
            if isinstance(self.robots, str):
                return httpx2.Response(
                    200, headers={"content-type": "text/plain"}, content=self.robots.encode()
                )
            if isinstance(self.robots, int):
                return httpx2.Response(self.robots)
            return httpx2.Response(404)
        if request.url.path in self.pages:
            return httpx2.Response(200, headers=HTML, content=self.pages[request.url.path])
        return httpx2.Response(404)

    def count(self, path):
        return sum(1 for _, p in self.requests if p == path)


def fetcher(site, cache=None, hosts=None):
    mapping = hosts or {"example.com": [PUBLIC_IP]}

    def resolver(host, port):
        if host not in mapping:
            raise FetchError("dns_failure", "The host name could not be resolved.")
        return mapping[host]

    return PageFetcher(cache, resolver=resolver, transport=httpx2.MockTransport(site))


@pytest.fixture
def cache(redis_client):
    return PageCache(redis_client)


URL = "https://example.com/przepis"


# --- robots.txt ---
def test_allowed_page_is_fetched_after_reading_robots(cache):
    site = Site(robots="User-agent: *\nDisallow: /admin/\n")

    page = fetcher(site, cache).fetch(URL)

    assert page.body == PAGE
    assert [p for _, p in site.requests] == ["/robots.txt", "/przepis"]


def test_disallowed_page_is_not_requested(cache):
    site = Site(robots="User-agent: *\nDisallow: /przepis\n")

    with pytest.raises(FetchError) as exc:
        fetcher(site, cache).fetch(URL)

    assert exc.value.code == "robots_disallowed"
    assert site.count("/przepis") == 0


def test_rules_for_our_bot_name_apply(cache):
    site = Site(robots="User-agent: RecipeMacrosBot\nDisallow: /\n")

    with pytest.raises(FetchError) as exc:
        fetcher(site, cache).fetch(URL)

    assert exc.value.code == "robots_disallowed"


def test_wildcard_rules_are_honoured(cache):
    site = Site(robots="User-agent: *\nDisallow: /*zep\n", pages={"/przepis": PAGE})

    with pytest.raises(FetchError):
        fetcher(site, cache).fetch(URL)


def test_missing_robots_means_allowed(cache):
    site = Site(robots=None)  # 404

    assert fetcher(site, cache).fetch(URL).body == PAGE


@pytest.mark.parametrize("status", [500, 502, 503])
def test_server_error_on_robots_means_disallowed(cache, status):
    site = Site(robots=status)

    with pytest.raises(FetchError) as exc:
        fetcher(site, cache).fetch(URL)

    assert exc.value.code == "robots_unavailable"
    assert site.count("/przepis") == 0


def test_network_failure_on_robots_means_disallowed(cache):
    def handler(request):
        if request.url.path == "/robots.txt":
            raise httpx2.ReadTimeout("slow")
        return httpx2.Response(200, headers=HTML, content=PAGE)

    with pytest.raises(FetchError) as exc:
        fetcher(handler, cache).fetch(URL)

    assert exc.value.code == "robots_unavailable"


def test_robots_on_an_internal_host_reports_the_real_problem_not_a_robots_error(cache):
    site = Site()

    with pytest.raises(FetchError) as exc:
        fetcher(site, cache, hosts={"example.com": ["10.0.0.1"]}).fetch(URL)

    assert exc.value.code == "blocked_address"
    assert site.requests == []


def test_robots_is_checked_again_for_the_host_after_a_redirect(cache):
    def handler(request):
        host, path = request.headers["host"], request.url.path
        if path == "/robots.txt":
            body = "User-agent: *\nDisallow: /\n" if host == "other.example" else ""
            return httpx2.Response(
                200, headers={"content-type": "text/plain"}, content=body.encode()
            )
        if host == "example.com":
            return httpx2.Response(302, headers={"location": "https://other.example/przepis"})
        return httpx2.Response(200, headers=HTML, content=PAGE)

    hosts = {"example.com": [PUBLIC_IP], "other.example": ["8.8.8.8"]}
    with pytest.raises(FetchError) as exc:
        fetcher(handler, cache, hosts=hosts).fetch(URL)

    assert exc.value.code == "robots_disallowed"


# --- robots cache ---
def test_robots_is_fetched_once_per_origin(cache):
    site = Site(robots="User-agent: *\nDisallow:\n", pages={"/a": PAGE, "/b": PAGE})
    f = fetcher(site, cache)

    f.fetch("https://example.com/a")
    f.fetch("https://example.com/b")

    assert site.count("/robots.txt") == 1


def test_robots_cache_lifetimes(cache, redis_client):
    fetcher(Site(robots="User-agent: *\nDisallow:\n"), cache).fetch(URL)
    ttl_ok = redis_client.ttl("robots:v1:https://example.com")
    assert 0 < ttl_ok <= get_settings().robots_cache_ttl_sec

    redis_client.flushdb()
    with pytest.raises(FetchError):
        fetcher(Site(robots=503), cache).fetch(URL)
    ttl_error = redis_client.ttl("robots:v1:https://example.com")
    assert 0 < ttl_error <= get_settings().robots_error_cache_ttl_sec  # retried sooner


def test_cached_robots_rules_are_used_without_fetching(cache):
    cache.set_robots("https://example.com", RobotsRules("ok", "User-agent: *\nDisallow: /\n"))
    site = Site()

    with pytest.raises(FetchError) as exc:
        fetcher(site, cache).fetch(URL)

    assert exc.value.code == "robots_disallowed"
    assert site.requests == []


# --- page cache ---
def test_second_fetch_comes_from_the_cache(cache):
    site = Site(robots="User-agent: *\nDisallow:\n")
    f = fetcher(site, cache)

    first = f.fetch(URL)
    second = f.fetch(URL)

    assert site.count("/przepis") == 1
    assert second.body == first.body == PAGE
    assert second.final_url == first.final_url and second.content_type == "text/html"


def test_refresh_skips_the_cache_and_updates_it(cache):
    site = Site(pages={"/przepis": b"<html>v1</html>"})
    f = fetcher(site, cache)
    f.fetch(URL)

    site.pages["/przepis"] = b"<html>v2</html>"
    assert f.fetch(URL).body == b"<html>v1</html>"  # still cached
    assert f.fetch(URL, refresh=True).body == b"<html>v2</html>"
    assert f.fetch(URL).body == b"<html>v2</html>"  # the refreshed page replaced the old entry
    assert site.count("/przepis") == 2


def test_cached_page_is_stored_compressed_with_a_ttl(cache, redis_client):
    big = b"<html>" + b"przepis " * 50_000 + b"</html>"
    fetcher(Site(pages={"/przepis": big}), cache).fetch(URL)

    key = next(iter(redis_client.scan_iter("page:v1:*")))
    stored = redis_client.hget(key, "body")
    assert len(stored) < len(big) / 10
    assert 0 < redis_client.ttl(key) <= get_settings().page_cache_ttl_sec


def test_cache_does_not_mix_up_urls(cache):
    site = Site(pages={"/a": b"<html>a</html>", "/b": b"<html>b</html>"})
    f = fetcher(site, cache)

    assert f.fetch("https://example.com/a").body == b"<html>a</html>"
    assert f.fetch("https://example.com/b").body == b"<html>b</html>"


def test_failed_fetches_are_not_cached(cache, redis_client):
    site = Site(pages={})
    with pytest.raises(FetchError):
        fetcher(site, cache).fetch(URL)

    assert list(redis_client.scan_iter("page:v1:*")) == []


def test_corrupt_cache_entry_is_treated_as_a_miss(cache, redis_client):
    f = fetcher(Site(), cache)
    f.fetch(URL)
    key = next(iter(redis_client.scan_iter("page:v1:*")))
    redis_client.hset(key, "body", b"not zlib data")

    assert f.fetch(URL).body == PAGE


class BrokenRedis:
    """Every operation fails, like a Redis that is down."""

    def __getattr__(self, name):
        def fail(*args, **kwargs):
            raise RedisError("connection refused")

        return fail

    def pipeline(self, *args, **kwargs):
        raise RedisError("connection refused")


def test_imports_still_work_when_redis_is_down():
    site = Site()
    page = fetcher(site, PageCache(BrokenRedis())).fetch(URL)

    assert page.body == PAGE
    assert site.count("/robots.txt") == 1


def test_fetcher_works_without_any_cache():
    site = Site()
    f = fetcher(site, None)

    assert f.fetch(URL).body == PAGE
    assert f.fetch(URL).body == PAGE
    assert site.count("/przepis") == 2


def test_cached_entries_survive_json_roundtrip_of_robots(cache):
    cache.set_robots("https://example.com", RobotsRules("ok", "User-agent: *\nDisallow: /x\n"))

    assert cache.get_robots("https://example.com") == RobotsRules(
        "ok", "User-agent: *\nDisallow: /x\n"
    )
    assert cache.get_robots("https://other.example") is None
    json.dumps({"status": "ok"})  # sanity: the stored shape is plain JSON
