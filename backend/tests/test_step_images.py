"""Step pictures: parsing, safe download, storage, serving, refresh and edit behaviour.
The web is faked (no network); files go to the temporary MEDIA_DIR set in conftest."""

from pathlib import Path

import httpx2
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.config import get_settings
from app.main import app
from app.routers.recipe_import import get_page_fetcher, get_recipe_ai
from app.schemas.ai import AIRefinement
from app.services.ai_extract import RecipeAI
from app.services.media import detect_image
from app.services.page_fetcher import PageFetcher
from app.services.redis_client import get_redis
from app.services.safe_fetch import FetchedPage, FetchError
from tests.fakes import FakeLLM, ing
from tests.test_import import URL, FakeFetcher, do_import
from tests.test_recipe_extractor import extract, page, recipe
from tests.test_recipes import create, recipe_payload

JPEG = b"\xff\xd8\xff\xe0" + b"jpeg-bytes" * 4
PNG = b"\x89PNG\r\n\x1a\n" + b"png-bytes" * 4
WEBP = b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"x" * 8
GIF = b"GIF89a" + b"gif-bytes" * 4
SVG = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
IMG = "https://blog.example.test/img/"


def media_files() -> set[str]:
    return {p.name for p in Path(get_settings().media_dir).glob("*")}


def steps_page(*steps):
    node = recipe(
        recipeIngredient=["1 jajko"],
        recipeInstructions=[
            {"@type": "HowToStep", "text": text, **({"image": image} if image else {})}
            for text, image in steps
        ],
    )
    return page(node).encode()


class ImageFetcher(FakeFetcher):
    """FakeFetcher that also serves step pictures (bytes, or a FetchError to raise)."""

    def __init__(self, pages, images):
        super().__init__(pages)
        self.images = images
        self.image_calls = []

    def fetch_image(self, url, *, timeout=None):
        self.image_calls.append(url)
        data = self.images.get(url, FetchError("not_found", "gone"))
        if isinstance(data, FetchError):
            raise data
        return FetchedPage(url, url, 200, "image/jpeg", data)


@pytest.fixture(autouse=True)
def _clean_media():
    for path in Path(get_settings().media_dir).glob("*"):
        path.unlink()
    yield
    app.dependency_overrides.pop(get_page_fetcher, None)
    app.dependency_overrides.pop(get_recipe_ai, None)


@pytest.fixture
def web():
    def install(pages, images):
        fetcher = ImageFetcher(pages, images)
        app.dependency_overrides[get_page_fetcher] = lambda: fetcher
        return fetcher

    return install


TWO = steps_page(("Pokrój.", IMG + "a.jpg"), ("Ugotuj.", IMG + "b.png"))
BOTH = {IMG + "a.jpg": JPEG, IMG + "b.png": PNG}


# --- parser ---
def test_parser_reads_step_images_in_every_shape():
    html = steps_page(
        ("Jeden.", "/img/one.jpg"),  # relative
        ("Dwa.", {"@type": "ImageObject", "url": "https://x.test/two.jpg"}),
        ("Trzy.", ["https://x.test/three.jpg", "https://x.test/other.jpg"]),
        ("Cztery.", "javascript:alert(1)"),  # not http(s)
        ("Pięć.", "data:image/png;base64,AAAA"),
        ("Sześć.", None),
    )

    result = extract(html, base="https://blog.example.test/przepis/")

    assert result.step_images == (
        "https://blog.example.test/img/one.jpg",
        "https://x.test/two.jpg",
        "https://x.test/three.jpg",
        None,
        None,
        None,
    )


def test_parser_has_no_images_for_plain_text_steps():
    assert extract(page(recipe(recipeInstructions=["A.", "B."]))).step_images == ()


# --- type detection ---
@pytest.mark.parametrize(
    ("data", "expected"),
    [(JPEG, "jpg"), (PNG, "png"), (WEBP, "webp"), (GIF, "gif"), (SVG, None), (b"<html>", None)],
)
def test_type_is_detected_from_the_content(data, expected):
    detected = detect_image(data)
    assert (detected[0] if detected else None) == expected


# --- fetching (real safe_get with a fake network) ---
def image_fetcher(handler, mapping=None):
    mapping = mapping or {"cdn.example.com": ["93.184.216.34"]}
    return PageFetcher(
        resolver=lambda host, port: mapping.get(host, [host]),  # IP literals resolve to themselves
        transport=httpx2.MockTransport(handler),
    )


