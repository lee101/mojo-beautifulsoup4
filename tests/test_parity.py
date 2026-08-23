import re

import numpy as np
import pytest
from bs4 import BeautifulSoup as ReferenceSoup
from bs4.element import Comment as ReferenceComment
from bs4.element import Doctype as ReferenceDoctype

from mojo_beautifulsoup4 import (
    BeautifulSoup,
    Comment,
    Doctype,
    NavigableString,
    SoupStrainer,
    Tag,
)


def pair(markup):
    return BeautifulSoup(markup, "html.parser"), ReferenceSoup(markup, "html.parser")


def identities(nodes):
    return [
        (
            node.name,
            node.get("id"),
            tuple(node.get("class", [])),
            node.get_text("|", strip=True),
        )
        for node in nodes
    ]


@pytest.mark.parametrize(
    "markup",
    [
        '<div class="card wide" id="main">Hello &amp; <b>world</b><br/></div>',
        "<p>one<p>two",
        "<ul><li>a<li>b</ul>",
        '<input disabled data-x="a>b"><hr>',
        "text<div>x</div>tail",
    ],
)
def test_serialization_matches_html_parser(markup):
    ours, reference = pair(markup)
    assert str(ours) == str(reference)


def test_comments_doctype_and_processing_instruction():
    markup = "<!doctype html><?target value?><!--note--><p>x</p>"
    ours, reference = pair(markup)
    assert str(ours) == str(reference)
    assert isinstance(ours.contents[0], Doctype)
    assert isinstance(reference.contents[0], ReferenceDoctype)
    assert isinstance(ours.find(string="note"), Comment)
    assert isinstance(reference.find(string="note"), ReferenceComment)


def test_parse_construction_sets_parent_links():
    soup = BeautifulSoup("<!doctype html><?go?><main>text<!--note--></main>")
    assert all(node.parent is soup for node in soup.contents)
    assert all(node.parent is soup.main for node in soup.main.contents)


def test_raw_text_elements_match():
    markup = (
        '<script>if (a < b) x="</scriptx>"; &amp;</script>'
        "<style>a>b{}</style><title>x &amp; y</title>"
        "<textarea>one &lt; two</textarea>"
    )
    ours, reference = pair(markup)
    assert str(ours) == str(reference)
    assert ours.script.string == reference.script.string
    assert ours.style.string == reference.style.string
    assert ours.title.string == reference.title.string
    assert ours.textarea.string == reference.textarea.string


def test_unicode_and_entities_match():
    markup = "<p title='café &amp; tea'>雪 &lt; π &#169; &quot;x&quot;</p>"
    ours, reference = pair(markup)
    assert str(ours) == str(reference)
    assert ours.p.attrs == reference.p.attrs
    assert ours.p.get_text() == reference.p.get_text()


def test_find_all_names_and_limit():
    markup = "<main><p>A</p><div><p>B</p><span>C</span></div><p>D</p></main>"
    ours, reference = pair(markup)
    assert identities(ours.find_all(["p", "span"], limit=3)) == identities(
        reference.find_all(["p", "span"], limit=3)
    )
    assert identities(ours.main.find_all(True, recursive=False)) == identities(
        reference.main.find_all(True, recursive=False)
    )


def test_find_attributes_classes_and_regex():
    markup = """
    <a id="a1" class="button primary" href="/one">One</a>
    <a id="a2" class="button" href="/two">Two</a>
    <a id="a3">Three</a>
    """
    ours, reference = pair(markup)
    assert identities(ours.find_all("a", class_="button")) == identities(
        reference.find_all("a", class_="button")
    )
    assert identities(ours.find_all(href=re.compile(r"/t"))) == identities(
        reference.find_all(href=re.compile(r"/t"))
    )
    assert identities(ours.find_all(id=True)) == identities(reference.find_all(id=True))


def test_simd_comparison_tail_and_root_find_fast_path():
    markup = (
        '<article class="abcdefghijk tailmatch">one</article>'
        '<article class="abcdefghijX tailmatch">two</article>'
    )
    ours, reference = pair(markup)
    assert identities(ours.select(".abcdefghijk")) == identities(
        reference.select(".abcdefghijk")
    )
    assert identities(ours.find_all("article", class_="tailmatch")) == identities(
        reference.find_all("article", class_="tailmatch")
    )
    assert identities(ours.find_all("article", class_="abcdefghijk tailmatch")) == identities(
        reference.find_all("article", class_="abcdefghijk tailmatch")
    )


