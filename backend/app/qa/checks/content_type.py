"""CT-* — content-type checks (PRD §8.6 L)."""

from __future__ import annotations

from typing import Iterable

from app.crawler.types import FetchError
from app.qa.checks._base import issue
from app.qa.enums import IssueCategory, IssueLabel, Severity
from app.qa.registry import check
from app.qa.types import CheckContext, Issue

CAT = IssueCategory.CT


@check("CT-eval", CAT)
def content_type(ctx: CheckContext) -> Iterable[Issue]:
    art = ctx.artifact
    if art.fetch_error is not FetchError.NONE or art.http_status is None:
        return
    if not (200 <= art.http_status < 300):
        return
    if art.is_html:
        return  # CT-01 standard — full checks already ran

    ct = (art.content_type or "unknown").split(";")[0].strip().lower()
    ev = {"content_type": ct}
    if "pdf" in ct:
        yield issue(code="CT-02", label=IssueLabel.NONE, category=CAT, severity=Severity.MEDIUM,
                    message="Source is a PDF; HTML link checks are not applicable (special backlink type).",  # noqa: E501
                    recommendation="Mark as a PDF backlink; future support will scan PDF text for the target URL.",  # noqa: E501
                    evidence=ev)
    elif any(t in ct for t in ("image/", "text/plain", "javascript", "json", "xml")):
        yield issue(code="CT-03", label=IssueLabel.NONE, category=CAT, severity=Severity.MEDIUM,
                    message=f"Non-HTML host content-type ({ct}); link-in-HTML checks not applicable.",
                    recommendation="Flag for manual review; the placement is not a standard web page.",
                    evidence=ev)
    else:
        yield issue(code="CT-05", label=IssueLabel.NONE, category=CAT, severity=Severity.MEDIUM,
                    message=f"Unsupported/unknown content-type ({ct}); flagged for manual review.",
                    evidence=ev)
