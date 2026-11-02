"""Fetching web pages on behalf of a user without becoming an SSRF proxy.

SSRF (server-side request forgery) is when a user makes OUR server request an address that
only the server can reach: localhost, the home or office network, cloud metadata services.
Defences, all in this module:

  * every address is resolved by us and REJECTED unless all of its IPs are public;
  * the connection goes to the IP we checked (the URL is rewritten to the IP, the original
    name is sent as the Host header and used for TLS), so DNS cannot answer differently
    between the check and the connection (DNS rebinding);
  * redirects are never followed by the HTTP library: each hop is validated and resolved
    again, at most `fetch_max_redirects` times;
  * no proxies from the environment (a proxy would receive the name, not our pinned IP);
  * response size is limited after decompression, and there is a total time budget.
"""

import ipaddress
import socket
import time
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import SplitResult, urljoin, urlunsplit

import httpx2

from app.config import get_settings
from app.services.urls import UrlError, validate_url

HTML_TYPES = frozenset({"text/html", "application/xhtml+xml"})
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_DEFAULT_PORTS = {"http": 80, "https": 443}
_MAX_CONNECT_ATTEMPTS = 3  # IPs tried when a host has several (e.g. IPv6 not routable)

# Ranges that embed or tunnel an IPv4 address (or are otherwise special) and that
# ipaddress.is_global does not reliably flag: reject them outright.
_BLOCKED_NETWORKS = tuple(
    ipaddress.ip_network(n)
    for n in (
        "64:ff9b::/96",  # NAT64: can embed a private IPv4
        "64:ff9b:1::/48",
        "2002::/16",  # 6to4
        "2001::/32",  # Teredo
    )
)


class FetchError(Exception):
    """A page could not be fetched. `code` is stable for API clients, `message` is for people."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class FetchedPage:
    url: str  # the address that was requested (normalized)
    final_url: str  # the address after redirects
    status: int
    content_type: str
    body: bytes


Resolver = Callable[[str, int], list[str]]


def system_resolver(host: str, port: int) -> list[str]:
    """Resolve with the operating system (IPv4 first); returns every address found."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError):
        raise FetchError("dns_failure", "The host name could not be resolved.") from None
    addresses = [str(info[4][0]).split("%", 1)[0] for info in infos]
    unique = list(dict.fromkeys(addresses))
    return sorted(unique, key=lambda a: ":" in a)  # stable: IPv4 before IPv6


def is_public_ip(value: str) -> bool:
    """True only for globally routable addresses (no loopback, private, link-local, CGNAT,
    multicast, reserved or documentation ranges, and no tunnels to such addresses)."""
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped  # ::ffff:127.0.0.1 is loopback in disguise
    # is_global alone is not enough: Python reports multicast ranges as global.
    if (
        address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
        or address.is_private
        or not address.is_global
    ):
        return False
    return not any(address in network for network in _BLOCKED_NETWORKS)


def resolve_public(host: str, port: int, resolver: Resolver) -> list[str]:
    addresses = resolver(host, port)
    if not addresses:
        raise FetchError("dns_failure", "The host name could not be resolved.")
    # ALL addresses must be public: a name that also points inside is not trusted.
    if not all(is_public_ip(a) for a in addresses):
        raise FetchError("blocked_address", "The address points to a private or internal network.")
    return addresses


def _pinned_url(parts: SplitResult, ip: str) -> str:
    host = f"[{ip}]" if ":" in ip else ip
    port = parts.port
    netloc = host if port is None else f"{host}:{port}"
    return urlunsplit((parts.scheme, netloc, parts.path or "/", parts.query, ""))


def _raise_for_status(status: int) -> None:
    if 200 <= status < 300:
        return
    if status in (401, 402, 403, 407, 451):
        raise FetchError("access_denied", "The page requires a login or blocks automated access.")
    if status in (404, 410):
        raise FetchError("not_found", "The page was not found (it may have been removed).")
    if status == 429:
        raise FetchError("upstream_error", "The site is limiting requests, try again later.")
    raise FetchError("upstream_error", f"The site answered with an error (HTTP {status}).")


class _ConnectFailed(Exception):
    pass


