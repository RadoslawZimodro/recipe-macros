"""Cleaning a page down to the text the AI reads."""

from app.services.page_text import page_content

BASE = "https://blog.example.test/przepis"


def content(html, limit=30_000):
    return page_content(html.encode(), base_url=BASE, limit=limit)


def test_page_furniture_is_removed_and_the_content_stays():
    html = """
    <html><head><title>T</title><style>.a{color:red}</style><script>var secret = 1;</script></head>
    <body>
      <header><nav>Menu Start Przepisy</nav></header>
      <main><h1>Pierogi</h1><p>Zagnieć ciasto.</p></main>
      <aside>Reklama kup teraz</aside>
      <form><input value="x"><button>Zapisz się</button></form>
      <footer>© Blog</footer>
      <noscript>Włącz JavaScript</noscript>
    </body></html>
    """

    text = content(html).text

    assert "Pierogi" in text and "Zagnieć ciasto." in text
    for dropped in ("Menu", "Reklama", "Zapisz", "© Blog", "secret", "color:red", "JavaScript"):
        assert dropped not in text


def test_block_elements_make_lines_and_inline_elements_do_not():
    html = (
        "<body><p>Pokrój <b>cebulę</b> drobno.</p>"
        "<ul><li>200 g <span>mąki</span></li><li>jajko</li></ul>a<br>b</body>"
    )

    lines = content(html).text.splitlines()

    assert "Pokrój cebulę drobno." in lines
    assert "200 g mąki" in lines and "jajko" in lines
    assert lines[-2:] == ["a", "b"]


def test_blank_runs_and_spaces_are_collapsed():
    text = content("<body><p>a</p><p></p><p></p><p></p><p>b    c  d</p></body>").text

    assert "\n\n\n" not in text
    assert "b c d" in text


def test_short_pages_are_not_truncated():
    result = content("<body><p>krótko</p></body>", limit=1000)

    assert result.truncated is False and result.text == "krótko"


def test_long_pages_are_cut_around_the_ingredients_not_from_the_top():
    story = "Historia rodzinna. " * 400  # ~7600 characters before the recipe
    html = (
        f"<body><p>{story}</p><h2>Składniki</h2><ul><li>500 g mąki</li></ul><p>Koniec.</p></body>"
    )

    result = content(html, limit=3000)

    assert result.truncated is True
    assert len(result.text) <= 3000
    assert "500 g mąki" in result.text  # a plain cut from the top would have lost it


def test_long_page_without_an_ingredients_heading_is_cut_from_the_top():
    result = content("<body><p>" + "a" * 5000 + "</p></body>", limit=1000)

    assert result.truncated is True and result.text == "a" * 1000


def test_english_ingredients_heading_is_found_too():
    html = "<body><p>" + "story " * 1000 + "</p><h2>Ingredients</h2><p>2 eggs</p></body>"

    assert "2 eggs" in content(html, limit=2000).text


def test_image_comes_from_open_graph_and_is_made_absolute():
    html = '<head><meta property="og:image" content="/img/a.jpg"></head><body>x</body>'

    assert content(html).image_url == "https://blog.example.test/img/a.jpg"


def test_image_falls_back_to_twitter_card_and_rejects_bad_schemes():
    twitter = '<head><meta name="twitter:image" content="https://cdn.example.test/t.jpg"></head>'
    assert content(twitter + "<body>x</body>").image_url == "https://cdn.example.test/t.jpg"

    bad = '<head><meta property="og:image" content="javascript:alert(1)"></head><body>x</body>'
    assert content(bad).image_url is None
    assert content("<body>x</body>").image_url is None


def test_garbage_input_does_not_crash():
    assert content("").text == ""
    assert page_content(b"\x00\x01\x02", base_url=BASE, limit=100).image_url is None
