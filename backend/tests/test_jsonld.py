"""Recipe extraction from JSON-LD. The pages in tests/fixtures/recipes are synthetic: written
for these tests in the layouts found on real sites, so no third-party content is committed."""

import json
from pathlib import Path

import pytest

from app.services.jsonld import extract_recipe

FIXTURES = Path(__file__).parent / "fixtures" / "recipes"
SOURCE = "https://example.test/przepis"


def extract(html, base=SOURCE):
    data = html if isinstance(html, bytes) else html.encode()
    return extract_recipe(data, base_url=base, source_url=SOURCE)


def fixture(name, base=SOURCE):
    return extract((FIXTURES / name).read_bytes(), base)


def page(*blocks):
    """Wrap JSON-LD blocks (dicts or raw strings) in a minimal HTML page."""
    scripts = "".join(
        f'<script type="application/ld+json">{b if isinstance(b, str) else json.dumps(b)}</script>'
        for b in blocks
    )
    return f"<html><head>{scripts}</head><body></body></html>"


def recipe(**fields):
    return {"@context": "https://schema.org", "@type": "Recipe", "name": "Zupa", **fields}


STEPS = ["Pokrój.", "Ugotuj."]


# --- realistic pages ---
def test_polish_flat_recipe():
    result = fixture("pl_flat.html")

    r = result.recipe
    assert r.title == "Szarlotka z kruszonką"
    assert r.description.startswith("Domowa szarlotka na kruchym spodzie")
    assert r.source_url == SOURCE
    assert r.image_url == "https://blog.example.test/img/szarlotka-1x1.jpg"  # first of the list
    assert r.servings == 8
    assert (r.prep_time_min, r.cook_time_min) == (30, 60)
    assert r.tags == ["deser", "polska", "ciasto", "jabłka", "szarlotka", "ciasto kruche"]
    assert [i.raw_text for i in r.ingredients] == [
        "300 g mąki pszennej",
        "200 g zimnego masła",
        "100 g cukru pudru",
        "1 jajko",
        "1 kg kwaśnych jabłek",
        "2 łyżki cynamonu",
        "szczypta soli",
    ]
    assert len(r.steps) == 3 and r.steps[0].instruction.startswith("Zagnieć mąkę")
    assert result.source_nutrition == {
        "calories": "320 kcal",
        "fatContent": "14 g",
        "carbohydrateContent": "45 g",
        "proteinContent": "4 g",
    }


def test_ingredient_lines_are_kept_as_text_only_for_the_ai_step():
    ingredient = fixture("pl_flat.html").recipe.ingredients[0]

    assert (ingredient.quantity, ingredient.unit, ingredient.ingredient_id) == (None, None, None)


def test_english_graph_with_sections_object_image_and_list_yield():
    r = fixture("en_graph.html", base="https://kitchen.example.test/lemon-chickpea-pasta/").recipe

    assert r.title == "Weeknight Lemon Chickpea Pasta"
    assert (
        r.description
        == "A bright, one-pan pasta with chickpeas, lemon and garlic. Ready in 30 minutes."
    )
    assert r.image_url == "https://kitchen.example.test/media/lemon-pasta.jpg"  # made absolute
    assert r.servings == 4  # ["4", "4 servings"]
    assert (r.prep_time_min, r.cook_time_min) == (10, 20)
    assert r.tags == [
        "dinner",
        "main course",
        "italian-inspired",
        "pasta",
        "vegetarian",
        "30 minutes",
    ]
    assert len(r.ingredients) == 6
    assert [s.instruction for s in r.steps] == [
        "Boil the pasta in salted water until al dente, then drain and keep a cup of the water.",
        "Warm the olive oil and fry the garlic for one minute.",
        "Add the chickpeas and lemon zest, cook for five minutes.",
        "Toss in the pasta with a splash of the cooking water and the lemon juice.",
    ]


