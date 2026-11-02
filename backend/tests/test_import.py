"""POST /recipes/import end to end: real PostgreSQL and Redis, faked web (no real network)."""

from pathlib import Path

import httpx2
import pytest
from sqlalchemy import text

from app.config import get_settings
from app.main import app
from app.routers.recipe_import import get_page_fetcher
from app.services.page_cache import PageCache
from app.services.page_fetcher import PageFetcher
from app.services.redis_client import get_redis
from app.services.safe_fetch import FetchedPage, FetchError
from tests.test_recipes import recipe_payload

FIXTURES = Path(__file__).parent / "fixtures" / "recipes"
URL = "https://blog.example.test/szarlotka"
PL_FLAT = (FIXTURES / "pl_flat.html").read_bytes()
EN_GRAPH = (FIXTURES / "en_graph.html").read_bytes()
MICRODATA = (FIXTURES / "microdata_only.html").read_bytes()
ARTICLE = (FIXTURES / "article_only.html").read_bytes()


class FakeFetcher:
    """Stands in for PageFetcher: serves canned pages and records how it was called."""

    def __init__(self, pages=None):
        self.pages = pages if pages is not None else {URL: PL_FLAT}
        self.calls = []

    def fetch(self, url, *, refresh=False):
        self.calls.append((url, refresh))
        page = self.pages.get(url)
        if isinstance(page, FetchError):
            raise page
        if page is None:
            raise FetchError("not_found", "The page was not found (it may have been removed).")
        return FetchedPage(url, url, 200, "text/html", page)


@pytest.fixture
def fake():
    fetcher = FakeFetcher()
    app.dependency_overrides[get_page_fetcher] = lambda: fetcher
    yield fetcher
    app.dependency_overrides.pop(get_page_fetcher, None)


def do_import(client, url=URL, **extra):
    return client.post("/recipes/import", json={"url": url, **extra})


# --- creating ---
def test_import_creates_a_recipe_from_json_ld(alice, fake):
    response = do_import(alice)

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "created"
    recipe = body["recipe"]
    assert recipe["title"] == "Szarlotka z kruszonką"
    assert recipe["source_url"] == URL
    assert recipe["import_method"] == "jsonld"
    assert recipe["imported_at"] is not None
    assert recipe["servings"] == 8
    assert (recipe["prep_time_min"], recipe["cook_time_min"]) == (30, 60)
    assert recipe["tags"][:2] == ["deser", "polska"]
    assert [s["position"] for s in recipe["steps"]] == [1, 2, 3]
    assert [i["position"] for i in recipe["ingredients"]] == list(range(1, 8))
    assert recipe["ingredients"][0]["raw_text"] == "300 g mąki pszennej"
    assert recipe["ingredients"][0]["quantity"] is None  # parsing the line is the AI step
    assert recipe["source_nutrition"]["calories"] == "320 kcal"
    assert fake.calls == [(URL, False)]


def test_imported_recipe_is_a_normal_recipe(alice, fake):
    recipe_id = do_import(alice).json()["recipe"]["id"]

    assert alice.get(f"/recipes/{recipe_id}").json()["title"] == "Szarlotka z kruszonką"
    assert alice.get("/recipes", params={"q": "szarlotka"}).json()["total"] == 1
    assert alice.get("/recipes", params={"tag": "deser"}).json()["total"] == 1


def test_the_stored_address_is_the_normalized_one(alice, fake):
    fake.pages = {URL: PL_FLAT}

    response = do_import(
        alice, url="  HTTPS://Blog.Example.test/szarlotka?utm_source=news#komentarze "
    )

    assert response.status_code == 201
    assert response.json()["recipe"]["source_url"] == URL
    assert fake.calls == [(URL, False)]


# --- the same link again ---
def test_importing_a_saved_link_returns_it_without_fetching(alice, fake):
    first = do_import(alice).json()["recipe"]

    again = do_import(alice)

    assert again.status_code == 200
    assert again.json()["status"] == "existing"
    assert again.json()["recipe"]["id"] == first["id"]
    assert len(fake.calls) == 1  # no second fetch


def test_tracking_variants_of_a_link_are_the_same_recipe(alice, fake):
    first = do_import(alice).json()["recipe"]

    variant = do_import(alice, url=URL + "?utm_source=mail&fbclid=1#x")

    assert variant.json()["status"] == "existing" and variant.json()["recipe"]["id"] == first["id"]
    assert len(fake.calls) == 1


