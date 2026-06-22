"""Overall status classification (PRD §8.9).

Precedence (important):
  1. A *definite* CRITICAL verdict (404/410/DNS/SSL/link-missing/cross-domain
     canonical/redirect-loop/soft-404/robots-blocked) → **FAIL**.
  2. Otherwise, an unanswerable core question (CAPTCHA/WAF/JS-inconclusive/
     conflicting directives/non-HTML) → **NEEDS_MANUAL_REVIEW** (overrides PASS/WARNING).
  3. Otherwise, a purely transient failure (timeout/429/503/504/conn-reset) → **UNKNOWN**.
  4. Otherwise band by score and remaining severities.
"""

from __future__ import annotations

from app.crawler.types import CrawlArtifact, FetchError
from app.qa.enums import IssueLabel, OverallStatus, Severity
from app.qa.types import Issue

_REVIEW_LABELS = {IssueLabel.CAPTCHA_DETECTED, IssueLabel.INDEXABILITY_UNKNOWN}
_TRANSIENT_ERRORS = (FetchError.TIMEOUT, FetchError.CONNECTION, FetchError.UNKNOWN)
_TRANSIENT_STATUSES = {429, 503, 504}
_CONFLICT_CODES = {"MR-05", "XR-05"}


def classify(artifact: CrawlArtifact, issues: list[Issue], score: int) -> OverallStatus:
    severities = {i.severity for i in issues}
    labels = {i.label for i in issues}
    det = artifact.detection

    definite_critical = any(
        i.severity is Severity.CRITICAL and i.label not in _REVIEW_LABELS for i in issues
    )

    non_html_200 = (
        artifact.http_status is not None
        and 200 <= artifact.http_status < 300
        and not artifact.is_html
    )
    # A 403 that survived the fallback-agent retry is almost always a bot/WAF
    # block rather than a dead page — the link is often still live for real
    # visitors. Route it to manual review instead of a confident FAIL/WARNING.
    hard_403 = artifact.http_status == 403

    review = (
        det.captcha
        or det.cloudflare_challenge
        or det.waf_block
        or hard_403
        or bool(labels & _REVIEW_LABELS)
        or non_html_200
        or any(i.code in _CONFLICT_CODES for i in issues)
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
    if score < 30:
        return OverallStatus.FAIL
    if Severity.HIGH in severities or Severity.MEDIUM in severities or score < 80:
        return OverallStatus.WARNING
    return OverallStatus.PASS