def _request_once(
    parts: SplitResult,
    ip: str,
    *,
    accept: str,
    content_types: frozenset[str] | None,
    max_bytes: int,
    truncate: bool,
    raise_on_status: bool,
    deadline: float,
    transport: httpx2.BaseTransport | None,
) -> FetchedPage | str:
    """One GET to one pinned IP. Returns the redirect target (str) or the page."""
    settings = get_settings()
    host = parts.hostname or ""
    headers = {
        "Host": parts.netloc,
        "User-Agent": settings.fetch_user_agent,
        "Accept": accept,
        "Accept-Language": "pl,en;q=0.8",
    }
    # TLS must validate the certificate for the NAME, not for the IP we connect to.
    extensions = {"sni_hostname": host} if parts.scheme == "https" else {}
    timeout = httpx2.Timeout(
        connect=settings.fetch_connect_timeout_sec,
        read=settings.fetch_read_timeout_sec,
        write=5.0,
        pool=5.0,
    )
    url = urlunsplit((parts.scheme, parts.netloc, parts.path or "/", parts.query, ""))
    try:
        with (
            httpx2.Client(
                transport=transport, timeout=timeout, follow_redirects=False, trust_env=False
            ) as client,
            client.stream(
                "GET", _pinned_url(parts, ip), headers=headers, extensions=extensions
            ) as response,
        ):
            status = response.status_code
            if status in _REDIRECT_STATUSES and response.headers.get("location"):
                return response.headers["location"]
            if raise_on_status:
                _raise_for_status(status)
            content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
            if not 200 <= status < 300:  # robots.txt: the caller interprets the status
                return FetchedPage(url, url, status, content_type, b"")
            if content_types is not None and content_type and content_type not in content_types:
                raise FetchError("not_html", "The address does not point to a web page.")
            declared = response.headers.get("content-length", "")
            if declared.isdigit() and int(declared) > max_bytes and not truncate:
                raise FetchError("too_large", "The page is too large to import.")

            chunks: list[bytes] = []
            total = 0
            for chunk in response.iter_bytes():  # already decompressed: counts real size
                total += len(chunk)
                if total > max_bytes:
                    if not truncate:
                        raise FetchError("too_large", "The page is too large to import.")
                    chunks.append(chunk[: len(chunk) - (total - max_bytes)])
                    break
                chunks.append(chunk)
                if time.monotonic() > deadline:
                    raise FetchError("timeout", "The site took too long to answer.")
            return FetchedPage(url, url, status, content_type, b"".join(chunks))
    except (httpx2.ConnectTimeout, httpx2.ConnectError):
        raise _ConnectFailed from None
    except httpx2.TimeoutException:
        raise FetchError("timeout", "The site took too long to answer.") from None
    except httpx2.HTTPError:
        raise FetchError("upstream_error", "The site could not be read.") from None


def safe_get(
    url: str,
    *,
    accept: str,
    content_types: frozenset[str] | None = HTML_TYPES,
    max_bytes: int | None = None,
    truncate: bool = False,
    raise_on_status: bool = True,
    before_hop: Callable[[str], None] | None = None,
    resolver: Resolver = system_resolver,
    transport: httpx2.BaseTransport | None = None,
) -> FetchedPage:
    """GET `url`, following up to `fetch_max_redirects` redirects with every hop re-validated.

    `before_hop(url)` runs before each connection (used for the robots.txt check).
    `raise_on_status=False` returns non-2xx responses instead of raising (robots.txt).
    """
    settings = get_settings()
    limit = max_bytes or settings.fetch_max_bytes
    deadline = time.monotonic() + settings.fetch_total_timeout_sec
    current = url

    for _ in range(settings.fetch_max_redirects + 1):
        try:
            parts = validate_url(current)
        except UrlError as exc:
            raise FetchError(exc.code, exc.message) from None
        if before_hop is not None:
            before_hop(urlunsplit(parts))
        if time.monotonic() > deadline:
            raise FetchError("timeout", "The site took too long to answer.")

        port = parts.port or _DEFAULT_PORTS[parts.scheme]
        addresses = resolve_public(parts.hostname or "", port, resolver)

        outcome: FetchedPage | str | None = None
        for ip in addresses[:_MAX_CONNECT_ATTEMPTS]:
            try:
                outcome = _request_once(
                    parts,
                    ip,
                    accept=accept,
                    content_types=content_types,
                    max_bytes=limit,
                    truncate=truncate,
                    raise_on_status=raise_on_status,
                    deadline=deadline,
                    transport=transport,
                )
                break
            except _ConnectFailed:
                continue
        if outcome is None:
            raise FetchError("upstream_error", "Could not connect to the site.")

        if isinstance(outcome, str):  # redirect: resolve against the current URL, validate again
            current = urljoin(urlunsplit(parts), outcome)
            continue
        return FetchedPage(
            url, urlunsplit(parts), outcome.status, outcome.content_type, outcome.body
        )

    raise FetchError("too_many_redirects", "The address redirects too many times.")