def test_manual_edits_survive_a_plain_reimport(alice, fake):
    recipe = do_import(alice).json()["recipe"]
    alice.put(
        f"/recipes/{recipe['id']}", json=recipe_payload(title="Moja szarlotka", source_url=URL)
    )

    again = do_import(alice).json()["recipe"]

    assert again["title"] == "Moja szarlotka"


# --- refresh = upsert ---
def test_refresh_overwrites_the_recipe_in_place(alice, fake, admin_db):
    first = do_import(alice).json()["recipe"]
    alice.put(f"/recipes/{first['id']}", json=recipe_payload(title="Moja wersja", source_url=URL))
    fake.pages[URL] = EN_GRAPH  # the page changed

    response = do_import(alice, refresh=True)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "refreshed"
    recipe = body["recipe"]
    assert recipe["id"] == first["id"]  # same row: the upsert updated it
    assert recipe["title"] == "Weeknight Lemon Chickpea Pasta"  # manual edit overwritten
    assert [s["position"] for s in recipe["steps"]] == [1, 2, 3, 4]
    assert [i["position"] for i in recipe["ingredients"]] == list(range(1, 7))
    assert recipe["imported_at"] > first["imported_at"]
    assert recipe["updated_at"] > first["updated_at"]
    assert recipe["created_at"] == first["created_at"]
    assert fake.calls[-1] == (URL, True)  # the cache was bypassed
    counts = admin_db.execute(
        text(
            "SELECT (SELECT count(*) FROM recipes), (SELECT count(*) FROM recipe_steps), "
            "(SELECT count(*) FROM recipe_ingredients)"
        )
    ).one()
    assert tuple(counts) == (1, 4, 6)  # no duplicates, the old children are gone


def test_refresh_of_an_unsaved_link_just_creates_it(alice, fake):
    response = do_import(alice, refresh=True)

    assert response.status_code == 201
    assert response.json()["status"] == "created"


def test_a_deleted_recipe_can_be_imported_again_as_a_new_one(alice, fake):
    first = do_import(alice).json()["recipe"]
    alice.delete(f"/recipes/{first['id']}")

    second = do_import(alice)

    assert second.status_code == 201
    assert second.json()["recipe"]["id"] != first["id"]


# --- users ---
def test_each_user_gets_their_own_copy(alice, bob, fake):
    a = do_import(alice).json()["recipe"]
    b = do_import(bob)

    assert b.status_code == 201  # Bob does not "see" Alice's saved link
    assert b.json()["recipe"]["id"] != a["id"]
    assert alice.get(f"/recipes/{b.json()['recipe']['id']}").status_code == 404
    assert len(fake.calls) == 2


def test_import_requires_a_session_and_csrf(client, alice, fake):
    assert client.post("/recipes/import", json={"url": URL}).status_code == 401
    del alice.headers["X-CSRF-Token"]
    assert do_import(alice).status_code == 403
    assert fake.calls == []


# --- errors ---
def error_of(response):
    return response.json()["detail"]


def test_page_without_json_ld_recipe_is_a_clear_422(alice, fake):
    fake.pages = {URL: MICRODATA, URL + "-2": ARTICLE}

    for url in (URL, URL + "-2"):
        response = do_import(alice, url=url)
        assert response.status_code == 422
        assert error_of(response)["code"] == "no_recipe_data"
        assert "structured recipe data" in error_of(response)["message"]
    assert alice.get("/recipes").json()["total"] == 0


@pytest.mark.parametrize(
    "url",
    [
        "https://www.instagram.com/p/abc/",
        "https://www.tiktok.com/@u/video/1",
        "https://www.youtube.com/watch?v=abc",
        "https://youtu.be/abc",
    ],
)
def test_social_links_are_refused_before_any_fetch(alice, fake, url):
    response = do_import(alice, url=url)

    assert response.status_code == 422
    assert error_of(response)["code"] == "unsupported_site"
    assert fake.calls == []


@pytest.mark.parametrize(
    "url",
    [
        "",
        "not a url",
        "ftp://example.com/a",
        "http://localhost:8010/health",
        "https://u:p@example.com/",
    ],
)
def test_invalid_links_are_refused_before_any_fetch(alice, fake, url):
    response = do_import(alice, url=url)

    assert response.status_code == 422
    assert error_of(response)["code"] == "invalid_url"
    assert fake.calls == []


