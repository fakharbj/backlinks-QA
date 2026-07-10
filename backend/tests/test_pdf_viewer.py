"""PDF/document-viewer link recovery — no false LINK_MISSING on viewer pages.

Layer 1: SVG-overlay anchors (xlink:href) are extracted like normal links.
Layer 2: an unmatched link on a viewer page routes to NEEDS_MANUAL_REVIEW,
never a confident CRITICAL LINK_MISSING; normal pages keep the hard FAIL.
"""

from app.crawler.parse import parse_html
from app.crawler.types import CrawlArtifact, CrawlMode, CrawlRequest, ParsedLink
from app.qa import evaluate
from app.qa.enums import OverallStatus


# The exact real-world shape the team reported: a PDF viewer's extracted-link
# SVG overlay (data-link-id / class="web extracted" / <rect> child).
_VIEWER_HTML = """
<html><body>
<div class="pdf_viewer">
  <a class="web extracted" data-page-number="3" data-link-id="1603985224"
     href="https://www.beyerbrown.com/" rel="nofollow" target="_blank">
    <title>https://www.beyerbrown.com/</title>
    <rect height="47.78" width="706.1" x="272" y="2640.67"></rect>
  </a>
</div>
</body></html>
"""


def test_extracted_overlay_anchor_is_parsed_and_page_flagged():
    page = parse_html(_VIEWER_HTML, final_url="https://host.test/doc")
    hrefs = {l.normalized_url for l in page.links}
    assert any("beyerbrown.com" in h for h in hrefs)  # the link IS extracted
    assert page.signals.doc_viewer is True


def test_svg_xlink_href_fallback():
    html = '<svg><a xlink:href="https://acme.test/seo"><rect/></a></svg>'
    page = parse_html(html, final_url="https://host.test/p")
    assert any("acme.test/seo" in l.normalized_url for l in page.links)


def test_pdf_url_flags_viewer():
    page = parse_html("<html><body>x</body></html>", final_url="https://host.test/file.pdf")
    assert page.signals.doc_viewer is True


def _artifact(doc_viewer: bool) -> CrawlArtifact:
    req = CrawlRequest(source_url="https://pub.test/doc", target_url="https://acme.test/")
    art = CrawlArtifact(
        request=req, http_status=200, final_url="https://pub.test/doc", content_type="text/html"
    )
    art.robots.source_allowed = True
    # Page has SOME links (viewer chrome) but none to the target.
    other = ParsedLink(
        href="https://viewerhost.test/help", resolved_url="https://viewerhost.test/help",
        normalized_url="https://viewerhost.test/help", anchor_text="Help",
    )
    art.all_links = [other]
    art.matched_links = []
    art.signals.doc_viewer = doc_viewer
    art.signals.doc_viewer_signature = "extracted_overlay" if doc_viewer else None
    return art


def test_missing_link_on_viewer_page_is_review_not_fail():
    result = evaluate(_artifact(doc_viewer=True))
    assert result.status is OverallStatus.NEEDS_MANUAL_REVIEW
    assert "LINK_MISSING" not in {i.label.value for i in result.issues}


def test_missing_link_on_normal_page_still_fails():
    result = evaluate(_artifact(doc_viewer=False))
    assert result.status is OverallStatus.FAIL
    assert "LINK_MISSING" in {i.label.value for i in result.issues}


def test_normal_article_not_flagged_as_viewer():
    html = "<html><body><p>A normal article. <a href='https://x.test/'>x</a> " + ("word " * 300) + "</p></body></html>"
    page = parse_html(html, final_url="https://host.test/article")
    assert page.signals.doc_viewer is False
