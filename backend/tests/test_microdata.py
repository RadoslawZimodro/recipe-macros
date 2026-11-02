"""Recipe extraction from schema.org Microdata. Pages in tests/fixtures/recipes are synthetic."""

import json
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from app.services import microdata
from app.services.recipe_extractor import extract_recipe

FIXTURES = Path(__file__).parent / "fixtures" / "recipes"
SOURCE = "https://example.test/przepis"
RECIPE = "https://schema.org/Recipe"


def extract(html, base=SOURCE):
    data = html if isinstance(html, bytes) else html.encode()
    return extract_recipe(data, base_url=base, source_url=SOURCE)


def fixture(name, base=SOURCE):
    return extract((FIXTURES / name).read_bytes(), base)


def recipe_html(inner, itemtype=RECIPE, attrs=""):
    return f'<div itemscope itemtype="{itemtype}" {attrs}>{inner}</div>'


STEP = '<p itemprop="recipeInstructions">Ugotuj.</p>'
NAME = '<h1 itemprop="name">Zupa</h1>'


def nodes(html):
    return list(microdata.microdata_recipe_nodes(BeautifulSoup(html, "lxml")))


# --- realistic pages ---
def test_polish_blog_with_nested_author_lists_and_inline_markup():
    result = fixture("microdata_pl_blog.html", base="https://blog.example.test/pierogi")

    r = result.recipe
    assert result.method == "microdata"
    assert r.title == "Pierogi ruskie z cebulką"  # not the author's name
    assert r.description == "Klasyczne pierogi z serem, ziemniakami i smażoną cebulką."
    assert r.image_url == "https://blog.example.test/uploads/pierogi.jpg"  # <img src>, absolute
    assert r.servings == 40
    assert (r.prep_time_min, r.cook_time_min) == (60, 15)  # <meta content> and <time datetime>
    assert r.tags == ["danie główne", "pierogi", "obiad", "kuchnia polska"]
    assert [i.raw_text for i in r.ingredients] == [
        "500 g mąki pszennej",  # the <span> inside the <li> does not split the line
        "1 szklanka ciepłej wody",
        "500 g ziemniaków",
        "250 g białego sera",
        "2 cebule",
        "sól, pieprz",
    ]
    assert [s.instruction for s in r.steps] == [
        "Z mąki i wody zagnieć elastyczne ciasto.",  # <b> does not split the step
        "Ugotuj ziemniaki i przeciśnij je przez praskę, dodaj ser.",
        "Wykrój kółka, nałóż farsz i sklej pierogi.",
        "Gotuj w osolonej wodzie 3 minuty od wypłynięcia.",
    ]
    assert result.source_nutrition == {"calories": "180 kcal", "proteinContent": "6 g"}


def test_nested_steps_itemref_and_a_review_that_must_not_leak():
    result = fixture("microdata_howto_itemref.html")

    r = result.recipe
    assert r.title == "Spiced Carrot Soup"  # the Review's name ("Great soup!") is not ours
    assert r.image_url == "https://cdn.example.test/carrot-soup.jpg"  # <link href>
    assert r.servings == 4
    assert (r.prep_time_min, r.cook_time_min) == (10, 30)
    assert [s.instruction for s in r.steps] == [
        "Sweat the onion in butter until soft.",
        "Add carrots, stock and cumin; simmer for 25 minutes.",
        "Blend until smooth and season.",
    ]
    # these four <li> live OUTSIDE the recipe element and are pulled in through itemref
    assert [i.raw_text for i in r.ingredients] == [
        "500 g carrots",
        "1 onion",
        "1 tsp ground cumin",
        "750 ml vegetable stock",
    ]


# --- JSON-LD vs Microdata ---
def test_json_ld_wins_when_both_formats_have_a_usable_recipe():
    ld = {
        "@context": "https://schema.org",
        "@type": "Recipe",
        "name": "Z JSON-LD",
        "recipeIngredient": ["1 jajko"],
    }
    html = f'<script type="application/ld+json">{json.dumps(ld)}</script>' + recipe_html(
        '<h1 itemprop="name">Z Microdata</h1><p itemprop="recipeIngredient">a</p>'
        '<p itemprop="recipeIngredient">b</p>'
    )

    result = extract(html)

    assert result.recipe.title == "Z JSON-LD" and result.method == "jsonld"


