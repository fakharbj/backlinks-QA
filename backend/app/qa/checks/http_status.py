"""HTTP-* — HTTP status checks (PRD §8.6 B)."""

from __future__ import annotations

from typing import Iterable

from app.crawler.types import FetchError
from app.qa.checks._base import issue
from app.qa.enums import IssueCategory, IssueLabel, Severity
from app.qa.registry import check
from app.qa.types import CheckContext, Issue

CAT = IssueCategory.HTTP


def _final_status(ctx: CheckContext) -> int | None:
    return ctx.artifact.http_status


@check("HTTP-4xx-5xx", CAT)
def status_errors(ctx: CheckContext) -> Iterable[Issue]:
    art = ctx.artifact
    if art.fetch_error not in (FetchError.NONE, FetchError.TOO_LARGE):
        return  # transport never produced a status → NET-*/RDR-* own it
    status = _final_status(ctx)
    if status is None:
        return
    ev = {"http_status": status, "final_url": art.final_url}

    if status == 404:
        yield issue(code="HTTP-404", label=IssueLabel.SOURCE_404, category=CAT,
                    severity=Severity.CRITICAL,
                    message="Source page returns 404 Not Found; the backlink is lost.", evidence=ev)
    elif status == 410:
        yield issue(code="HTTP-410", label=IssueLabel.SOURCE_404, category=CAT,
                    severity=Severity.CRITICAL,
                    message="Source page returns 410 Gone; permanently removed.", evidence=ev)
    elif status == 403:
        yield issue(code="HTTP-403", label=IssueLabel.SOURCE_403, category=CAT,
                    severity=Severity.HIGH,
                    message="Source page returns 403 Forbidden (often WAF/bot rules).", evidence=ev)
    elif status == 401:
        yield issue(code="HTTP-401", label=IssueLabel.HTTP_ERROR, category=CAT,
                    severity=Severity.HIGH,
                    message="Source page returns 401 Unauthorized; login-gated and not publicly indexable.",  # noqa: E501
                    evidence=ev)
    elif status == 400:
        yield issue(code="HTTP-400", label=IssueLabel.HTTP_ERROR, category=CAT,
                    severity=Severity.HIGH,
                    message="Source page returns 400 Bad Request.", evidence=ev)
    elif status == 429:
        yield issue(code="HTTP-429", label=IssueLabel.HTTP_ERROR, category=CAT,
                    severity=Severity.MEDIUM,
                    message="We were rate-limited (429). Backing off and rechecking.", evidence=ev)
    elif status in (500, 502):
        yield issue(code=f"HTTP-{status}", label=IssueLabel.SOURCE_5XX, category=CAT,
                    severity=Severity.CRITICAL,
                    message=f"Source page returns {status} server error.", evidence=ev)
    elif status in (503, 504):
        yield issue(code=f"HTTP-{status}", label=IssueLabel.SOURCE_5XX, category=CAT,
                    severity=Severity.HIGH,
                    message=f"Source page returns {status}; often transient. Rechecking on schedule.",  # noqa: E501
                    evidence=ev)
    elif 500 <= status < 600:
        yield issue(code="HTTP-5XX", label=IssueLabel.SOURCE_5XX, category=CAT,
                    severity=Severity.HIGH,
                    message=f"Source page returns server error {status}.", evidence=ev)
    elif 400 <= status < 500:
        yield issue(code="HTTP-4XX", label=IssueLabel.HTTP_ERROR, category=CAT,
                    severity=Severity.HIGH,
                    message=f"Source page returns client error {status}.", evidence=ev)