@pytest.mark.parametrize("delta", [-1, 3])
def test_prefilter_parallel_threshold_matches_serial_shape(delta):
    from mojo_beautifulsoup4 import _lib

    count = _lib.PREFILTER_PARALLEL_THRESHOLD + delta
    starts = np.zeros(count, dtype=np.int64)
    ends = np.full(count, 7, dtype=np.int64)
    empty = np.zeros(count, dtype=np.int64)
    result = _lib.prefilter(
        b"article",
        starts,
        ends,
        empty,
        empty,
        empty,
        empty,
        tag="article",
        element_id=None,
        classes=(),
    )
    assert result.shape == (count,)
    assert np.all(result)


def test_string_search_matches():
    markup = "<div><p>alpha</p><p><b>beta</b></p><!--gamma--></div>"
    ours, reference = pair(markup)
    assert list(map(str.__str__, ours.find_all(string=re.compile("a$")))) == list(
        map(str, reference.find_all(string=re.compile("a$")))
    )
    assert ours.find("p", string="alpha").get_text() == reference.find(
        "p", string="alpha"
    ).get_text()


def test_tree_navigation_matches():
    markup = "<section><h2>Title</h2> gap <p>A <b>B</b></p><p>C</p></section>"
    ours, reference = pair(markup)
    assert ours.b.parent.name == reference.b.parent.name
    assert [p.name for p in ours.b.parents] == [p.name for p in reference.b.parents]
    assert ours.h2.find_next_sibling("p").get_text() == reference.h2.find_next_sibling(
        "p"
    ).get_text()
    assert ours.section.find_all("p")[1].find_previous("h2").string == reference.section.find_all(
        "p"
    )[1].find_previous("h2").string


def test_text_string_and_stripped_strings():
    markup = "<div>  A <span> B <i>C</i> </span>\n D </div>"
    ours, reference = pair(markup)
    assert ours.div.get_text("|", strip=True) == reference.div.get_text("|", strip=True)
    assert list(ours.div.stripped_strings) == list(reference.div.stripped_strings)
    assert ours.i.string == reference.i.string
    assert ours.div.string is None and reference.div.string is None


@pytest.mark.parametrize(
    "selector",
    [
        "main article.card",
        "article.card > h2",
        "#featured + article",
        "#featured ~ article",
        "article.card, nav a",
        "*",
        "article[data-kind]",
        'article[data-kind="news"]',
        'article[data-kind~="news"]',
        'article[data-kind|="news"]',
        'article[data-kind*="ew"]',
        'a[href^="/"][href$="2"]',
        ".card.primary",
    ],
)
def test_basic_css_selector_parity(selector):
    markup = """
    <main>
      <article id="featured" class="card primary" data-kind="news"><h2>A</h2><a href="/p1">one</a></article>
      <article class="card" data-kind="note"><h2>B</h2><a href="/p2">two</a></article>
      <article class="other"><h2>C</h2></article>
      <nav><a href="https://example.test">outside</a></nav>
    </main>
    """
    ours, reference = pair(markup)
    assert identities(ours.select(selector)) == identities(reference.select(selector))


@pytest.mark.parametrize(
    "selector",
    [
        "li:first-child",
        "li:last-child",
        "li:only-child",
        "li:nth-child(2n+1)",
        "li:nth-last-child(2)",
        "li:not(.off)",
        "li:is(.hot, .off)",
        "li:where(.hot, .off)",
        "p:first-of-type",
        "p:last-of-type",
        "ul:only-of-type",
        "p:nth-of-type(2)",
        "p:nth-last-of-type(2)",
        "div:empty",
        "section:has(> p.hot)",
        'section:-soup-contains("two")',
    ],
)
def test_pseudo_selector_parity(selector):
    markup = """
    <section><p class="hot">one</p><p>two</p><ul>
      <li class="hot">a</li><li class="off">b</li><li>c</li><li class="hot">d</li>
    </ul></section><div></div><div> </div>
    """
    ours, reference = pair(markup)
    assert identities(ours.select(selector)) == identities(reference.select(selector))