def test_microdata_is_used_when_the_json_ld_recipe_is_only_a_teaser():
    ld = {"@context": "https://schema.org", "@type": "Recipe", "name": "Tylko nazwa"}
    html = f'<script type="application/ld+json">{json.dumps(ld)}</script>' + recipe_html(
        NAME + '<p itemprop="recipeIngredient">1 jajko</p>'
    )

    result = extract(html)

    assert result.recipe.title == "Zupa" and result.method == "microdata"


def test_microdata_is_used_when_the_json_ld_block_is_broken():
    html = '<script type="application/ld+json">{oops</script>' + recipe_html(NAME + STEP)

    assert extract(html).method == "microdata"


# --- which elements are recipes ---
@pytest.mark.parametrize(
    "itemtype",
    [
        "https://schema.org/Recipe",
        "http://schema.org/Recipe",
        "http://schema.org/Recipe/",
        "HTTPS://SCHEMA.ORG/RECIPE",
        "https://schema.org/Thing https://schema.org/Recipe",
    ],
)
def test_recipe_itemtype_spellings(itemtype):
    assert extract(recipe_html(NAME + STEP, itemtype=itemtype)).recipe.title == "Zupa"


@pytest.mark.parametrize(
    "html",
    [
        recipe_html(NAME + STEP, itemtype="https://schema.org/Article"),
        recipe_html(NAME + STEP, itemtype="https://schema.org/RecipeBox"),  # not a Recipe
        f'<div itemtype="{RECIPE}">{NAME}{STEP}</div>',  # itemtype without itemscope
        f"<div itemscope>{NAME}{STEP}</div>",  # itemscope without a type
        "<div itemprop='name'>x</div>",
    ],
)
def test_other_items_are_ignored(html):
    assert extract(html) is None


def test_needs_a_title_and_content_like_json_ld():
    assert extract(recipe_html(STEP)) is None
    assert extract(recipe_html(NAME)) is None  # a teaser
    assert extract(recipe_html(NAME + '<p itemprop="recipeIngredient">1 jajko</p>')) is not None


def test_the_fuller_of_several_recipes_wins():
    html = recipe_html(
        '<h1 itemprop="name">Krótki</h1><p itemprop="recipeIngredient">a</p>'
    ) + recipe_html(
        '<h1 itemprop="name">Pełny</h1><p itemprop="recipeIngredient">a</p>'
        '<p itemprop="recipeIngredient">b</p><p itemprop="recipeInstructions">c</p>'
    )

    assert extract(html).recipe.title == "Pełny"


# --- how a property's value is read (HTML Microdata spec) ---
@pytest.mark.parametrize(
    ("element", "expected"),
    [
        ('<meta itemprop="recipeYield" content="12 sztuk">', 12),
        ('<span itemprop="recipeYield">6 porcji</span>', 6),
        ('<data itemprop="recipeYield" value="8">osiem</data>', 8),
        ('<span itemprop="recipeYield"><b>3</b> osoby</span>', 3),
    ],
)
def test_value_sources_for_plain_properties(element, expected):
    assert extract(recipe_html(NAME + STEP + element)).recipe.servings == expected


@pytest.mark.parametrize(
    "element",
    [
        '<time itemprop="prepTime" datetime="PT25M">25 min</time>',
        '<meta itemprop="prepTime" content="PT25M">',
        '<span itemprop="prepTime">PT25M</span>',
    ],
)
def test_durations_from_time_meta_or_text(element):
    assert extract(recipe_html(NAME + STEP + element)).recipe.prep_time_min == 25


@pytest.mark.parametrize(
    ("element", "expected"),
    [
        ('<img itemprop="image" src="/a.jpg">', "https://example.test/a.jpg"),
        (
            '<link itemprop="image" href="https://cdn.example.test/b.jpg">',
            "https://cdn.example.test/b.jpg",
        ),
        ('<a itemprop="image" href="c.jpg">zdjęcie</a>', "https://example.test/c.jpg"),
        (
            '<meta itemprop="image" content="https://cdn.example.test/d.jpg">',
            "https://cdn.example.test/d.jpg",
        ),
        ('<img itemprop="image" src="javascript:alert(1)">', None),
        ('<img itemprop="image">', None),
    ],
)
def test_image_sources(element, expected):
    assert extract(recipe_html(NAME + STEP + element)).recipe.image_url == expected