def test_instructions_given_as_one_text_with_br_and_numbers():
    r = fixture("pl_text_instructions.html", base="https://sklep.example.test/a/b").recipe

    assert [s.instruction for s in r.steps] == [
        "Wymieszaj mąkę z drożdżami i solą.",
        "Dodaj mleko z olejem i wyrabiaj ciasto 10 minut.",
        "Odstaw pod przykryciem na godzinę.",
        "Uformuj bułeczki i piecz 20 minut w 200 stopniach.",
    ]
    assert r.servings == 12
    assert (r.prep_time_min, r.cook_time_min) == (75, 20)  # PT1H15M, P0DT0H20M
    assert r.image_url == "https://sklep.example.test/zdjecia/buleczki.jpg"


def test_html_entities_and_blank_ingredient_lines_are_cleaned():
    lines = [i.raw_text for i in fixture("pl_text_instructions.html").recipe.ingredients]

    assert lines == [
        "500 g mąki pszennej",  # &nbsp; became a normal space
        "1 opakowanie drożdży suchych (7 g)",
        "250 ml ciepłego mleka",
        "2 łyżki oleju",
        "sól & cukier do smaku",  # &amp; decoded
    ]


def test_broken_json_block_is_skipped_and_cdata_wrapper_is_tolerated():
    r = fixture("broken_then_valid.html").recipe

    assert r.title == "Overnight Oats"  # not "Broken block"
    assert r.description == "Prepare the evening before. Eat cold in the morning."  # raw newline
    assert r.servings == 2
    assert len(r.ingredients) == 3 and len(r.steps) == 2


def test_the_fuller_recipe_wins_over_teasers():
    r = fixture("multiple_recipes.html").recipe

    assert r.title == "Roast Tomato Soup"  # not "Garlic Bread" / "Green Salad"
    assert r.servings == 6  # "6-8 servings" -> first number
    assert (r.prep_time_min, r.cook_time_min) == (15, 45)


def test_microdata_only_page_has_no_recipe_for_this_step():
    assert fixture("microdata_only.html") is None


def test_json_ld_without_a_recipe_gives_none():
    assert fixture("article_only.html") is None


def test_page_without_any_structured_data():
    assert extract("<html><body><h1>Zupa</h1><p>Pokrój i ugotuj.</p></body></html>") is None


# --- shapes of the Recipe node ---
@pytest.mark.parametrize(
    "type_value",
    [
        "Recipe",
        "recipe",
        ["Recipe"],
        ["Thing", "Recipe"],
        "https://schema.org/Recipe",
        "schema:Recipe",
    ],
)
def test_recipe_type_spellings(type_value):
    node = recipe(recipeInstructions=STEPS)
    node["@type"] = type_value

    assert extract(page(node)).recipe.title == "Zupa"


def test_top_level_list_and_nested_main_entity():
    assert extract(page([{"@type": "WebSite"}, recipe(recipeInstructions=STEPS)])) is not None
    wrapper = {"@type": "WebPage", "mainEntity": recipe(recipeInstructions=STEPS)}
    assert extract(page(wrapper)).recipe.title == "Zupa"


def test_a_recipe_needs_a_title_and_some_content():
    assert extract(page(recipe(name=""))) is None
    assert extract(page({"@type": "Recipe", "recipeInstructions": STEPS})) is None
    assert extract(page(recipe())) is None  # name only: a teaser, not a recipe
    assert extract(page(recipe(recipeIngredient=["1 jajko"]))) is not None  # ingredients suffice
    assert extract(page(recipe(recipeInstructions="Ugotuj."))) is not None  # steps suffice


def test_script_type_with_parameters_and_uppercase_is_found():
    html = (
        '<script type="Application/LD+JSON; charset=utf-8">'
        + json.dumps(recipe(recipeInstructions=STEPS))
        + "</script>"
    )

    assert extract(html).recipe.title == "Zupa"


