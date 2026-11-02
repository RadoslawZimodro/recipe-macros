"""robots.txt rules according to RFC 9309.

A small implementation of our own: `urllib.robotparser` does not understand the `*` and `$`
wildcards that many sites use (for example `Disallow: /*?print=`), so it would let us fetch
pages the owner has excluded.

Rules in short: the group for our product token wins, otherwise the `*` group; among the
rules that match the URL path the LONGEST pattern wins and Allow beats Disallow on a tie; no
matching rule means allowed. Availability: a missing file (4xx) allows everything, an
unreachable one (5xx, network error) is treated as a complete disallow.
"""

import re
from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import urlsplit

MAX_ROBOTS_BYTES = 500 * 1024  # RFC 9309: parse at least 500 KiB, ignore the rest


@dataclass(frozen=True)
class RobotsRules:
    """What we learned about a site's robots.txt: ok (body parsed), missing, or error."""

    status: str  # "ok" | "missing" | "error"
    body: str = ""


Group = tuple[
    frozenset[str], tuple[tuple[bool, str], ...]
]  # (user agents, ((allow, pattern), ...))


def parse_groups(text: str) -> list[Group]:
    groups: list[Group] = []
    agents: list[str] = []
    rules: list[tuple[bool, str]] = []
    reading_agents = False

    def flush() -> None:
        if agents:
            groups.append((frozenset(agents), tuple(rules)))

    for line in text[:MAX_ROBOTS_BYTES].splitlines():
        line = line.split("#", 1)[0].strip()
        field, sep, value = line.partition(":")
        if not sep:
            continue
        field, value = field.strip().lower(), value.strip()
        if field == "user-agent":
            if not reading_agents:  # a new group starts after the previous group's rules
                flush()
                agents, rules = [], []
                reading_agents = True
            agents.append(value.lower())
        elif field in ("allow", "disallow") and agents:
            reading_agents = False
            if value:  # an empty Disallow means "nothing is disallowed"; an empty Allow is noise
                rules.append((field == "allow", value))
    flush()
    return groups


@lru_cache(maxsize=512)
def _compile(pattern: str) -> re.Pattern[str]:
    anchored = pattern.endswith("$")
    if anchored:
        pattern = pattern[:-1]
    regex = ".*".join(re.escape(part) for part in pattern.split("*"))
    return re.compile(regex + ("$" if anchored else ""))


def is_allowed(rules: RobotsRules, url: str, product_token: str) -> bool:
    if rules.status == "missing":
        return True
    if rules.status != "ok":
        return False

    parts = urlsplit(url)
    path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
    if parts.path == "/robots.txt":
        return True

    groups = parse_groups(rules.body)
    token = product_token.lower()
    matching = [g for g in groups if token in g[0]] or [g for g in groups if "*" in g[0]]
    if not matching:
        return True

    best: tuple[int, bool] | None = None  # (pattern length, allow)
    for _, group_rules in matching:
        for allow, pattern in group_rules:
            if _compile(pattern).match(path):
                candidate = (len(pattern), allow)
                if (
                    best is None
                    or candidate[0] > best[0]
                    or (candidate[0] == best[0] and allow and not best[1])
                ):
                    best = candidate
    return True if best is None else best[1]