def test_one_element_may_carry_several_property_names():
    node = nodes(recipe_html('<h1 itemprop="name headline">Zupa</h1>' + STEP))[0]

    assert node["name"] == "Zupa" and node["headline"] == "Zupa"


def test_repeated_properties_become_lists_and_single_ones_stay_scalar():
    node = nodes(
        recipe_html(NAME + '<i itemprop="x">a</i><i itemprop="x">b</i><i itemprop="y">c</i>')
    )[0]

    assert node["x"] == ["a", "b"] and node["y"] == "c"


def test_properties_inside_plain_wrappers_belong_to_the_recipe():
    html = recipe_html(
        '<div class="a"><section><h1 itemprop="name">Zupa</h1></section></div>'
        '<div itemprop="wrapper"><span itemprop="recipeInstructions">Ugotuj.</span></div>'
    )

    assert extract(html).recipe.steps[0].instruction == "Ugotuj."


def test_nested_items_keep_their_own_properties():
    node = nodes(
        recipe_html(
            NAME + '<div itemprop="author" itemscope itemtype="https://schema.org/Person">'
            '<span itemprop="name">Jan</span></div>'
        )
    )[0]

    assert node["name"] == "Zupa"  # the author's name stays inside the author
    assert node["author"]["name"] == "Jan"
    assert node["author"]["@type"] == ["https://schema.org/Person"]


def test_a_nested_item_without_itemprop_is_not_a_property():
    node = nodes(
        recipe_html(
            NAME
            + '<div itemscope itemtype="https://schema.org/Thing"><i itemprop="name">Obcy</i></div>'
        )
    )[0]

    assert node == {"@type": [RECIPE], "name": "Zupa"}


def test_missing_itemref_target_is_ignored():
    html = recipe_html(NAME + STEP, attrs='itemref="nie-ma tez-nie-ma"')

    assert extract(html).recipe.title == "Zupa"


def test_line_structure_comes_from_block_elements_and_br_only():
    html = recipe_html(
        NAME + '<div itemprop="recipeInstructions">Pokrój <i>cebulę</i> drobno.<br>Podsmaż ją.'
        "<ul><li>Dodaj sól</li><li>Dodaj pieprz</li></ul></div>"
    )

    assert [s.instruction for s in extract(html).recipe.steps] == [
        "Pokrój cebulę drobno.",
        "Podsmaż ją.",
        "Dodaj sól",
        "Dodaj pieprz",
    ]


def test_script_and_style_text_inside_a_property_is_not_content():
    html = recipe_html(
        NAME + '<div itemprop="recipeInstructions">Ugotuj.'
        "<script>alert(1)</script><style>p{}</style></div>"
    )

    assert [s.instruction for s in extract(html).recipe.steps] == ["Ugotuj."]


# --- robustness ---
def test_garbage_and_hostile_pages_do_not_crash():
    assert extract(b"") is None
    assert extract(b"\x00\x01 itemscope itemtype") is None
    deep = "<div>" * 2000 + recipe_html(NAME + STEP) + "</div>" * 2000  # no recursion limit hit
    assert extract(deep).recipe.title == "Zupa"


def test_deeply_nested_items_stop_at_the_depth_limit():
    html = NAME + STEP
    for _ in range(microdata.MAX_DEPTH + 5):
        html = f'<div itemprop="child" itemscope itemtype="https://schema.org/Thing">{html}</div>'

    assert extract(recipe_html(html)) is None  # the real name/steps sit too deep to be reached


def test_element_budget_limits_the_work(monkeypatch):
    monkeypatch.setattr(microdata, "MAX_ELEMENTS", 10)
    lines = "".join('<p itemprop="recipeIngredient">x</p>' for _ in range(500))

    assert len(extract(recipe_html(NAME + lines)).recipe.ingredients) < 20


def test_many_recipes_on_one_page_do_not_blow_up():
    html = "".join(recipe_html(NAME + STEP) for _ in range(200))

    assert extract(html).recipe.title == "Zupa"
