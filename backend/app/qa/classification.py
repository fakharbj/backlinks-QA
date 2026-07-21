"""Overall status classification (PRD §8.9).

Precedence (important):
  1. A *definite* CRITICAL verdict (404/410/DNS/SSL/link-missing/cross-domain
     canonical/redirect-loop/soft-404/robots-blocked) → **FAIL**.
  2. Otherwise, an unanswerable core question (CAPTCHA/WAF/JS-inconclusive/
     conflicting directives/non-HTML) → **NEEDS_MANUAL_REVIEW** (overrides PASS/WARNING).
  3. Otherwise, a purely transient failure (timeout/429/503/504/conn-reset) → **UNKNOWN**.
  4. Otherwise band by score alone (fail_below / warn_below).
"""

from __future__ import annotations

from app.crawler.types import CrawlArtifact, FetchError
from app.qa.enums import IssueLabel, OverallStatus, Severity
from app.qa.types import Issue

_REVIEW_LABELS = {
    IssueLabel.CAPTCHA_DETECTED,
    IssueLabel.INDEXABILITY_UNKNOWN,
    # JS-only page we could not load content for — never a confident verdict.
    IssueLabel.JS_RENDER_REQUIRED,
}
_TRANSIENT_ERRORS = (FetchError.TIMEOUT, FetchError.CONNECTION, FetchError.UNKNOWN)
_TRANSIENT_STATUSES = {429, 503, 504}
_CONFLICT_CODES = {"MR-05", "XR-05"}
# Issues that mean "we could not actually read/verify the link" (as opposed to a
# confirmed defect) → route to NEEDS_MANUAL_REVIEW, never a confident FAIL.
# RBT-03 = source page disallowed in robots.txt (crawlers, incl. ours, are blocked).
_REVIEW_CODES = {"RBT-03"}


def classify(
    artifact: CrawlArtifact,
    issues: list[Issue],
    score: int,
    bands: dict | None = None,
) -> OverallStatus:
    fail_below, warn_below = 30, 80
    if bands:
        try:
            fail_below = int(bands.get("fail_below", 30))
            warn_below = int(bands.get("warn_below", 80))
        except (TypeError, ValueError):
            fail_below, warn_below = 30, 80
    labels = {i.label for i in issues}
    det = artifact.detection

    definite_critical = any(
        i.severity is Severity.CRITICAL
        and i.label not in _REVIEW_LABELS
        and i.code not in _REVIEW_CODES
        for i in issues
    )

    non_html_200 = (
        artifact.http_status is not None
        and 200 <= artifact.http_status < 300
        and not artifact.is_html
    )
    # BROWSER-VERIFIED (Enterprise accuracy rule): when the headless browser
    # loaded the page AND found the link, every bot-block signal on the RAW
    # fetch (403, WAF, "JS required") is a false alarm — the page is live for
    # real users. Those signals must not push a verified link into review.
    browser_verified = artifact.found_in_rendered and bool(artifact.matched_links)
    # A 403 that survived the fallback-agent retry is almost always a bot/WAF
    # block rather than a dead page — the link is often still live for real
    # visitors. Route it to manual review instead of a confident FAIL/WARNING —
    # unless the browser already verified the page.
    hard_403 = artifact.http_status == 403 and not browser_verified

    review = (
        (det.captcha and not browser_verified)
        or (det.cloudflare_challenge and not browser_verified)
        or (det.waf_block and not browser_verified)
        or hard_403
        or (bool(labels & _REVIEW_LABELS) and not browser_verified)
        or non_html_200
        or any(i.code in _CONFLICT_CODES for i in issues)
        or any(i.code in _REVIEW_CODES for i in issues)
    )
    transient = (
        artifact.fetch_error in _TRANSIENT_ERRORS
        or artifact.http_status in _TRANSIENT_STATUSES
    )

    if definite_critical:
        return OverallStatus.FAIL
    if review:
        return OverallStatus.NEEDS_MANUAL_REVIEW
    if transient:
        return OverallStatus.UNKNOWN
    if score < fail_below:
        return OverallStatus.FAIL
    # Owner rule (2026-07-22): WARNING is decided by the SCORE ALONE. A link at
    # or above ``warn_below`` (default 80) is PASS even when medium/high issues
    # deducted points on the way (e.g. rel=sponsored −10 → 90 = still PASS).
    # Severity no longer force-demotes a good score; deductions already priced
    # the issue into the number.
    if score < warn_below:
        return OverallStatus.WARNING
    return OverallStatus.PASS
