"""CAN-* — canonical-tag checks (PRD §8.6 I)."""

from __future__ import annotations

from typing import Iterable
from urllib.parse import urlsplit

from app.crawler.normalize import normalize_url, registrable_domain
from app.crawler.types import FetchError
from app.qa.checks._base import issue
from app.qa.enums import IssueCategory, IssueLabel, Severity
from app.qa.registry import check
from app.qa.types import CheckContext, Issue

CAT = IssueCategory.CAN


def _has_page(ctx: CheckContext) -> bool:
    art = ctx.artifact
    return (
        art.fetch_error is FetchError.NONE
        and art.http_status is not None
        and 200 <= art.http_status < 300
        and art.is_html
    )


@check("CAN-eval", CAT)
def canonical(ctx: CheckContext) -> Iterable[Issue]:
    if not _has_page(ctx):
        return
    art = ctx.artifact

    if art.canonical_count == 0 or not art.canonical_url:
        yield issue(code="CAN-02", label=IssueLabel.NONE, category=CAT, severity=Severity.LOW,
                    message="No rel=canonical tag present; Google will infer one.")
        return

    if art.canonical_count > 1:
        yield issue(code="CAN-09", label=IssueLabel.CANONICAL_MISMATCH, category=CAT,
                    severity=Severity.MEDIUM,
                    message="Multiple canonical tags present; Google may ignore them.",
                    evidence={"count": art.canonical_count})

    if not art.canonical_resolved:
        yield issue(code="CAN-10", label=IssueLabel.CANONICAL_MISMATCH, category=CAT,
                    severity=Severity.MEDIUM,
                    message="Canonical URL is invalid or could not be resolved.",
                    evidence={"canonical": art.canonical_url})
        return

    final_norm = normalize_url(art.final_url or "").normalized
    if art.canonical_resolved == final_norm:
        return  # self-referential (CAN-01 PASS)

    src_dom = registrable_domain(urlsplit(final_norm).hostname or "")
    can_dom = registrable_domain(urlsplit(art.canonical_resolved).hostname or "")

    if can_dom and src_dom and can_dom != src_dom:
        yield issue(code="CAN-04", label=IssueLabel.CANONICAL_CROSS_DOMAIN, category=CAT,
                    severity=Severity.CRITICAL,
                    message="Canonical points to another domain; equity leaves this domain entirely.",  # noqa: E501
                    evidence={"canonical": art.canonical_resolved, "source_domain": src_dom})
    else:
        yield issue(code="CAN-03", label=IssueLabel.CANONICAL_MISMATCH, category=CAT,
                    severity=Severity.HIGH,
                    message="Canonical points to a different URL on the same domain; ensure that page also hosts the link.",  # noqa: E501
                    evidence={"canonical": art.canonical_resolved, "crawled": final_norm})

    # Optional secondary-fetch signals (only if the worker resolved canonical status).
    if art.canonical_status is not None and art.canonical_status >= 400:
        yield issue(code="CAN-05", label=IssueLabel.CANONICAL_MISMATCH, category=CAT,
                    severity=Severity.HIGH,
                    message=f"Canonical target returns {art.canonical_status}.",
                    evidence={"canonical_status": art.canonical_status})
