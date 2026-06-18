"""ANC-* — anchor-text checks (PRD §8.6 E)."""

from __future__ import annotations

import re
from typing import Iterable

from app.qa.checks._base import issue
from app.qa.enums import IssueCategory, IssueLabel, Severity
from app.qa.registry import check
from app.qa.types import CheckContext, Issue

CAT = IssueCategory.ANC

_MONEY_HINTS = ("buy", "cheap", "best", "price", "discount", "deal", "coupon", "for sale",
                "online", "review")


def _norm(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


@check("ANC-compare", CAT)
def anchor_comparison(ctx: CheckContext) -> Iterable[Issue]:
    link = ctx.artifact.primary_link
    if link is None:
        return
    actual = link.effective_anchor
    expected = ctx.request.expected_anchor_text

    if not actual.strip():
        if link.is_image_anchor:
            yield issue(code="ANC-06", label=IssueLabel.NONE, category=CAT, severity=Severity.LOW,
                        message="Image-only anchor; the image alt text is used as the effective anchor.",  # noqa: E501
                        evidence={"image_alt": link.image_alt})
        else:
            yield issue(code="ANC-05", label=IssueLabel.ANCHOR_CHANGED, category=CAT,
                        severity=Severity.MEDIUM, message="Anchor text is empty.",
                        recommendation="Request a meaningful anchor.")
        return

    if not expected:
        return  # nothing contractual to compare against; anchor merely captured (ANC-01)

    na, ne = _norm(actual), _norm(expected)
    if na == ne:
        return  # exact match (ANC-02 PASS) — no issue
    if ne in na or na in ne:
        yield issue(code="ANC-03", label=IssueLabel.NONE, category=CAT, severity=Severity.LOW,
                    message="Anchor partially matches the expected anchor.",
                    evidence={"actual": actual, "expected": expected})
    else:
        yield issue(code="ANC-04", label=IssueLabel.ANCHOR_CHANGED, category=CAT,
                    severity=Severity.MEDIUM,
                    message="Anchor text differs from the expected anchor.",
                    evidence={"actual": actual, "expected": expected})


@check("ANC-08", CAT)
def over_optimized_anchor(ctx: CheckContext) -> Iterable[Issue]:
    link = ctx.artifact.primary_link
    if link is None:
        return
    anchor = _norm(link.effective_anchor)
    if anchor and any(h in anchor for h in _MONEY_HINTS) and len(anchor.split()) <= 6:
        yield issue(code="ANC-08", label=IssueLabel.NONE, category=CAT, severity=Severity.LOW,
                    message="Anchor looks like an exact-match money keyword (over-optimization risk).",  # noqa: E501
                    recommendation="Diversify anchor text to reduce over-optimization risk.",
                    evidence={"anchor": link.effective_anchor})
