"""SSRF protection and limits of the page fetcher. No real network: DNS is faked and the HTTP
layer is httpx2.MockTransport, which sees exactly what would be sent to the pinned IP."""

import gzip
import ipaddress

import httpx2
import pytest

from app.config import get_settings
from app.services.safe_fetch import (
    FetchedPage,
    FetchError,
    is_public_ip,
    resolve_public,
    safe_get,
    system_resolver,
)

PUBLIC_IP = "93.184.216.34"
HTML = {"content-type": "text/html; charset=utf-8"}


def dns(mapping):
    def resolver(host, port):
        try:
            ipaddress.ip_address(host)
            return [host]  # an IP literal resolves to itself, like in the real resolver
        except ValueError:
            pass
        if host not in mapping:
            raise FetchError("dns_failure", "The host name could not be resolved.")
        return mapping[host]

    return resolver


def get(url, handler, mapping=None, **kwargs):
    """Run safe_get against a handler; returns (page, list of requests the handler saw)."""
    seen = []

    def wrapped(request):
        seen.append(request)
        return handler(request)

    mapping = mapping if mapping is not None else {"example.com": [PUBLIC_IP]}
    kwargs.setdefault("accept", "text/html")
    page = safe_get(url, resolver=dns(mapping), transport=httpx2.MockTransport(wrapped), **kwargs)
    return page, seen


def ok(body=b"<html>ok</html>", headers=HTML):
    return lambda request: httpx2.Response(200, headers=headers, content=body)


# --- which addresses count as public ---
@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1", "127.1.2.3", "0.0.0.0", "10.0.0.1", "172.16.5.4", "172.31.255.255",
        "192.168.1.1", "169.254.169.254",  # cloud metadata endpoint
        "100.64.0.1",  # carrier-grade NAT
        "224.0.0.1", "240.0.0.1", "255.255.255.255", "192.0.2.1", "198.51.100.7",
        "::1", "::", "fe80::1", "fc00::1", "fd12:3456::1", "ff02::1",
        "::ffff:127.0.0.1", "::ffff:10.0.0.1", "::ffff:169.254.169.254",  # IPv4 in IPv6
        "64:ff9b::7f00:1", "2002:7f00:1::", "2001:0:4136:e378:8000:63bf:3fff:fdd2",
        "not-an-ip", "",
    ],
)  # fmt: skip
def test_internal_addresses_are_not_public(address):
    assert is_public_ip(address) is False


@pytest.mark.parametrize("address", [PUBLIC_IP, "8.8.8.8", "1.1.1.1", "2606:4700:4700::1111"])
def test_public_addresses_are_public(address):
    assert is_public_ip(address) is True


def test_one_internal_address_among_public_ones_blocks_the_host():
    with pytest.raises(FetchError) as exc:
        resolve_public("example.com", 443, lambda h, p: [PUBLIC_IP, "10.0.0.5"])

    assert exc.value.code == "blocked_address"


def test_empty_resolution_is_a_dns_failure():
    with pytest.raises(FetchError) as exc:
        resolve_public("example.com", 443, lambda h, p: [])

    assert exc.value.code == "dns_failure"


# --- literals and tricks, resolved by the real system resolver (nothing is contacted) ---
@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://localhost/",
        "http://localhost./",
        "http://[::1]/",
        "http://2130706433/",  # 127.0.0.1 as one decimal number
        "http://0x7f.1/",  # hexadecimal part
        "http://0177.0.0.1/",  # octal part
        "http://127.1/",  # shortened
        "http://169.254.169.254/latest/meta-data/",
        "http://10.1.2.3/admin",
        "http://[::ffff:127.0.0.1]/",
    ],
)
def test_loopback_and_private_literals_never_reach_the_network(url):
    def handler(request):  # pragma: no cover - must not be called
        raise AssertionError("a request was sent to an internal address")

    with pytest.raises(FetchError) as exc:
        safe_get(
            url,
            accept="text/html",
            resolver=system_resolver,
            transport=httpx2.MockTransport(handler),
        )

    assert exc.value.code in {"blocked_address", "dns_failure"}


def test_internal_name_is_blocked_before_connecting():
    page = None
    with pytest.raises(FetchError) as exc:
        page, seen = get(
            "https://intranet.example/", ok(), mapping={"intranet.example": ["192.168.0.10"]}
        )

    assert exc.value.code == "blocked_address"
    assert page is None


# --- the connection is pinned to the checked IP ---
def test_https_request_goes_to_the_checked_ip_with_name_for_tls_and_host_header():
    page, seen = get("https://example.com/przepis?id=7", ok())

    assert len(seen) == 1
    request = seen[0]
    assert request.url.host == PUBLIC_IP  # connect to the IP we validated
    assert request.url.path == "/przepis" and request.url.query == b"id=7"
    assert request.headers["host"] == "example.com"
    assert request.extensions["sni_hostname"] == "example.com"  # certificate checked for the name
    assert page.body == b"<html>ok</html>"
    assert page.url == "https://example.com/przepis?id=7"


