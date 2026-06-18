"""HTML parsing tests: link detection, hidden links, meta/X-robots, canonical."""

from app.crawler.parse import parse_html, parse_robots_directives, parse_x_robots_header

HTML = """
<html lang="en"><head>
  <title>Review of Acme</title>
  <meta name="description" content="A review">
  <meta name="robots" content="noindex, nofollow">
  <link rel="canonical" href="https://acme.test/canonical">
</head><body>
  <h1>Acme review</h1>
  <p>This is an in-content paragraph with several meaningful words about Acme.</p>
  <a href="https://acme.test/seo" rel="nofollow sponsored">Acme SEO</a>
  <footer><a href="https://acme.test/footer">footer link</a></footer>
  <div style="display:none"><a href="https://acme.test/hidden">hidden</a></div>
  <noscript><a href="https://acme.test/noscript">noscript link</a></noscript>
  <!-- <a href="https://acme.test/comment">comment link</a> -->
</body></html>
"""


def _by_norm(page):
    return {link.normalized_url: link for link in page.links}


def test_link_extraction_and_rel():
    page = parse_html(HTML, final_url="https://acme.test/page")
    links = _by_norm(page)
    seo = links["https://acme.test/seo"]
    assert seo.anchor_text == "Acme SEO"
    assert set(seo.rel) == {"nofollow", "sponsored"}
    assert seo.region == "body"


def test_footer_region_detected():
    page = parse_html(HTML, final_url="https://acme.test/page")
    assert _by_norm(page)["https://acme.test/footer"].region == "footer"


def test_css_hidden_link_flagged():
    page = parse_html(HTML, final_url="https://acme.test/page")
    assert _by_norm(page)["https://acme.test/hidden"].css_hidden is True


def test_noscript_link_flagged():
    page = parse_html(HTML, final_url="https://acme.test/page")
    assert _by_norm(page)["https://acme.test/noscript"].in_noscript is True


def test_comment_link_flagged():
    page = parse_html(HTML, final_url="https://acme.test/page")
    comment = _by_norm(page)["https://acme.test/comment"]
    assert comment.in_comment is True
    assert comment.css_hidden is True


def test_meta_robots_and_canonical():
    page = parse_html(HTML, final_url="https://acme.test/page")
    assert page.meta_robots.noindex is True
    assert page.meta_robots.nofollow is True
    assert page.canonical_url == "https://acme.test/canonical"
    assert page.canonical_count == 1
    assert page.signals.title == "Review of Acme"
    assert page.signals.language == "en"
    assert page.signals.word_count > 5


def test_parse_robots_directives_none():
    d = parse_robots_directives("none")
    assert d.none is True and d.noindex is True and d.nofollow is True


def test_parse_robots_directives_conflicting():
    d = parse_robots_directives("index, noindex")
    assert d.conflicting is True


def test_parse_robots_directives_ua_specific():
    d = parse_robots_directives("googlebot: noindex")
    assert d.ua_specific.get("googlebot") == "noindex"


def test_x_robots_header_most_restrictive():
    d = parse_x_robots_header(["unavailable_after: 01 Jan 2000", "noindex", "nofollow"])
    assert d.noindex is True
    assert d.nofollow is True
