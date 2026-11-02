"""robots.txt rules per RFC 9309."""

import pytest

from app.services.robots import RobotsRules, is_allowed, parse_groups

TOKEN = "RecipeMacrosBot"
SITE = "https://example.com"


def allowed(body, path, token=TOKEN):
    return is_allowed(RobotsRules("ok", body), SITE + path, token)


# --- availability (RFC 9309 section 2.3.1) ---
def test_missing_robots_allows_everything():
    assert is_allowed(RobotsRules("missing"), SITE + "/anything", TOKEN)


def test_unreachable_robots_disallows_everything():
    assert not is_allowed(RobotsRules("error"), SITE + "/anything", TOKEN)


def test_empty_file_allows_everything():
    assert allowed("", "/x")


# --- groups ---
def test_star_group_applies_when_there_is_no_group_for_us():
    assert not allowed("User-agent: *\nDisallow: /private/", "/private/a")
    assert allowed("User-agent: *\nDisallow: /private/", "/public/a")


def test_our_group_beats_the_star_group_even_when_less_strict():
    body = "User-agent: *\nDisallow: /\n\nUser-agent: RecipeMacrosBot\nDisallow: /admin/\n"

    assert allowed(body, "/przepis/1")
    assert not allowed(body, "/admin/x")


def test_token_match_is_case_insensitive():
    assert not allowed("User-agent: recipemacrosbot\nDisallow: /", "/x")


def test_other_bots_rules_do_not_apply_to_us():
    assert allowed("User-agent: Googlebot\nDisallow: /", "/x")


def test_consecutive_user_agent_lines_share_one_group():
    body = "User-agent: Googlebot\nUser-agent: RecipeMacrosBot\nDisallow: /secret\n"

    assert not allowed(body, "/secret")


def test_user_agent_after_rules_starts_a_new_group():
    body = "User-agent: Googlebot\nDisallow: /g\nUser-agent: RecipeMacrosBot\nDisallow: /r\n"

    assert allowed(body, "/g")
    assert not allowed(body, "/r")
    assert [sorted(agents) for agents, _ in parse_groups(body)] == [
        ["googlebot"],
        ["recipemacrosbot"],
    ]


# --- rule matching ---
def test_disallow_everything_and_empty_disallow():
    assert not allowed("User-agent: *\nDisallow: /", "/x")
    assert allowed("User-agent: *\nDisallow:", "/x")  # empty Disallow = nothing disallowed


def test_longest_match_wins_and_allow_wins_a_tie():
    body = "User-agent: *\nDisallow: /przepisy/\nAllow: /przepisy/publiczne/\n"
    assert allowed(body, "/przepisy/publiczne/zupa")
    assert not allowed(body, "/przepisy/prywatne/zupa")

    tie = "User-agent: *\nDisallow: /a\nAllow: /a\n"
    assert allowed(tie, "/abc")


def test_order_of_rules_does_not_matter():
    body = "User-agent: *\nAllow: /przepisy/publiczne/\nDisallow: /przepisy/\n"

    assert allowed(body, "/przepisy/publiczne/zupa")
    assert not allowed(body, "/przepisy/inne")


@pytest.mark.parametrize(
    ("pattern", "path", "expected"),
    [
        ("/*?print=", "/przepis?print=1", False),  # wildcard
        ("/*?print=", "/przepis", True),
        ("/*.pdf$", "/a/b.pdf", False),  # end anchor
        ("/*.pdf$", "/a/b.pdf?x=1", True),  # '$' means the URL ends there
        ("/*.pdf$", "/a/b.pdfx", True),
        ("/foo", "/foobar", False),  # plain prefix
        ("/foo/", "/foobar", True),
        ("/a*b*c", "/aXXbYYc", False),
    ],
)
def test_wildcards_and_anchors(pattern, path, expected):
    assert allowed(f"User-agent: *\nDisallow: {pattern}\n", path) is expected


def test_query_string_is_part_of_the_matched_path():
    assert not allowed("User-agent: *\nDisallow: /search?q=", "/search?q=zupa")
    assert allowed("User-agent: *\nDisallow: /search?q=", "/search")


def test_robots_txt_itself_is_always_allowed():
    assert allowed("User-agent: *\nDisallow: /", "/robots.txt")


# --- robustness ---
def test_comments_unknown_fields_and_garbage_are_ignored():
    body = (
        "# comment\n"
        "User-agent: *  # all bots\n"
        "Crawl-delay: 10\n"
        "Sitemap: https://example.com/sitemap.xml\n"
        "this line has no colon\n"
        "Disallow: /tmp/  # temp files\n"
    )

    assert not allowed(body, "/tmp/x")
    assert allowed(body, "/ok")


def test_rules_before_any_user_agent_are_ignored():
    assert allowed("Disallow: /\nUser-agent: *\nDisallow: /x\n", "/y")


def test_field_names_are_case_insensitive():
    assert not allowed("USER-AGENT: *\nDISALLOW: /x", "/x")


def test_only_the_first_500_kib_are_parsed():
    padding = "# " + "x" * 600_000 + "\n"
    body = padding + "User-agent: *\nDisallow: /\n"

    assert allowed(body, "/anything")
