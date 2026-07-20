"""Temp QA lab scoring lens — SEO-outcome rules (owner spec)."""

from __future__ import annotations

from app.crawler.types import CrawlArtifact, CrawlRequest, FetchError
from app.qa.enums import IssueCategory, IssueLabel, OverallStatus, Severity
from app.qa.types import Issue, QAResult
from app.services.qa_lab_scoring import lab_verdict


def _art(**kw) -> CrawlArtifact:
    # is_html is a computed property (from content_type) — never settable.
    kw.pop("is_html", None)
    req = CrawlRequest(source_url="https://src.test/p", target_url="https://acme.test/x")
    art = CrawlArtifact(request=req, content_type="text/html")
    art.robots.source_allowed = True
    for k, v in kw.items():
        setattr(art, k, v)
    return art


def _result(*labels, link_found=False, followable=None, http=200) -> QAResult:
    issues = [
        Issue(code=f"T-{i}", label=lbl, category=IssueCategory.LNK, severity=Severity.HIGH, message=lbl.value)
        for i, lbl in enumerate(labels)
    ]
    return QAResult(
        status=OverallStatus.PASS, score=100, grade_band=None,
        is_followable=followable, is_indexable=None, issues=issues,
        link_found=link_found, http_status=http,
    )


def test_error_page_is_not_scored():
    # 422/403/5xx we couldn't read → NEEDS_MANUAL_REVIEW, score None (never a number).
    art = _art(http_status=422, is_html=True, fetch_error=FetchError.NONE)
    v = lab_verdict(art, _result(IssueLabel.HTTP_ERROR, http=422))
    assert v["status"] == "NEEDS_MANUAL_REVIEW"
    assert v["score"] is None
    assert "couldn't" in v["summary"].lower() or "verify" in v["summary"].lower()


def test_404_page_gone_is_zero():
    art = _art(http_status=404, is_html=True, fetch_error=FetchError.NONE)
    v = lab_verdict(art, _result(IssueLabel.SOURCE_404, http=404))
    assert v["status"] == "FAIL" and v["score"] == 0


def test_missing_link_on_200_is_zero():
    art = _art(http_status=200, is_html=True, fetch_error=FetchError.NONE)
    v = lab_verdict(art, _result(IssueLabel.LINK_MISSING, link_found=False))
    assert v["status"] == "FAIL" and v["score"] == 0
    assert v["link_found"] is False


def test_js_suspected_missing_is_review_not_zero():
    art = _art(http_status=200, is_html=True, fetch_error=FetchError.NONE, js_render_suspected=True)
    v = lab_verdict(art, _result(IssueLabel.JS_RENDER_REQUIRED, link_found=False))
    assert v["status"] == "NEEDS_MANUAL_REVIEW" and v["score"] is None


def test_nofollow_plus_noindex_is_zero():
    art = _art(http_status=200, is_html=True, fetch_error=FetchError.NONE)
    v = lab_verdict(art, _result(IssueLabel.LINK_NOFOLLOW, IssueLabel.PAGE_NOINDEX,
                                 link_found=True, followable=False))
    assert v["status"] == "FAIL" and v["score"] == 0


def test_clean_dofollow_link_scores_high():
    art = _art(http_status=200, is_html=True, fetch_error=FetchError.NONE)
    v = lab_verdict(art, _result(link_found=True, followable=True))
    assert v["status"] == "PASS" and v["score"] >= 80
    assert v["indexable"] is True and v["followable"] is True


def test_canonical_and_placement_are_ignored():
    # A found dofollow link whose ONLY findings are canonical / thin-content /
    # placement must NOT lose points in the lab — those are excluded.
    art = _art(http_status=200, is_html=True, fetch_error=FetchError.NONE)
    v = lab_verdict(art, _result(IssueLabel.CANONICAL_CROSS_DOMAIN, link_found=True, followable=True))
    assert v["status"] == "PASS" and v["score"] == 100


def test_fully_rendered_but_absent_is_not_found_not_review():
    # We DID render the real page (browser 200) and the link isn't there →
    # genuine "not found" FAIL 0, NOT "couldn't check". (qr.ae → Quora case.)
    art = _art(http_status=200, fetch_error=FetchError.NONE, rendered=True,
               browser_http_status=200, js_render_suspected=False)
    v = lab_verdict(art, _result(IssueLabel.LINK_MISSING, link_found=False))
    assert v["status"] == "FAIL" and v["score"] == 0


def test_browser_blocked_stays_review():
    # The browser itself was blocked (403) — we could NOT read the real content
    # → review, not scored. (Medium/Reddit case.)
    art = _art(http_status=403, fetch_error=FetchError.NONE, rendered=True,
               browser_http_status=403, js_render_suspected=True)
    v = lab_verdict(art, _result(IssueLabel.SOURCE_403, link_found=False, http=403))
    assert v["status"] == "NEEDS_MANUAL_REVIEW" and v["score"] is None


def test_login_wall_redirect_is_fail():
    # The page redirected to a sign-in wall → not publicly accessible → FAIL 0.
    art = _art(http_status=200, fetch_error=FetchError.NONE, rendered=True,
               browser_http_status=200, final_url="https://medium.com/m/signin")
    v = lab_verdict(art, _result(link_found=False))
    assert v["status"] == "FAIL" and v["score"] == 0
    assert "login" in v["summary"].lower() or "sign" in v["summary"].lower()


def test_nofollow_alone_is_penalised_not_zero():
    art = _art(http_status=200, is_html=True, fetch_error=FetchError.NONE)
    v = lab_verdict(art, _result(IssueLabel.LINK_NOFOLLOW, link_found=True, followable=False))
    assert 0 < v["score"] < 80
    assert v["followable"] is False and v["indexable"] is True
