"""BOT-* — bot-protection / soft-404 / parked detection (PRD §8.6 N).

We never bypass protection; we surface it so the classifier routes the link to
NEEDS_MANUAL_REVIEW (CAPTCHA/WAF) or FAIL (soft-404/parked).
"""

from __future__ import annotations

from typing import Iterable

from app.qa.checks._base import issue
from app.qa.enums import IssueCategory, IssueLabel, Severity
from app.qa.registry import check
from app.qa.types import CheckContext, Issue

CAT = IssueCategory.BOT


def _browser_verified(ctx: CheckContext) -> bool:
    """Raw fetch was blocked but the headless browser loaded the page AND found
    the link — the block only applies to robots; suppress the review-routing
    bot issues (classification also honors this)."""
    art = ctx.artifact
    return bool(art.found_in_rendered and art.matched_links)


@check("BOT-01", CAT)
def captcha(ctx: CheckContext) -> Iterable[Issue]:
    if _browser_verified(ctx):
        return
    det = ctx.artifact.detection
    if det.captcha:
        yield issue(code="BOT-01", label=IssueLabel.CAPTCHA_DETECTED, category=CAT,
                    severity=Severity.INFO,  # caps score via label-cap; status → REVIEW
                    message="CAPTCHA detected; we do not solve CAPTCHAs — manual review required.",
                    evidence={"signature": det.signature})
    elif det.cloudflare_challenge:
        yield issue(code="BOT-02", label=IssueLabel.CAPTCHA_DETECTED, category=CAT,
                    severity=Severity.INFO,
                    message="Cloudflare/JS browser challenge detected; manual review required.",
                    evidence={"signature": det.signature})


@check("BOT-03", CAT)
def waf_block(ctx: CheckContext) -> Iterable[Issue]:
    if _browser_verified(ctx):
        return
    det = ctx.artifact.detection
    if det.waf_block and not det.captcha and not det.cloudflare_challenge:
        yield issue(code="BOT-03", label=IssueLabel.SOURCE_403, category=CAT, severity=Severity.HIGH,
                    message="WAF/firewall block detected; the page may still be live for real users. Verify manually.",  # noqa: E501
                    evidence={"signature": det.signature})


@check("BOT-04", CAT)
def soft_404(ctx: CheckContext) -> Iterable[Issue]:
    det = ctx.artifact.detection
    if det.parked:
        yield issue(code="BOT-06", label=IssueLabel.SOFT_404, category=CAT, severity=Severity.CRITICAL,
                    message="Parked/expired-domain page detected; the backlink is effectively lost.",
                    evidence={"signature": det.signature})
    elif det.soft_404:
        yield issue(code="BOT-04", label=IssueLabel.SOFT_404, category=CAT, severity=Severity.CRITICAL,
                    message="Soft-404 detected (200 OK but 'not found'/placeholder content).",
                    evidence={"signature": det.signature})
    elif det.empty_page:
        yield issue(code="BOT-05", label=IssueLabel.SOFT_404, category=CAT, severity=Severity.HIGH,
                    message="Empty/blank page (no content or link).",
                    evidence={"signature": det.signature})