def test_name_may_be_a_list_or_contain_markup():
    assert (
        extract(page(recipe(name=["Zupa dnia", "x"], recipeInstructions=STEPS))).recipe.title
        == "Zupa dnia"
    )
    assert (
        extract(
            page(recipe(name="Zupa <i>pomidorowa</i> &amp; chleb", recipeInstructions=STEPS))
        ).recipe.title
        == "Zupa pomidorowa & chleb"
    )


# --- servings ---
@pytest.mark.parametrize(
    ("value", "expected"),
    [("4", 4), (4, 4), (4.0, 4), ("4 servings", 4), ("6-8", 6), (["", "10 porcji"], 10),
     ("makes 1 loaf", 1), ("a few", 1), (None, 1), (0, 1), ("0", 1), (5000, 1000), (True, 1),
     ({}, 1)],
)  # fmt: skip
def test_servings_parsing(value, expected):
    node = recipe(recipeInstructions=STEPS)
    if value is not None:
        node["recipeYield"] = value

    assert extract(page(node)).recipe.servings == expected


# --- durations ---
@pytest.mark.parametrize(
    ("value", "expected"),
    [("PT30M", 30), ("PT1H", 60), ("PT1H30M", 90), ("pt45m", 45), ("P0DT0H20M", 20),
     ("P1DT2H", 1560), ("P1W", 10080), ("PT90S", 2), ("PT0M", None), ("P0D", None),
     ("30 minutes", None), ("", None), (None, None), (30, None), ("PT", None), ("PT10X", None),
     ("P1000D", None)],
)  # fmt: skip
def test_iso_duration_parsing(value, expected):
    node = recipe(recipeInstructions=STEPS)
    if value is not None:
        node["prepTime"] = value

    assert extract(page(node)).recipe.prep_time_min == expected


# --- images ---
@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("https://cdn.example.test/a.jpg", "https://cdn.example.test/a.jpg"),
        ("/a.jpg", "https://example.test/a.jpg"),
        ("a.jpg", "https://example.test/a.jpg"),
        ("//cdn.example.test/a.jpg", "https://cdn.example.test/a.jpg"),
        (["", "javascript:alert(1)", "https://cdn.example.test/b.jpg"], "https://cdn.example.test/b.jpg"),
        ({"@type": "ImageObject", "url": "https://cdn.example.test/c.jpg"}, "https://cdn.example.test/c.jpg"),
        ([{"contentUrl": "/d.jpg"}], "https://example.test/d.jpg"),
        ("javascript:alert(1)", None),
        ("data:image/png;base64,AAAA", None),
        (123, None),
        ({}, None),
        ("", None),
    ],
)  # fmt: skip
def test_image_url_handling(value, expected):
    node = recipe(recipeInstructions=STEPS, image=value)

    assert extract(page(node)).recipe.image_url == expected


# --- instructions ---
def test_numbering_prefixes_are_removed_but_quantities_are_not():
    node = recipe(
        recipeInstructions=[
            "1. Pokrój",
            "2) Wymieszaj",
            "Krok 3: Piecz",
            "10 minut w piekarniku",
            "10 - 12 minut",
        ]
    )

    assert [s.instruction for s in extract(page(node)).recipe.steps] == [
        "Pokrój",
        "Wymieszaj",
        "Piecz",
        "10 minut w piekarniku",
        "10 - 12 minut",
    ]


def test_howto_step_without_text_uses_its_name_and_duplicates_collapse():
    node = recipe(
        recipeInstructions=[
            {"@type": "HowToStep", "name": "Wymieszaj"},
            {"@type": "HowToStep", "name": "Wymieszaj"},
            {"@type": "HowToStep", "text": "Piecz", "name": "ignored"},
        ]
    )

    assert [s.instruction for s in extract(page(node)).recipe.steps] == ["Wymieszaj", "Piecz"]