def test_scoped_select_and_select_one():
    markup = "<div id='a'><p>A</p></div><div id='b'><p>B</p><span><p>C</p></span></div>"
    ours, reference = pair(markup)
    assert identities(ours.select_one("#b").select(":scope > p")) == identities(
        reference.select_one("#b").select(":scope > p")
    )
    assert ours.select_one("#b p").get_text() == reference.select_one("#b p").get_text()


def test_bytes_encoding_detection():
    markup = b'<meta charset="windows-1252"><p>\x93quoted\x94</p>'
    ours, reference = pair(markup)
    assert ours.original_encoding == reference.original_encoding
    assert ours.p.get_text() == reference.p.get_text()


def test_mutation_api_matches_result():
    ours, reference = pair("<div><p>A</p><p>B</p></div>")
    ours_new = ours.new_tag("a", href="/")
    ours_new.append("link")
    ref_new = reference.new_tag("a", href="/")
    ref_new.append("link")
    ours.div.insert(1, ours_new)
    reference.div.insert(1, ref_new)
    ours.div.find_all("p")[0].replace_with("first")
    reference.div.find_all("p")[0].replace_with("first")
    ours.div.find_all("p")[0].extract()
    reference.div.find_all("p")[0].extract()
    assert str(ours) == str(reference)


def test_selector_cache_is_invalidated_by_append():
    soup = BeautifulSoup("<div><p class='old'>A</p></div>", "html.parser")
    assert soup.select(".new") == []
    tag = soup.new_tag("p", attrs={"class": ["new"]})
    soup.div.append(tag)
    assert soup.select_one(".new") is tag


def test_selector_cache_is_invalidated_by_attribute_mutation():
    soup = BeautifulSoup("<p class='old'>A &amp; B</p>", "html.parser")
    assert soup.select_one(".old") is soup.p
    soup.p["class"].append("new")
    assert soup.select_one(".new") is soup.p
    assert str(soup.p.string) == "A & B"
    assert str(soup) == '<p class="old new">A &amp; B</p>'


def test_soup_strainer_covered_behavior():
    markup = "<div><a href='/a'>A</a></div><p>B</p>"
    soup = BeautifulSoup(markup, "html.parser", parse_only=SoupStrainer("a"))
    assert str(soup) == '<a href="/a">A</a>'


def test_malformed_less_than_is_preserved():
    markup = "<<<<<<p>x</p><"
    ours, reference = pair(markup)
    assert str(ours) == str(reference)


def test_public_types_and_attribute_mapping():
    soup = BeautifulSoup("<div data-x='1'>text</div>", "html.parser")
    assert isinstance(soup.div, Tag)
    assert isinstance(soup.div.string, NavigableString)
    assert soup.div["data-x"] == "1"
    assert soup.div.get_attribute_list("missing") == []
    assert soup.div.has_attr("data-x")


@pytest.mark.parametrize(
    "bad_array, error",
    [
        (np.zeros(2, dtype=np.int32), TypeError),
        (np.zeros((1, 2), dtype=np.int64), ValueError),
        (np.zeros(4, dtype=np.int64)[::2], ValueError),
    ],
)
def test_prefilter_rejects_unsafe_array_layouts(bad_array, error):
    from mojo_beautifulsoup4 import _lib

    good = np.zeros(2, dtype=np.int64)
    with pytest.raises(error):
        _lib.prefilter(
            b"",
            bad_array,
            good,
            good,
            good,
            good,
            good,
            tag=None,
            element_id=None,
            classes=(),
        )


def test_prefilter_rejects_mismatched_and_out_of_bounds_offsets():
    from mojo_beautifulsoup4 import _lib

    one = np.zeros(1, dtype=np.int64)
    two = np.zeros(2, dtype=np.int64)
    with pytest.raises(ValueError, match="entries"):
        _lib.prefilter(
            b"x", one, two, one, one, one, one,
            tag=None, element_id=None, classes=(),
        )
    out_of_bounds = np.ones(1, dtype=np.int64) * 2
    with pytest.raises(ValueError, match="offsets"):
        _lib.prefilter(
            b"x", one, out_of_bounds, one, one, one, one,
            tag=None, element_id=None, classes=(),
        )


def test_tokenizer_empty_and_dense_malformed_input_stays_in_bounds():
    from mojo_beautifulsoup4 import _lib

    assert all(len(field) == 0 for field in _lib.tokenize(b""))
    fields = _lib.tokenize(b"<" * 257)
    assert all(len(field) == 257 for field in fields)
