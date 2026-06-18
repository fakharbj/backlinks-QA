"""MR-* — meta robots checks (PRD §8.6 G)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from app.crawler.types import FetchError
from app.qa.checks._base import issue
from app.qa.enums import IssueCategory, IssueLabel, Severity
from app.qa.registry import check
from app.qa.types import CheckContext, Issue

CAT = IssueCategory.MR


def _has_page(ctx: CheckContext) -> bool:
    art = ctx.artifact
    return (
        art.fetch_error is FetchError.NONE
        and art.http_status is not None
        and 200 <= art.http_status < 300
        and art.is_html
    )


@check("MR-eval", CAT)
def meta_robots(ctx: CheckContext) -> Iterable[Issue]:
    if not _has_page(ctx):
        return
    mr = ctx.artifact.meta_robots
    index_expected = ctx.policy.index_expected
    ev = {"meta_robots": mr.raw}

    if mr.none:
        yield issue(code="MR-03", label=IssueLabel.PAGE_NOINDEX, category=CAT,
                    severity=Severity.CRITICAL,
                    message="Page meta robots is 'none' (noindex,nofollow) — worst case.", evidence=ev)
        return

    if mr.noindex:
        sev = Severity.CRITICAL if index_expected else Severity.MEDIUM
        yield issue(code="MR-01", label=IssueLabel.PAGE_NOINDEX, category=CAT, severity=sev,
                    message="Page is set to noindex via meta robots.", evidence=ev)
    if mr.nofollow:
        yield issue(code="MR-02", label=IssueLabel.PAGE_NOFOLLOW, category=CAT,
                    severity=Severity.HIGH,
                    message="Page-level meta robots nofollow — no link on the page passes equity.",
                    evidence=ev)

    # Googlebot-specific directive overrides the generic one (MR-04).
    gb = mr.ua_specific.get("googlebot", "")
    if "noindex" in gb or "none" in gb:
        yield issue(code="MR-04", label=IssueLabel.PAGE_NOINDEX, category=CAT,
                    severity=Severity.CRITICAL if index_expected else Severity.MEDIUM,
                    message="Googlebot-specific meta robots sets noindex.", evidence={"googlebot": gb})
    elif "nofollow" in gb:
        yield issue(code="MR-04", label=IssueLabel.PAGE_NOFOLLOW, category=CAT,
                    severity=Severity.HIGH,
                    message="Googlebot-specific meta robots sets nofollow.", evidence={"googlebot": gb})

    if mr.conflicting:
        yield issue(code="MR-05", label=IssueLabel.NONE, category=CAT, severity=Severity.MEDIUM,
                    message="Conflicting/multiple robots directives; Google applies the most restrictive.",  # noqa: E501
                    recommendation="Ask the publisher to clean up duplicate robots tags.", evidence=ev)

    if mr.unavailable_after is not None:
        ua = mr.unavailable_after
        if ua.tzinfo is None:
            ua = ua.replace(tzinfo=timezone.utc)
        if ua < datetime.now(timezone.utc):
            yield issue(code="MR-07", label=IssueLabel.PAGE_NOINDEX, category=CAT,
                        severity=Severity.HIGH,
                        message="meta 'unavailable_after' date has passed; treat as noindex.",
                        evidence={"unavailable_after": ua.isoformat()})
