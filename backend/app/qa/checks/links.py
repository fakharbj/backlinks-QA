"""LNK-* — link-presence & placement checks (PRD §8.6 D)."""

from __future__ import annotations

from typing import Iterable
from urllib.parse import urlsplit

from app.crawler.normalize import normalize_url, registrable_domain
from app.crawler.types import FetchError, ParsedLink
from app.qa.checks._base import issue
from app.qa.enums import IssueCategory, IssueLabel, Severity
from app.qa.registry import check
from app.qa.types import CheckContext, Issue

CAT = IssueCategory.LNK


def _page_was_readable(ctx: CheckContext) -> bool:
    """Only assert presence/absence when we actually read a real HTML page."""
    art = ctx.artifact
    if art.fetch_error is not FetchError.NONE:
        return False
    if art.http_status is None or not (200 <= art.http_status < 300):
        return False
    if not art.is_html:
        return False
    det = art.detection
    return not (det.captcha or det.cloudflare_challenge or det.waf_block or det.soft_404
                or det.empty_page or det.parked)


def _expected_domain(ctx: CheckContext) -> str:
    expected = ctx.request.expected_target_url or ctx.request.target_url
    norm = normalize_url(expected)
    return norm.registrable_domain if norm.valid else ""


@check("LNK-01", CAT)
def link_presence(ctx: CheckContext) -> Iterable[Issue]:
    art = ctx.artifact
    if not _page_was_readable(ctx):
        return
    if art.link_found:
        yield issue(code="LNK-01", label=IssueLabel.LINK_FOUND, category=CAT,
                    severity=Severity.INFO,
                    message="Backlink found on the source page.",
                    evidence={"matched": art.primary_link.normalized_url if art.primary_link else None,  # noqa: E501
                              "count": len(art.matched_links)})
        return

    # A page with ZERO outbound links is a JavaScript shell (Notion, SPAs)
    # whose content we could not load (render blocked/bot-walled) — that is
    # "couldn't check", NEVER a confident "link missing".
    if not art.all_links:
        yield issue(code="LNK-09", label=IssueLabel.JS_RENDER_REQUIRED, category=CAT,
                    severity=Severity.INFO,
                    message=("The page builds its content with JavaScript and our checker "
                             "couldn't load it. Open the page yourself to confirm — the link "
                             "could not be verified automatically."),
                    evidence={"outbound_links": 0, "rendered": art.rendered})
        return

    # No exact match → wrong-target (same domain) or genuinely missing.
    exp_dom = _expected_domain(ctx)
    same_domain_link = next(
        (
            link for link in art.all_links
            if registrable_domain(urlsplit(link.normalized_url).hostname or "") == exp_dom
        ),
        None,
    )
    if same_domain_link is not None:
        yield issue(code="LNK-06", label=IssueLabel.WRONG_TARGET, category=CAT,
                    severity=Severity.HIGH,
                    message="A link to the target domain exists, but not to the agreed target URL.",  # noqa: E501
                    evidence={"found_url": same_domain_link.normalized_url,
                              "expected": ctx.request.expected_target_url or ctx.request.target_url})  # noqa: E501
    elif art.signals.doc_viewer:
        # The page is a PDF/document VIEWER — the link usually lives inside the
        # embedded document (annotation layers built lazily by JS), which we may
        # not have fully read. "Couldn't verify" → review, NEVER a confident
        # LINK_MISSING (that was a reported false FAIL).
        yield issue(code="LNK-09", label=IssueLabel.JS_RENDER_REQUIRED, category=CAT,
                    severity=Severity.INFO,
                    message=("The page embeds a PDF/document and the link likely lives inside "
                             "it. Our checker couldn't fully read the document — open the page "
                             "and verify the link manually."),
                    evidence={"doc_viewer": art.signals.doc_viewer_signature,
                              "outbound_links": len(art.all_links),
                              "target": ctx.request.target_url})
    else:
        yield issue(code="LNK-02", label=IssueLabel.LINK_MISSING, category=CAT,
                    severity=Severity.CRITICAL,
                    message="Backlink is missing from the source page.",
                    evidence={"target": ctx.request.target_url,
                              "outbound_links": len(art.all_links)})


@check("LNK-18", CAT)
def relaxed_match_disclosure(ctx: CheckContext) -> Iterable[Issue]:
    """Transparency for GBP/citation RELAXED matches: the link counts as present,
    but reports must say HOW it matched — never pretend the exact agreed URL was
    found. INFO severity: no score damage, no status change."""
    art = ctx.artifact
    if not art.relaxed_reason or art.primary_link is None:
        return
    how = {
        "gbp_map": "a Google Maps / Business Profile listing link",
        "owned_directory": "a listing on one of our own directory sites",
    }.get(art.relaxed_reason, art.relaxed_reason)
    yield issue(code="LNK-18", label=IssueLabel.NONE, category=CAT, severity=Severity.INFO,
                message=f"Accepted via relaxed GBP/citation matching: the page carries {how} instead of the main-domain link.",  # noqa: E501
                evidence={"matched_url": art.primary_link.normalized_url,
                          "reason": art.relaxed_reason,
                          "expected": ctx.request.expected_target_url or ctx.request.target_url})


