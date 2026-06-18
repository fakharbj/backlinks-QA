"""RBT-* — robots.txt checks (PRD §8.6 J)."""

from __future__ import annotations

from typing import Iterable

from app.crawler.types import FetchError
from app.qa.checks._base import issue
from app.qa.enums import IssueCategory, IssueLabel, Severity
from app.qa.registry import check
from app.qa.types import CheckContext, Issue

CAT = IssueCategory.RBT


@check("RBT-03", CAT)
def source_disallowed(ctx: CheckContext) -> Iterable[Issue]:
    art = ctx.artifact
    blocked = art.robots.source_allowed is False or art.fetch_error is FetchError.BLOCKED_ROBOTS
    if blocked:
        yield issue(code="RBT-03", label=IssueLabel.ROBOTS_BLOCKED, category=CAT,
                    severity=Severity.CRITICAL,
                    message="Source page is disallowed in robots.txt for Googlebot; crawlers can't read the link.",  # noqa: E501
                    evidence={"matched_ua": art.robots.matched_user_agent})


@check("RBT-04", CAT)
def target_disallowed(ctx: CheckContext) -> Iterable[Issue]:
    if ctx.artifact.robots.target_allowed is False:
        yield issue(code="RBT-04", label=IssueLabel.ROBOTS_BLOCKED, category=CAT,
                    severity=Severity.MEDIUM,
                    message="Target URL is disallowed in robots.txt (informational for our own site).")


@check("RBT-02", CAT)
def robots_parse_issue(ctx: CheckContext) -> Iterable[Issue]:
    if ctx.artifact.robots.parse_error:
        yield issue(code="RBT-02", label=IssueLabel.NONE, category=CAT, severity=Severity.LOW,
                    message="robots.txt could not be parsed; treated as allow-all (noted for uncertainty).")  # noqa: E501


@check("RBT-08", CAT)
def crawl_delay_declared(ctx: CheckContext) -> Iterable[Issue]:
    delay = ctx.artifact.robots.crawl_delay
    if delay:
        yield issue(code="RBT-08", label=IssueLabel.NONE, category=CAT, severity=Severity.INFO,
                    message=f"robots.txt declares crawl-delay of {delay}s (respected during crawl).",
                    evidence={"crawl_delay": delay})