def test_malformed_request_bodies_are_rejected(alice, fake):
    assert alice.post("/recipes/import", json={}).status_code == 422
    assert alice.post("/recipes/import", json={"url": URL, "user_id": 2}).status_code == 422
    assert (
        alice.post("/recipes/import", json={"url": "https://e.com/" + "a" * 3000}).status_code
        == 422
    )
    assert fake.calls == []


@pytest.mark.parametrize(
    ("code", "status"),
    [
        ("blocked_address", 422),
        ("dns_failure", 422),
        ("robots_disallowed", 422),
        ("access_denied", 422),
        ("not_found", 422),
        ("not_html", 422),
        ("too_large", 422),
        ("too_many_redirects", 422),
        ("robots_unavailable", 502),
        ("upstream_error", 502),
        ("timeout", 504),
    ],
)
def test_fetch_errors_become_stable_codes_and_statuses(alice, fake, code, status):
    fake.pages = {URL: FetchError(code, f"readable message for {code}")}

    response = do_import(alice)

    assert response.status_code == status
    assert error_of(response) == {"code": code, "message": f"readable message for {code}"}
    assert alice.get("/recipes").json()["total"] == 0


# --- rate limit ---
def test_import_budget_per_user(alice, bob, fake, monkeypatch):
    monkeypatch.setattr(get_settings(), "import_rate_limit_per_min", 2)
    fake.pages = {f"{URL}-{n}": PL_FLAT for n in range(6)}

    assert do_import(alice, url=f"{URL}-0").status_code == 201
    assert do_import(alice, url=f"{URL}-1").status_code == 201
    blocked = do_import(alice, url=f"{URL}-2")

    assert blocked.status_code == 429
    assert error_of(blocked)["code"] == "rate_limited"
    assert 1 <= int(blocked.headers["Retry-After"]) <= 60
    assert do_import(bob, url=f"{URL}-3").status_code == 201  # another user is not affected
    assert len(fake.calls) == 3  # the refused import never reached the fetcher


def test_already_saved_links_do_not_use_the_budget(alice, fake, monkeypatch):
    monkeypatch.setattr(get_settings(), "import_rate_limit_per_min", 1)
    assert do_import(alice).status_code == 201

    for _ in range(5):
        assert do_import(alice).json()["status"] == "existing"


def test_failed_fetches_use_the_budget_too(alice, fake, monkeypatch):
    monkeypatch.setattr(get_settings(), "import_rate_limit_per_min", 2)
    fake.pages = {}  # every page is "not found"

    assert do_import(alice, url=URL + "-a").status_code == 422
    assert do_import(alice, url=URL + "-b").status_code == 422
    assert do_import(alice, url=URL + "-c").status_code == 429


def test_import_is_refused_when_the_rate_limiter_is_down(alice, fake):
    class BrokenRedis:
        def pipeline(self, *args, **kwargs):
            from redis.exceptions import RedisError

            raise RedisError("down")

    app.dependency_overrides[get_redis] = lambda: BrokenRedis()
    try:
        response = do_import(alice)
    finally:
        app.dependency_overrides.pop(get_redis, None)

    assert response.status_code == 503
    assert error_of(response)["code"] == "service_unavailable"
    assert fake.calls == []


# --- the whole chain: endpoint -> PageFetcher (robots, cache) -> faked network ---
def test_full_chain_with_robots_and_page_cache(alice):
    requests = []

    def site(request):
        requests.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx2.Response(
                200,
                headers={"content-type": "text/plain"},
                content=b"User-agent: *\nDisallow: /tajne/\n",
            )
        return httpx2.Response(200, headers={"content-type": "text/html"}, content=PL_FLAT)

    fetcher = PageFetcher(
        PageCache(get_redis()),
        resolver=lambda host, port: ["93.184.216.34"],
        transport=httpx2.MockTransport(site),
    )
    app.dependency_overrides[get_page_fetcher] = lambda: fetcher
    try:
        created = do_import(alice)
        refreshed = do_import(alice, refresh=True)  # bypasses the cache read
        blocked = do_import(alice, url="https://blog.example.test/tajne/przepis")
    finally:
        app.dependency_overrides.pop(get_page_fetcher, None)

    assert created.status_code == 201 and refreshed.json()["status"] == "refreshed"
    assert blocked.status_code == 422 and error_of(blocked)["code"] == "robots_disallowed"
    assert requests.count("/szarlotka") == 2 and requests.count("/robots.txt") == 1
    assert list(get_redis().scan_iter("page:v1:*"))  # the page is cached for later
