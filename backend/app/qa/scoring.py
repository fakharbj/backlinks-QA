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
from app.qa.scoring_rules import (
    DEFAULT_RULESET,
    METRIC_PARAMS,
    ResolvedRuleset,
    outcome_label,
    param_label,
    param_outcome_for,
)
from app.qa.types import Issue, ScoreStep

# Labels that cap the ceiling without being CRITICAL (review-type uncertainty).
_LABEL_CAPS: dict[IssueLabel, int] = {
    IssueLabel.CAPTCHA_DETECTED: 25,
}


def _issue_delta(iss: Issue, ruleset: ResolvedRuleset) -> tuple[int, tuple[str, str] | None, bool]:
    """Signed score delta for one issue plus its explainability facts.

    Returns ``(delta, param_outcome, from_ruleset)`` where ``param_outcome`` is the
    ``(parameter, outcome)`` this issue maps to (or ``None`` if unmapped → severity
    fallback), and ``from_ruleset`` is True when a rule set override supplied the
    points (else today's ``-severity.deduction``)."""
    outcome = param_outcome_for(iss)
    if outcome is not None:
        override = ruleset.points(*outcome)
        if override is not None:
            return override, outcome, True
    return -iss.severity.deduction, outcome, False


def score_issues(
    issues: list[Issue],
    ruleset: ResolvedRuleset | None = None,
    signals: dict[str, str] | None = None,
) -> tuple[int, list[ScoreStep]]:
    """Deterministic score. With no ruleset (or an empty one) this is identical to
    the legacy severity model; a configured ruleset overrides per-parameter points
    and adds metric-parameter contributions from ``signals``."""
    rs = ruleset or DEFAULT_RULESET
    score = 100
    breakdown: list[ScoreStep] = [
        ScoreStep(code="START", severity=Severity.INFO, delta=0, note="Baseline score")
    ]

    # 1) Per-issue deltas (override or severity deduction).
    for iss in issues:
        delta, po, from_ruleset = _issue_delta(iss, rs)
        if delta:
            pkey = po[0] if po else None
            okey = po[1] if po else None
            breakdown.append(
                ScoreStep(
                    code=iss.code,
                    severity=iss.severity,
                    delta=delta,
                    note=iss.label.value if iss.label is not IssueLabel.NONE else iss.message[:48],
                    parameter_key=pkey,
                    parameter_label=param_label(pkey) if pkey else None,
                    outcome_key=okey,
                    outcome_label=outcome_label(pkey, okey) if pkey and okey else None,
                    source="ruleset" if from_ruleset else "severity",
                    configured_points=delta if from_ruleset else None,
                )
            )
            score += delta

    # 2) Metric-parameter contributions (DA/Semrush/age/index/duplicate). These are
    #    not QA issues; they only move the score when explicitly configured.
    if signals:
        for param, outcome in signals.items():
            if param not in METRIC_PARAMS or not outcome:
                continue
            pts = rs.points(param, outcome)
            if pts:
                score += pts
                breakdown.append(
                    ScoreStep(
                        code=f"{param}:{outcome}",
                        severity=Severity.INFO,
                        delta=pts,
                        note=f"{param_label(param)} = {outcome_label(param, outcome)}",
                        parameter_key=param,
                        parameter_label=param_label(param),
                        outcome_key=outcome,
                        outcome_label=outcome_label(param, outcome),
                        source="metric_signal",
                        configured_points=pts,
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
                source="cap",
            )
        )
        score = cap_value

    return score, breakdown