def test_fetch_image_does_not_trust_the_content_type_header():
    fetcher = image_fetcher(
        lambda r: httpx2.Response(200, content=PNG, headers={"content-type": "text/plain"})
    )

    assert fetcher.fetch_image("https://cdn.example.com/a").body == PNG


def test_fetch_image_rejects_a_too_large_file(monkeypatch):
    monkeypatch.setattr(get_settings(), "image_max_bytes", 100)
    fetcher = image_fetcher(lambda r: httpx2.Response(200, content=JPEG + b"x" * 500))

    with pytest.raises(FetchError) as exc:
        fetcher.fetch_image("https://cdn.example.com/a.jpg")
    assert exc.value.code == "too_large"


def test_fetch_image_rejects_private_addresses():
    fetcher = image_fetcher(
        lambda r: httpx2.Response(200, content=JPEG), {"intranet.test": ["10.0.0.5"]}
    )

    with pytest.raises(FetchError) as exc:
        fetcher.fetch_image("https://intranet.test/a.jpg")
    assert exc.value.code == "blocked_address"
    with pytest.raises(FetchError):
        fetcher.fetch_image("http://127.0.0.1/a.jpg")


# --- import ---
def test_import_saves_pictures_and_exposes_relative_urls(alice, web):
    fetcher = web({URL: TWO}, BOTH)

    response = do_import(alice)

    assert response.status_code == 201
    body = response.json()
    rid = body["recipe"]["id"]
    assert [s["image_url"] for s in body["recipe"]["steps"]] == [
        f"/recipes/{rid}/steps/1/image",
        f"/recipes/{rid}/steps/2/image",
    ]
    assert "picture" not in (body["notice"] or "")
    assert fetcher.image_calls == [IMG + "a.jpg", IMG + "b.png"]
    assert len(media_files()) == 2

    served = alice.get(f"/recipes/{rid}/steps/2/image")
    assert served.status_code == 200
    assert served.content == PNG
    assert served.headers["content-type"] == "image/png"
    assert served.headers["x-content-type-options"] == "nosniff"
    assert served.headers["cache-control"] == "private, max-age=86400"


def test_a_failing_picture_does_not_break_the_import(alice, web):
    web({URL: TWO}, {IMG + "a.jpg": FetchError("timeout", "slow"), IMG + "b.png": PNG})

    body = do_import(alice).json()

    assert [s["image_url"] is not None for s in body["recipe"]["steps"]] == [False, True]
    assert "1 step picture" in body["notice"]
    assert len(media_files()) == 1


def test_svg_is_rejected_and_names_are_generated_not_taken_from_the_url(alice, web):
    web(
        {URL: steps_page(("Jeden.", IMG + "evil.jpg"), ("Dwa.", IMG + "x.svg"))},
        {IMG + "evil.jpg": SVG, IMG + "x.svg": JPEG},  # SVG named .jpg, JPEG named .svg
    )

    body = do_import(alice).json()

    assert [s["image_url"] is not None for s in body["recipe"]["steps"]] == [False, True]
    (name,) = media_files()
    assert name != "x.svg" and name.endswith(".jpg") and len(name) == 36  # uuid hex + ext


def test_at_most_30_pictures_per_recipe(alice, web):
    steps = [(f"Krok {i}.", f"{IMG}{i}.jpg") for i in range(1, 33)]
    web({URL: steps_page(*steps)}, {f"{IMG}{i}.jpg": JPEG for i in range(1, 33)})

    body = do_import(alice).json()

    assert sum(s["image_url"] is not None for s in body["recipe"]["steps"]) == 30
    assert "2 step picture" in body["notice"]
    assert len(media_files()) == 30


def test_ai_that_changes_the_step_count_drops_the_pictures(alice, web):
    web({URL: TWO}, BOTH)
    merged = AIRefinement(
        steps=["Pokrój i ugotuj."], ingredients=[ing(0, qty=1, unit="piece", product="jajko")]
    )
    llm = FakeLLM(merged)  # the page has 2 steps, the AI returns 1
    app.dependency_overrides[get_recipe_ai] = lambda: RecipeAI(llm, get_redis())

    body = do_import(alice).json()

    assert body["ai_used"] is True
    assert [s["instruction"] for s in body["recipe"]["steps"]] == ["Pokrój i ugotuj."]
    assert body["recipe"]["steps"][0]["image_url"] is None
    assert "2 step picture" in body["notice"]
    assert media_files() == set()


