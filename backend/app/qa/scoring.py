"""Deterministic, explainable scoring (PRD §8.8).

    score = 100
    score -= Σ deduction(issue)          # weighted by severity
    score  = clamp(score, 0, 100)
    for issue: score = min(score, cap(issue))   # CRITICAL/review issues cap the ceiling

Every mutation is recorded as a ``ScoreStep`` so the detail page can render
"started at 100, −60 SOURCE_404 → capped at 25".
"""

from __future__ import annotations

from app.qa.enums import IssueLabel, Severity
from app.qa.types import Issue, ScoreStep

# Labels that cap the ceiling without being CRITICAL (review-type uncertainty).
_LABEL_CAPS: dict[IssueLabel, int] = {
    IssueLabel.CAPTCHA_DETECTED: 25,
}


def score_issues(issues: list[Issue]) -> tuple[int, list[ScoreStep]]:
    score = 100
    breakdown: list[ScoreStep] = [
        ScoreStep(code="START", severity=Severity.INFO, delta=0, note="Baseline score")
    ]

    # 1) Severity deductions.
    for iss in issues:
        deduction = iss.severity.deduction
        if deduction:
            score -= deduction
            breakdown.append(
                ScoreStep(
                    code=iss.code,
                    severity=iss.severity,
                    delta=-deduction,
                    note=iss.label.value if iss.label is not IssueLabel.NONE else iss.message[:48],
                )
            )

    score = max(0, min(100, score))

    # 2) Hard caps — the lowest applicable cap wins.
    cap_value: int | None = None
    cap_code: str | None = None
    for iss in issues:
        candidate = iss.severity.cap
        label_cap = _LABEL_CAPS.get(iss.label)
        for c in (candidate, label_cap):
            if c is not None and (cap_value is None or c < cap_value):
                cap_value, cap_code = c, iss.code

    if cap_value is not None and score > cap_value:
        breakdown.append(
            ScoreStep(
                code=cap_code or "CAP",
                severity=Severity.CRITICAL,
                delta=cap_value - score,
                cap_applied=cap_value,
                note=f"Capped at {cap_value} by {cap_code}",
            )
        )
        score = cap_value

    return score, breakdown
