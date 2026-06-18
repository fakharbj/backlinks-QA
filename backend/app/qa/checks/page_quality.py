"""PQ-* — page-quality signals (PRD §8.6 M). Secondary; rarely hard-fails."""

from __future__ import annotations

from typing import Iterable

from app.crawler.types import FetchError
from app.qa.checks._base import issue
from app.qa.enums import IssueCategory, IssueLabel, Severity
from app.qa.registry import check
from app.qa.types import CheckContext, Issue

CAT = IssueCategory.PQ


def _has_page(ctx: CheckContext) -> bool:
    art = ctx.artifact
    return (
        art.fetch_error is FetchError.NONE
        and art.http_status is not None
        and 200 <= art.http_status < 300
        and art.is_html
        and not art.detection.soft_404
    )


@check("PQ-01", CAT)
def title_missing(ctx: CheckContext) -> Iterable[Issue]:
    if _has_page(ctx) and not (ctx.artifact.signals.title or "").strip():
        yield issue(code="PQ-01", label=IssueLabel.NONE, category=CAT, severity=Severity.LOW,
                    message="Page has no <title> (quality signal).")


@check("PQ-03", CAT)
def thin_content(ctx: CheckContext) -> Iterable[Issue]:
    if not _has_page(ctx):
        return
    wc = ctx.artifact.signals.word_count
    if wc < ctx.policy.thin_content_words:
        yield issue(code="PQ-03", label=IssueLabel.NONE, category=CAT, severity=Severity.LOW,
                    message=f"Thin content ({wc} words < {ctx.policy.thin_content_words}); host page carries less value.",  # noqa: E501
                    evidence={"word_count": wc})


@check("PQ-04", CAT)
def excessive_outbound(ctx: CheckContext) -> Iterable[Issue]:
    if not _has_page(ctx):
        return
    n = ctx.artifact.signals.outbound_link_count
    if n > ctx.policy.excessive_outbound_links:
        yield issue(code="PQ-04", label=IssueLabel.TOO_MANY_OUTBOUND_LINKS, category=CAT,
                    severity=Severity.MEDIUM,
                    message=f"Excessive outbound links ({n} > {ctx.policy.excessive_outbound_links}); link-farm signal.",  # noqa: E501
                    evidence={"outbound_links": n})


@check("PQ-06", CAT)
def spam_neighborhood(ctx: CheckContext) -> Iterable[Issue]:
    if not _has_page(ctx):
        return
    hits = ctx.artifact.signals.spam_keyword_hits
    if hits:
        yield issue(code="PQ-06", label=IssueLabel.NONE, category=CAT, severity=Severity.MEDIUM,
                    message="Page contains adult/gambling/pharma/spam keywords (risky neighborhood).",
                    recommendation="Review host suitability for the client's brand.",
                    evidence={"keywords": hits[:8]})