def test_ai_that_keeps_the_step_count_keeps_the_pictures(alice, web):
    web({URL: TWO}, BOTH)
    same = AIRefinement(
        steps=["Pokrój składniki.", "Ugotuj."],
        ingredients=[ing(0, qty=1, unit="piece", product="jajko")],
    )
    app.dependency_overrides[get_recipe_ai] = lambda: RecipeAI(FakeLLM(same), get_redis())

    body = do_import(alice).json()

    assert body["ai_used"] is True
    assert [s["image_url"] is not None for s in body["recipe"]["steps"]] == [True, True]


def test_no_orphan_files_when_saving_fails(alice, web, monkeypatch):
    web({URL: TWO}, BOTH)

    def boom(*args, **kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr("app.services.recipe_import.build_children", boom)
    with pytest.raises(RuntimeError):
        do_import(alice)

    assert media_files() == set()


def test_refresh_replaces_pictures_and_deletes_old_files(alice, web):
    fetcher = web({URL: TWO}, BOTH)
    do_import(alice)
    old = media_files()
    fetcher.pages[URL] = steps_page(("Pokrój.", IMG + "c.gif"), ("Ugotuj dłużej.", None))
    fetcher.images[IMG + "c.gif"] = GIF

    body = do_import(alice, refresh=True).json()

    assert body["status"] == "refreshed"
    assert [s["image_url"] is not None for s in body["recipe"]["steps"]] == [True, False]
    new = media_files()
    assert len(new) == 1 and not (new & old)


def test_soft_delete_keeps_files_but_hides_them(alice, web):
    web({URL: TWO}, BOTH)
    rid = do_import(alice).json()["recipe"]["id"]

    assert alice.delete(f"/recipes/{rid}").status_code == 204

    assert len(media_files()) == 2
    assert alice.get(f"/recipes/{rid}/steps/1/image").status_code == 404


# --- endpoint access ---
def test_image_endpoint_isolation_and_login(alice, bob, client, web):
    web({URL: TWO}, BOTH)
    rid = do_import(alice).json()["recipe"]["id"]
    path = f"/recipes/{rid}/steps/1/image"

    assert alice.get(path).status_code == 200
    assert bob.get(path).status_code == 404
    assert client.get(path).status_code == 401
    assert alice.get(f"/recipes/{rid}/steps/9/image").status_code == 404
    assert alice.get("/recipes/99999/steps/1/image").status_code == 404


def test_a_step_without_a_picture_is_404(alice):
    rid = create(alice)["id"]

    assert alice.get(f"/recipes/{rid}/steps/1/image").status_code == 404


def test_clients_cannot_set_pictures(alice):
    payload = recipe_payload(steps=[{"instruction": "A.", "image_url": "/etc/passwd"}])

    response = alice.post("/recipes", json=payload)

    assert response.status_code == 201  # the unknown step field is ignored, never stored
    assert response.json()["steps"][0]["image_url"] is None


# --- PUT keeps or drops pictures ---
def test_put_keeps_pictures_of_unchanged_steps_and_removes_the_rest(alice, web):
    web({URL: TWO}, BOTH)
    rid = do_import(alice).json()["recipe"]["id"]
    payload = recipe_payload(
        steps=[{"instruction": "Pokrój."}, {"instruction": "Ugotuj dłużej."}], ingredients=[]
    )

    updated = alice.put(f"/recipes/{rid}", json=payload).json()

    assert [s["image_url"] is not None for s in updated["steps"]] == [True, False]
    assert alice.get(f"/recipes/{rid}/steps/1/image").content == JPEG
    assert len(media_files()) == 1  # the file of the changed step is gone


def test_put_with_swapped_steps_drops_pictures(alice, web):
    web({URL: TWO}, BOTH)
    rid = do_import(alice).json()["recipe"]["id"]
    payload = recipe_payload(
        steps=[{"instruction": "Ugotuj."}, {"instruction": "Pokrój."}], ingredients=[]
    )

    updated = alice.put(f"/recipes/{rid}", json=payload).json()

    assert all(s["image_url"] is None for s in updated["steps"])
    assert media_files() == set()


def test_database_refuses_a_path_that_is_not_a_generated_name(alice, admin_db):
    rid = create(alice)["id"]

    with pytest.raises(IntegrityError):
        admin_db.execute(
            text(
                "UPDATE recipe_steps SET image_path = '../../etc/passwd', "
                "image_content_type = 'image/png' WHERE recipe_id = :r AND position = 1"
            ),
            {"r": rid},
        )
    admin_db.rollback()


# --- review follow-ups ---
def test_names_are_matched_in_full(alice, web):
    from app.services.media import delete_images, image_file

    web({URL: TWO}, BOTH)
    do_import(alice)
    (name, *_) = sorted(media_files())

    assert image_file(name) is not None
    assert image_file(name + "\n") is None
    delete_images([name + "\n"])
    assert name in media_files()


@pytest.mark.parametrize(
    "path",
    [
        "/recipes/1/steps/99999999999/image",
        "/recipes/99999999999/steps/1/image",
        "/recipes/1/steps/0/image",
    ],
)
def test_out_of_range_ids_are_rejected_not_a_server_error(alice, path):
    assert alice.get(path).status_code == 422


def test_image_response_headers(alice, web):
    web({URL: TWO}, BOTH)
    rid = do_import(alice).json()["recipe"]["id"]

    headers = alice.get(f"/recipes/{rid}/steps/1/image").headers

    assert headers["x-content-type-options"] == "nosniff"
    assert headers["cache-control"] == "private, max-age=86400"
    assert headers["content-security-policy"] == "default-src 'none'; sandbox"


def test_fetch_image_rejects_a_gzip_bomb(monkeypatch):
    import gzip

    monkeypatch.setattr(get_settings(), "image_max_bytes", 100_000)
    bomb = gzip.compress(JPEG + b"\0" * 1_000_000)
    assert len(bomb) < 100_000  # small on the wire, huge after decompression
    fetcher = image_fetcher(
        lambda r: httpx2.Response(200, content=bomb, headers={"content-encoding": "gzip"})
    )

    with pytest.raises(FetchError) as exc:
        fetcher.fetch_image("https://cdn.example.com/a.jpg")
    assert exc.value.code == "too_large"


def test_fetch_image_honours_a_shorter_total_timeout():
    import time

    def slow(request):
        def chunks():
            for _ in range(10):
                time.sleep(0.1)
                yield b"x" * 10

        return httpx2.Response(200, content=chunks())

    fetcher = image_fetcher(slow)

    with pytest.raises(FetchError) as exc:
        fetcher.fetch_image("https://cdn.example.com/a.jpg", timeout=0.25)
    assert exc.value.code == "timeout"


def test_image_phase_has_a_hard_time_ceiling(alice, web, monkeypatch):
    import time

    monkeypatch.setattr(get_settings(), "image_total_budget_sec", 0.25)
    fetcher = web({URL: TWO}, BOTH)
    timeouts = []
    original = fetcher.fetch_image

    def slow(url, *, timeout=None):
        timeouts.append(timeout)
        time.sleep(0.3)
        return original(url)

    fetcher.fetch_image = slow

    body = do_import(alice).json()

    assert len(timeouts) == 1 and timeouts[0] <= 0.25  # the second picture never started
    assert "1 step picture" in body["notice"]
    assert [s["image_url"] is not None for s in body["recipe"]["steps"]] == [True, False]


def test_refresh_keeps_the_old_picture_when_the_download_fails(alice, web):
    fetcher = web({URL: TWO}, BOTH)
    first = do_import(alice).json()["recipe"]
    old = media_files()
    fetcher.images[IMG + "a.jpg"] = FetchError("timeout", "slow")  # step 1 fails
    fetcher.images[IMG + "b.png"] = GIF  # step 2 is replaced

    body = do_import(alice, refresh=True).json()

    assert [s["image_url"] is not None for s in body["recipe"]["steps"]] == [True, True]
    assert alice.get(f"/recipes/{first['id']}/steps/1/image").content == JPEG
    assert alice.get(f"/recipes/{first['id']}/steps/2/image").content == GIF
    files = media_files()
    assert len(files) == 2 and len(files & old) == 1  # old step-1 file kept, old step-2 deleted
