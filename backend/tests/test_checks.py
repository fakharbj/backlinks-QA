"""QA check-catalog tests (PRD §8.6) driven through evaluate()."""

import pytest

from app.crawler.normalize import normalize_url
from app.crawler.parse import parse_x_robots_header
from app.crawler.types import CrawlArtifact, CrawlRequest, FetchError, ParsedLink, RedirectHop
from app.qa import evaluate
from app.qa.enums import OverallStatus


def clean():
    req = CrawlRequest(
        source_url="https://pub.test/p",
        target_url="https://acme.test/seo",
        expected_anchor_text="Acme SEO",
    )
    art = CrawlArtifact(
        request=req, http_status=200, final_url="https://pub.test/p", content_type="text/html"
    )
    art.robots.source_allowed = True
    link = ParsedLink(
        href="https://acme.test/seo",
        resolved_url="https://acme.test/seo",
        normalized_url="https://acme.test/seo",
        anchor_text="Acme SEO",
    )
    art.matched_links = [link]
    art.all_links = [link]
    art.found_in_raw = True
    return art, link


def labels(result):
    return {i.label.value for i in result.issues}


def codes(result):
    return {i.code for i in result.issues}


def test_http_404_is_fail():
    art, _ = clean()
    art.http_status = 404
    art.matched_links = []
    result = evaluate(art)
    assert result.status is OverallStatus.FAIL
    assert "SOURCE_404" in labels(result)


def test_http_503_is_unknown():
    art, _ = clean()
    art.http_status = 503
    art.matched_links = []
    result = evaluate(art)
    assert result.status is OverallStatus.UNKNOWN


def test_redirect_loop_is_fail():
    art, _ = clean()
    art.fetch_error = FetchError.REDIRECT_LOOP
    result = evaluate(art)
    assert result.status is OverallStatus.FAIL
    assert "REDIRECT_LOOP" in labels(result)


def test_excessive_redirects_warns():
    art, _ = clean()
    art.redirect_chain = [
        RedirectHop(url=f"https://pub.test/{i}", status=301, location=f"https://pub.test/{i+1}")
        for i in range(5)
    ] + [RedirectHop(url="https://pub.test/final", status=200)]
    result = evaluate(art)
    assert "RDR-02" in codes(result)


def test_nofollow_when_follow_expected():
    art, link = clean()
    link.rel = ["nofollow"]
    result = evaluate(art)
    assert result.status is OverallStatus.WARNING
    assert "LINK_NOFOLLOW" in labels(result)
    assert result.is_followable is False


def test_anchor_changed():
    art, link = clean()
    link.anchor_text = "totally different anchor"
    result = evaluate(art)
    assert "ANCHOR_CHANGED" in labels(result)


def test_canonical_cross_domain_is_fail():
    art, _ = clean()
    art.canonical_url = "https://other.test/x"
    art.canonical_resolved = normalize_url("https://other.test/x").normalized
    art.canonical_count = 1
    result = evaluate(art)
    assert result.status is OverallStatus.FAIL
    assert "CANONICAL_CROSS_DOMAIN" in labels(result)


def test_meta_noindex_is_fail():
    art, _ = clean()
    art.meta_robots.index = False
    result = evaluate(art)
    assert result.status is OverallStatus.FAIL
    assert "PAGE_NOINDEX" in labels(result)


def test_x_robots_noindex_is_fail():
    art, _ = clean()
    art.x_robots = parse_x_robots_header(["noindex"])
    result = evaluate(art)
    assert result.status is OverallStatus.FAIL
    assert "X_ROBOTS_NOINDEX" in labels(result)


def test_robots_blocked_unread_routes_to_review_unscored():
    # Source disallowed AND we honored it (never fetched) = we couldn't read
    # the link → "needs review", not a confident FAIL, and NOT scored down.
    req = CrawlRequest(source_url="https://pub.test/p", target_url="https://acme.test/seo")
    art = CrawlArtifact(request=req)
    art.fetch_error = FetchError.BLOCKED_ROBOTS
    art.robots.source_allowed = False
    result = evaluate(art)
    assert result.status is OverallStatus.NEEDS_MANUAL_REVIEW
    assert "ROBOTS_BLOCKED" in labels(result)
    assert "RBT-03" in codes(result)