def test_item_list_without_type_is_treated_as_a_section():
    node = recipe(recipeInstructions=[{"name": "Ciasto", "itemListElement": [{"text": "Zagnieć"}]}])

    assert [s.instruction for s in extract(page(node)).recipe.steps] == ["Zagnieć"]


def test_limits_on_steps_ingredients_and_lengths():
    node = recipe(
        recipeInstructions=[f"krok {i}" for i in range(500)] + ["x" * 9000],
        recipeIngredient=[f"składnik {i}" for i in range(500)],
        name="N" * 1000,
        description="d" * 20_000,
    )

    r = extract(page(node)).recipe
    assert len(r.steps) == 100 and len(r.ingredients) == 200
    assert len(r.title) == 300 and len(r.description) == 5000


def test_overlong_step_and_ingredient_are_truncated():
    node = recipe(recipeInstructions=["x" * 9000], recipeIngredient=["y" * 900])

    r = extract(page(node)).recipe
    assert len(r.steps[0].instruction) == 5000 and len(r.ingredients[0].raw_text) == 500


def test_legacy_ingredients_property_and_single_string():
    node = recipe(ingredients=["1 jajko", "sól"])
    assert [i.raw_text for i in extract(page(node)).recipe.ingredients] == ["1 jajko", "sól"]

    node = recipe(recipeIngredient="1 jajko")
    assert [i.raw_text for i in extract(page(node)).recipe.ingredients] == ["1 jajko"]


# --- tags ---
def test_tags_are_split_lowercased_deduplicated_and_limited():
    node = recipe(
        recipeInstructions=STEPS,
        recipeCategory=["Obiad", "OBIAD"],
        recipeCuisine="Włoska",
        keywords="pasta; Szybkie, szybkie ,, "
        + ", ".join(f"tag{i}" for i in range(40))
        + ", "
        + "z" * 80,
    )

    tags = extract(page(node)).recipe.tags
    assert tags[:4] == ["obiad", "włoska", "pasta", "szybkie"]
    assert len(tags) == 20
    assert all(len(t) <= 50 for t in tags)


# --- nutrition ---
def test_nutrition_keeps_only_simple_values():
    node = recipe(
        recipeInstructions=STEPS,
        nutrition={
            "@type": "NutritionInformation",
            "calories": "250 kcal",
            "servingSize": "1 cup",
            "proteinContent": 12,
            "nested": {"a": 1},
            "flag": True,
            "long": "x" * 500,
        },
    )

    assert extract(page(node)).source_nutrition == {
        "calories": "250 kcal",
        "servingSize": "1 cup",
        "proteinContent": 12,
    }
    assert (
        extract(page(recipe(recipeInstructions=STEPS, nutrition="lots"))).source_nutrition is None
    )
    assert extract(page(recipe(recipeInstructions=STEPS))).source_nutrition is None


# --- robustness ---
@pytest.mark.parametrize(
    "html",
    [
        b"",
        b"\x00\x01\x02 not html",
        b"<script type='application/ld+json'></script>",
        b"<script type='application/ld+json'>null</script>",
        b"<script type='application/ld+json'>[1, 2, \"x\"]</script>",
        b"<script type='application/ld+json'>{\"@type\": 5}</script>",
        b"<script type='application/ld+json'>" + b"[" * 5000 + b"</script>",
    ],
)
def test_garbage_does_not_crash(html):
    assert extract(html) is None


def test_deeply_nested_json_is_not_walked_forever():
    deep = recipe(recipeInstructions=STEPS)
    for _ in range(50):
        deep = {"@type": "Thing", "child": deep}

    assert extract(page(deep)) is None  # nested deeper than the limit: ignored, no crash


def test_utf8_and_legacy_encodings_are_decoded():
    node = recipe(recipeInstructions=["Usmaż żółtka."], name="Jajka po żydowsku")
    html = '<meta charset="iso-8859-2">' + page(node)

    assert extract(html.encode("iso-8859-2")).recipe.title == "Jajka po żydowsku"