def test_http_request_keeps_the_host_header_and_has_no_sni():
    _, seen = get("http://example.com/a", ok())

    assert seen[0].url.host == PUBLIC_IP
    assert seen[0].headers["host"] == "example.com"
    assert "sni_hostname" not in seen[0].extensions


def test_ipv6_address_is_bracketed_in_the_pinned_url():
    _, seen = get("https://example.com/", ok(), mapping={"example.com": ["2606:4700:4700::1111"]})

    assert seen[0].url.host == "2606:4700:4700::1111"


def test_identifies_itself_and_sends_no_cookies_or_proxies():
    _, seen = get("https://example.com/", ok())

    assert seen[0].headers["user-agent"] == get_settings().fetch_user_agent
    assert "RecipeMacrosBot" in seen[0].headers["user-agent"]
    assert "cookie" not in seen[0].headers and "authorization" not in seen[0].headers


def test_falls_back_to_the_next_address_when_connecting_fails():
    attempts = []

    def handler(request):
        attempts.append(request.url.host)
        if request.url.host == "93.184.216.35":
            raise httpx2.ConnectError("unreachable")
        return httpx2.Response(200, headers=HTML, content=b"fine")

    page, _ = get(
        "https://example.com/", handler, mapping={"example.com": ["93.184.216.35", PUBLIC_IP]}
    )

    assert attempts == ["93.184.216.35", PUBLIC_IP]
    assert page.body == b"fine"


def test_unreachable_host_is_an_upstream_error():
    def handler(request):
        raise httpx2.ConnectTimeout("slow")

    with pytest.raises(FetchError) as exc:
        get("https://example.com/", handler)

    assert exc.value.code == "upstream_error"


# --- redirects: followed by us, validated at every hop ---
def redirect_to(location, status=302):
    return lambda request: httpx2.Response(status, headers={"location": location})


def test_relative_redirect_is_followed():
    def handler(request):
        if request.url.path == "/stary":
            return httpx2.Response(301, headers={"location": "/nowy"})
        return httpx2.Response(200, headers=HTML, content=b"new")

    page, seen = get("https://example.com/stary", handler)

    assert [r.url.path for r in seen] == ["/stary", "/nowy"]
    assert page.body == b"new"
    assert page.final_url == "https://example.com/nowy"
    assert page.url == "https://example.com/stary"


def test_redirect_to_another_public_host_is_resolved_and_pinned_again():
    def handler(request):
        if request.headers["host"] == "example.com":
            return httpx2.Response(302, headers={"location": "https://www.example.org/x"})
        return httpx2.Response(200, headers=HTML, content=b"org")

    mapping = {"example.com": [PUBLIC_IP], "www.example.org": ["8.8.8.8"]}
    page, seen = get("https://example.com/", handler, mapping=mapping)

    assert [(r.url.host, r.headers["host"]) for r in seen] == [
        (PUBLIC_IP, "example.com"),
        ("8.8.8.8", "www.example.org"),
    ]
    assert page.body == b"org"


@pytest.mark.parametrize(
    ("location", "mapping", "code"),
    [
        ("http://127.0.0.1/admin", {}, "blocked_address"),
        ("http://169.254.169.254/latest/meta-data/", {}, "blocked_address"),
        ("http://evil.example/", {"evil.example": ["10.0.0.7"]}, "blocked_address"),
        ("ftp://example.com/x", {}, "invalid_url"),
        ("file:///etc/passwd", {}, "invalid_url"),
        ("https://example.com:8443/x", {}, "invalid_url"),
        ("https://user:pw@example.com/x", {}, "invalid_url"),
        ("https://www.youtube.com/watch?v=abc", {}, "unsupported_site"),
    ],
)
def test_a_redirect_into_a_forbidden_place_is_refused(location, mapping, code):
    seen_hosts = []

    def handler(request):
        seen_hosts.append(request.headers["host"])
        return httpx2.Response(302, headers={"location": location})

    with pytest.raises(FetchError) as exc:
        get("https://example.com/", handler, mapping={"example.com": [PUBLIC_IP], **mapping})

    assert exc.value.code == code
    assert seen_hosts == ["example.com"]  # nothing was requested at the forbidden target


def test_redirect_loop_is_cut_after_the_limit():
    count = {"n": 0}

    def handler(request):
        count["n"] += 1
        return httpx2.Response(302, headers={"location": "/again"})

    with pytest.raises(FetchError) as exc:
        get("https://example.com/", handler)

    assert exc.value.code == "too_many_redirects"
    assert count["n"] == get_settings().fetch_max_redirects + 1


def test_redirect_without_location_is_an_error():
    with pytest.raises(FetchError) as exc:
        get("https://example.com/", lambda request: httpx2.Response(302))

    assert exc.value.code == "upstream_error"