def test_robots_blocked_but_page_read_gives_real_verdict():
    # The QA lab fetches with respect_robots=False: when we DID read the page
    # and found the link, robots.txt is an indexability NOTE (RBT-05), never
    # a "needs review" blocker — the verdict comes from real evidence.
    art, _ = clean()
    art.robots.source_allowed = False
    result = evaluate(art)
    assert result.status is not OverallStatus.NEEDS_MANUAL_REVIEW
    assert result.link_found is True
    assert "RBT-05" in codes(result)
    assert "RBT-03" not in codes(result)
    assert "ROBOTS_BLOCKED" in labels(result)  # still visible as a note


def test_js_injected_link_missing_is_review_not_fail():
    # Medium/Substack inject article-body links via JS: the page HAS nav/footer
    # links but the target link is absent. When the engine flagged the page as
    # JS-driven / proxy-reached, this is "couldn't confirm" (REVIEW), never a
    # confident LINK_MISSING / FAIL.
    from app.crawler.types import ParsedLink

    req = CrawlRequest(source_url="https://medium.com/@x/post", target_url="https://acme.test/seo")
    art = CrawlArtifact(request=req, http_status=200, final_url="https://medium.com/@x/post",
                        content_type="text/html")
    art.robots.source_allowed = True
    # Nav/footer links present, but NOT the target link.
    art.all_links = [
        ParsedLink(href="https://medium.com/about", resolved_url="https://medium.com/about",
                   normalized_url="https://medium.com/about", anchor_text="About"),
    ]
    art.js_render_suspected = True
    result = evaluate(art)
    assert result.status is OverallStatus.NEEDS_MANUAL_REVIEW
    assert "JS_RENDER_REQUIRED" in labels(result)
    assert "LINK_MISSING" not in labels(result)


def test_plain_page_missing_link_still_fails():
    # A normal HTML page (not JS-flagged) that genuinely lacks the link is a
    # real LINK_MISSING / FAIL — the review path must not swallow true misses.
    from app.crawler.types import ParsedLink

    req = CrawlRequest(source_url="https://blog.test/p", target_url="https://acme.test/seo")
    art = CrawlArtifact(request=req, http_status=200, final_url="https://blog.test/p",
                        content_type="text/html")
    art.robots.source_allowed = True
    art.all_links = [
        ParsedLink(href="https://other.test/x", resolved_url="https://other.test/x",
                   normalized_url="https://other.test/x", anchor_text="Other"),
    ]
    # js_render_suspected stays False (default) → genuine miss.
    result = evaluate(art)
    assert result.status is OverallStatus.FAIL
    assert "LINK_MISSING" in labels(result)


def test_soft_404_is_fail():
    art, _ = clean()
    art.detection.soft_404 = True
    art.matched_links = []
    result = evaluate(art)
    assert result.status is OverallStatus.FAIL
    assert "SOFT_404" in labels(result)


def test_captcha_routes_to_review_and_caps_score():
    art, _ = clean()
    art.detection.captcha = True
    result = evaluate(art)
    assert result.status is OverallStatus.NEEDS_MANUAL_REVIEW
    assert result.score <= 25
    assert "CAPTCHA_DETECTED" in labels(result)


def test_wrong_target_same_domain():
    art, _ = clean()
    other = ParsedLink(
        href="https://acme.test/other",
        resolved_url="https://acme.test/other",
        normalized_url="https://acme.test/other",
    )
    art.matched_links = []
    art.found_in_raw = False
    art.all_links = [other]
    result = evaluate(art)
    assert "WRONG_TARGET" in labels(result)


def test_js_only_link_flagged():
    art, _ = clean()
    art.found_in_raw = False
    art.found_in_rendered = True
    result = evaluate(art)
    assert "JS_RENDER_REQUIRED" in labels(result)


def test_dns_error_is_fail():
    art, _ = clean()
    art.fetch_error = FetchError.DNS
    art.http_status = None
    art.matched_links = []
    result = evaluate(art)
    assert result.status is OverallStatus.FAIL
    assert "DNS_ERROR" in labels(result)


def test_non_html_content_is_review():
    art, _ = clean()
    art.content_type = "application/pdf"
    art.matched_links = []
    result = evaluate(art)
    assert result.status is OverallStatus.NEEDS_MANUAL_REVIEW


@pytest.mark.parametrize("status_code,expected_label", [(403, "SOURCE_403"), (500, "SOURCE_5XX")])
def test_http_error_labels(status_code, expected_label):
    art, _ = clean()
    art.http_status = status_code
    art.matched_links = []
    result = evaluate(art)
    assert expected_label in labels(result)
