import pytest

from app.services.urls import UrlError, normalize_url, validate_url


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://Example.COM/Przepis", "https://example.com/Przepis"),  # host lower, path kept
        ("https://example.com", "https://example.com/"),
        ("  https://example.com/a  ", "https://example.com/a"),
        ("https://example.com:443/a", "https://example.com/a"),  # default port dropped
        ("http://example.com:80/a", "http://example.com/a"),
        ("https://example.com/a#komentarze", "https://example.com/a"),  # fragment dropped
        (
            "https://example.com/a?utm_source=mail&id=7&utm_campaign=x&fbclid=abc",
            "https://example.com/a?id=7",
        ),
        ("https://example.com/a?b=2&a=1", "https://example.com/a?b=2&a=1"),  # order kept
        ("https://example.com/a?GCLID=1&page=2", "https://example.com/a?page=2"),
        ("https://example.com/a?utm_source=x", "https://example.com/a"),  # query gone entirely
        ("HTTPS://example.com/a", "https://example.com/a"),
        ("https://example.com./a", "https://example.com/a"),  # trailing dot of the FQDN
    ],
)
def test_normalize_url(raw, expected):
    assert normalize_url(raw) == expected


def test_normalization_is_idempotent_and_merges_variants():
    variants = [
        "https://example.com/p?utm_source=a",
        "https://EXAMPLE.com/p#x",
        "https://example.com:443/p",
        "https://example.com/p?fbclid=1",
    ]

    assert {normalize_url(v) for v in variants} == {"https://example.com/p"}
    assert normalize_url(normalize_url(variants[0])) == "https://example.com/p"


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "example.com/przepis",  # no scheme
        "ftp://example.com/a",
        "file:///etc/passwd",
        "javascript:alert(1)",
        "data:text/html,hi",
        "https://",
        "https://user:pass@example.com/a",  # credentials
        "https://user@example.com/a",
        "https://example.com:8080/a",  # non-standard port
        "https://example.com:22/a",
        "https://example.com:notaport/a",
        "https://exa mple.com/a",
        "https://example.com/a\nHost: evil",
        "https://example.com/" + "a" * 2100,
    ],
)
def test_invalid_urls_are_rejected(raw):
    with pytest.raises(UrlError) as exc:
        validate_url(raw)

    assert exc.value.code == "invalid_url"


@pytest.mark.parametrize(
    "raw",
    [
        "https://www.instagram.com/p/abc/",
        "https://instagram.com/reel/x",
        "https://www.tiktok.com/@user/video/1",
        "https://vm.tiktok.com/abc",
        "https://www.youtube.com/watch?v=abc",
        "https://m.youtube.com/watch?v=abc",
        "https://youtu.be/abc",
        "https://YouTube.com/watch?v=abc",
    ],
)
def test_social_media_links_get_a_clear_error(raw):
    with pytest.raises(UrlError) as exc:
        validate_url(raw)

    assert exc.value.code == "unsupported_site"
    assert "YouTube" in exc.value.message


def test_lookalike_domains_are_not_blocked():
    assert normalize_url("https://notinstagram.com/a") == "https://notinstagram.com/a"
    assert normalize_url("https://youtube.com.example.org/a") == "https://youtube.com.example.org/a"


def test_international_host_names_are_stored_in_ascii_form():
    normalized = normalize_url("https://kuchnia-żurek.pl/przepis")

    assert normalized.startswith("https://xn--")
    assert normalized.endswith(".pl/przepis")
    host = normalized.split("/")[2]
    assert host.encode("ascii").decode("idna") == "kuchnia-żurek.pl"
