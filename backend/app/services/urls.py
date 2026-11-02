"""Validation and normalization of user-supplied recipe URLs.

validate_url() decides whether an address may be fetched at all (scheme, port, credentials,
unsupported social sites). normalize_url() turns the accepted address into the canonical form
used as the recipe's `source_url`, the upsert key and the cache key.
"""

from urllib.parse import SplitResult, urlsplit, urlunsplit

MAX_URL_LENGTH = 2048
ALLOWED_PORTS = frozenset({80, 443})
_DEFAULT_PORTS = {"http": 80, "https": 443}

# Out of scope (AGENTS.md section 6): content sits behind logins / apps, not in the HTML.
_UNSUPPORTED_SITES = (
    "instagram.com",
    "tiktok.com",
    "youtube.com",
    "youtu.be",
    "youtube-nocookie.com",
)

# Query parameters that identify a visit, not a page. Dropped so that the same recipe opened
# from a newsletter and from a search engine is one record.
_TRACKING_EXACT = frozenset(
    {"fbclid", "gclid", "dclid", "msclkid", "yclid", "igshid", "mc_cid", "mc_eid", "_ga", "_gl"}
)
_TRACKING_PREFIXES = ("utm_",)


class UrlError(ValueError):
    """The address cannot be imported. `code` is a stable identifier for API clients."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _host_in(host: str, domains: tuple[str, ...]) -> bool:
    return any(host == d or host.endswith("." + d) for d in domains)


def validate_url(raw: str) -> SplitResult:
    """Parse `raw` and return it with an ASCII (IDNA) host, or raise UrlError."""
    value = (raw or "").strip()
    if not value or len(value) > MAX_URL_LENGTH:
        raise UrlError("invalid_url", "The address is empty or longer than 2048 characters.")
    if any(ch.isspace() or ord(ch) < 32 for ch in value):
        raise UrlError("invalid_url", "The address contains spaces or control characters.")

    try:
        parts = urlsplit(value)
        port = parts.port
        host = parts.hostname
    except ValueError:
        raise UrlError("invalid_url", "The address is not a valid URL.") from None

    scheme = parts.scheme.lower()
    if scheme not in _DEFAULT_PORTS:
        raise UrlError("invalid_url", "Only http:// and https:// addresses can be imported.")
    if not host:
        raise UrlError("invalid_url", "The address has no host name.")
    if parts.username is not None or parts.password is not None:
        raise UrlError("invalid_url", "Addresses with a user name or password are not accepted.")
    if port is not None and port not in ALLOWED_PORTS:
        raise UrlError("invalid_url", "Only the standard web ports (80 and 443) are accepted.")

    try:
        host = host.lower().rstrip(".").encode("idna").decode("ascii")  # "żurek.pl" -> xn--...
    except UnicodeError:
        raise UrlError("invalid_url", "The host name is not valid.") from None
    if not host:
        raise UrlError("invalid_url", "The address has no host name.")

    if _host_in(host, _UNSUPPORTED_SITES):
        raise UrlError(
            "unsupported_site",
            "Instagram, TikTok and YouTube links cannot be imported. "
            "Use the address of a page with the written recipe.",
        )

    netloc = f"[{host}]" if ":" in host else host
    if port is not None and port != _DEFAULT_PORTS[scheme]:
        netloc += f":{port}"
    return SplitResult(scheme, netloc, parts.path, parts.query, "")


def _is_tracking(pair: str) -> bool:
    key = pair.split("=", 1)[0].lower()
    return key in _TRACKING_EXACT or key.startswith(_TRACKING_PREFIXES)


def normalize_url(raw: str) -> str:
    """Canonical form: lower-case scheme/host, default port and #fragment removed, tracking
    parameters dropped. Everything else (path, other parameters, their order) is kept."""
    parts = validate_url(raw)
    kept = [pair for pair in parts.query.split("&") if pair and not _is_tracking(pair)]
    return urlunsplit((parts.scheme, parts.netloc, parts.path or "/", "&".join(kept), ""))