@check("LNK-08", CAT)
def multiple_links(ctx: CheckContext) -> Iterable[Issue]:
    if len(ctx.artifact.matched_links) > 1:
        yield issue(code="LNK-08", label=IssueLabel.NONE, category=CAT, severity=Severity.INFO,
                    message=f"{len(ctx.artifact.matched_links)} links point to the target.",
                    evidence={"count": len(ctx.artifact.matched_links)})


@check("LNK-09", CAT)
def js_only_link(ctx: CheckContext) -> Iterable[Issue]:
    art = ctx.artifact
    if art.found_in_rendered and not art.found_in_raw:
        yield issue(code="LNK-09", label=IssueLabel.JS_RENDER_REQUIRED, category=CAT,
                    severity=Severity.MEDIUM,
                    message="Link is present only after JavaScript rendering; search engines may under-credit it.",  # noqa: E501
                    evidence={"crawl_mode": "rendered"})


@check("LNK-hidden", CAT)
def hidden_link(ctx: CheckContext) -> Iterable[Issue]:
    link = ctx.artifact.primary_link
    if link is None:
        return
    if link.in_comment:
        yield issue(code="LNK-11", label=IssueLabel.LINK_HIDDEN, category=CAT,
                    severity=Severity.HIGH, message="Link is buried inside an HTML comment.",
                    evidence={"region": link.region})
    elif link.in_iframe:
        yield issue(code="LNK-14", label=IssueLabel.LINK_HIDDEN, category=CAT,
                    severity=Severity.HIGH, message="Link is inside an iframe and generally won't credit the parent page.",  # noqa: E501
                    evidence={"region": link.region})
    elif link.css_hidden:
        yield issue(code="LNK-12", label=IssueLabel.LINK_HIDDEN, category=CAT,
                    severity=Severity.HIGH, message="Link is hidden via CSS (display/visibility/size/off-screen).",  # noqa: E501
                    evidence={"region": link.region})
    elif link.in_noscript:
        yield issue(code="LNK-13", label=IssueLabel.LINK_HIDDEN, category=CAT,
                    severity=Severity.MEDIUM, message="Link is inside a <noscript> block.",
                    evidence={"region": link.region})


@check("LNK-block", CAT)
def placement_block(ctx: CheckContext) -> Iterable[Issue]:
    link = ctx.artifact.primary_link
    if link is None:
        return
    if link.sponsored_block:
        yield issue(code="LNK-15", label=IssueLabel.LINK_SPONSORED, category=CAT,
                    severity=Severity.MEDIUM,
                    message="Link sits inside a sponsored/ad block; confirm it's editorial if that was agreed.",  # noqa: E501
                    evidence={"region": link.region})
    if link.ugc_block:
        yield issue(code="LNK-16", label=IssueLabel.LINK_UGC, category=CAT,
                    severity=Severity.MEDIUM,
                    message="Link sits inside a UGC/comment section; confirm the placement type.",
                    evidence={"region": link.region})


@check("LNK-17", CAT)
def placement_region(ctx: CheckContext) -> Iterable[Issue]:
    link = ctx.artifact.primary_link
    if link is None:
        return
    if link.region in ("footer", "sidebar", "header", "nav"):
        yield issue(code="LNK-17", label=IssueLabel.NONE, category=CAT, severity=Severity.LOW,
                    message=f"Link placed in the {link.region}; site-wide/boilerplate links carry less editorial value than in-content links.",  # noqa: E501
                    recommendation="Prefer an in-content, in-body placement.",
                    evidence={"region": link.region})


@check("LNK-04", CAT)
def normalized_only_match(ctx: CheckContext) -> Iterable[Issue]:
    link = ctx.artifact.primary_link
    if link is None:
        return
    if ctx.request.domain_match():
        # Whole-domain scope: a different page on the target domain is a valid
        # match, not a minor normalization difference — don't flag it.
        return
    expected = ctx.request.expected_target_url or ctx.request.target_url
    if link.resolved_url and expected and link.resolved_url.rstrip("/") != expected.rstrip("/"):
        # Matched only after normalization (trailing slash / scheme / tracking params).
        yield issue(code="LNK-04", label=IssueLabel.NONE, category=CAT, severity=Severity.LOW,
                    message="Target matched only after normalization (minor differences in slash/scheme/params).",  # noqa: E501
                    recommendation="Prefer linking to the exact final target URL.",
                    evidence={"found": link.resolved_url, "expected": expected})
