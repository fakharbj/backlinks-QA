"""Helpers shared by check modules."""

from __future__ import annotations

from typing import Any

from app.qa.enums import IssueCategory, IssueLabel, Severity
from app.qa.recommendations import recommend
from app.qa.types import Issue


def issue(
    *,
    code: str,
    label: IssueLabel,
    category: IssueCategory,
    severity: Severity,
    message: str,
    evidence: dict[str, Any] | None = None,
    recommendation: str | None = None,
) -> Issue:
    """Construct an ``Issue``, defaulting the recommendation from the label catalog."""
    return Issue(
        code=code,
        label=label,
        category=category,
        severity=severity,
        message=message,
        recommendation=recommendation if recommendation is not None else recommend(label),
        evidence=evidence or {},
    )