# --- status codes ---
@pytest.mark.parametrize(
    ("status", "code"),
    [
        (401, "access_denied"),
        (402, "access_denied"),
        (403, "access_denied"),
        (404, "not_found"),
        (410, "not_found"),
        (429, "upstream_error"),
        (500, "upstream_error"),
        (503, "upstream_error"),
        (418, "upstream_error"),
    ],
)
def test_error_statuses_map_to_stable_codes(status, code):
    with pytest.raises(FetchError) as exc:
        get("https://example.com/", lambda request: httpx2.Response(status, headers=HTML))

    assert exc.value.code == code


# --- content and size ---
@pytest.mark.parametrize(
    "content_type", ["application/pdf", "image/png", "application/json", "text/plain"]
)
def test_only_html_is_accepted(content_type):
    with pytest.raises(FetchError) as exc:
        get("https://example.com/", ok(headers={"content-type": content_type}))

    assert exc.value.code == "not_html"


@pytest.mark.parametrize(
    "content_type", ["text/html", "TEXT/HTML; charset=ISO-8859-2", "application/xhtml+xml"]
)
def test_html_types_are_accepted(content_type):
    page, _ = get("https://example.com/", ok(headers={"content-type": content_type}))

    assert page.body == b"<html>ok</html>"


def test_missing_content_type_is_tolerated():
    page, _ = get("https://example.com/", ok(headers={}))

    assert page.content_type == ""


def test_body_over_the_limit_is_rejected(monkeypatch):
    monkeypatch.setattr(get_settings(), "fetch_max_bytes", 1000)

    with pytest.raises(FetchError) as exc:
        get("https://example.com/", ok(body=b"x" * 1001))

    assert exc.value.code == "too_large"


def test_body_exactly_at_the_limit_is_accepted(monkeypatch):
    monkeypatch.setattr(get_settings(), "fetch_max_bytes", 1000)

    page, _ = get("https://example.com/", ok(body=b"x" * 1000))

    assert len(page.body) == 1000


def test_declared_content_length_over_the_limit_is_rejected_early(monkeypatch):
    monkeypatch.setattr(get_settings(), "fetch_max_bytes", 1000)
    headers = {**HTML, "content-length": "5000"}

    class Endless(httpx2.SyncByteStream):
        def __iter__(self):  # pragma: no cover - must not be read
            raise AssertionError("the body was read although the header was over the limit")
            yield b""

    with pytest.raises(FetchError) as exc:
        get(
            "https://example.com/",
            lambda request: httpx2.Response(200, headers=headers, stream=Endless()),
        )

    assert exc.value.code == "too_large"


def test_size_is_counted_after_decompression_so_a_gzip_bomb_is_stopped(monkeypatch):
    monkeypatch.setattr(get_settings(), "fetch_max_bytes", 100_000)
    bomb = gzip.compress(b"a" * 50_000_000)  # a few KB on the wire, 50 MB when unpacked
    assert len(bomb) < 100_000

    def handler(request):
        headers = {**HTML, "content-encoding": "gzip"}
        return httpx2.Response(200, headers=headers, stream=httpx2.ByteStream(bomb))

    with pytest.raises(FetchError) as exc:
        get("https://example.com/", handler)

    assert exc.value.code == "too_large"


def test_gzip_pages_are_decoded():
    def handler(request):
        headers = {**HTML, "content-encoding": "gzip"}
        return httpx2.Response(
            200, headers=headers, stream=httpx2.ByteStream(gzip.compress(b"<html>zip</html>"))
        )

    page, _ = get("https://example.com/", handler)

    assert page.body == b"<html>zip</html>"


def test_truncate_mode_returns_the_first_bytes_instead_of_failing():
    page, _ = get("https://example.com/", ok(body=b"0123456789"), max_bytes=4, truncate=True)

    assert page.body == b"0123"


# --- time ---
def test_read_timeout_is_a_timeout_error():
    def handler(request):
        raise httpx2.ReadTimeout("slow")

    with pytest.raises(FetchError) as exc:
        get("https://example.com/", handler)

    assert exc.value.code == "timeout"


def test_total_time_budget_is_enforced(monkeypatch):
    monkeypatch.setattr(get_settings(), "fetch_total_timeout_sec", -1)

    with pytest.raises(FetchError) as exc:
        get("https://example.com/", ok())

    assert exc.value.code == "timeout"


# --- other ---
def test_unresolvable_host_is_a_dns_failure():
    with pytest.raises(FetchError) as exc:
        get("https://nie-istnieje.example/", ok(), mapping={})

    assert exc.value.code == "dns_failure"


def test_non_2xx_can_be_returned_to_the_caller_for_robots_txt():
    page, _ = get(
        "https://example.com/robots.txt",
        lambda request: httpx2.Response(404, headers=HTML, content=b"missing"),
        raise_on_status=False,
    )

    assert isinstance(page, FetchedPage) and page.status == 404 and page.body == b""


def test_invalid_start_url_is_reported_as_fetch_error():
    with pytest.raises(FetchError) as exc:
        get("ftp://example.com/", ok())

    assert exc.value.code == "invalid_url"
