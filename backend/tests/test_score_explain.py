"""Score-breakdown explainability (enrich-on-read) — pure, no DB/network."""

from app.qa.enums import IssueCategory, IssueLabel, Severity
from app.qa.recommendations import enrich_breakdown
from app.qa.types import Issue


def _issue(code: str, label: IssueLabel, rec: str | None = None) -> Issue:
    return Issue(
        code=code, category=IssueCategory.LNK, severity=Severity.CRITICAL,
        message="x", label=label, recommendation=rec,
    )


def test_enrich_orders_biggest_deduction_first_and_attaches_recommendation():
    steps = [
        {"code": "START", "severity": "INFO", "delta": 0, "note": "Baseline score"},
        {"code": "LNK-02", "severity": "MEDIUM", "delta": -10, "note": "LINK_NOFOLLOW"},
        {"code": "LNK-01", "severity": "CRITICAL", "delta": -60, "note": "LINK_MISSING"},
        {"code": "da_band:high", "severity": "INFO", "delta": 5, "source": "metric_signal",
         "parameter_key": "da_band", "outcome_label": "High"},
        {"code": "LNK-01", "severity": "CRITICAL", "delta": -15, "cap_applied": 25,
         "note": "Capped at 25 by LNK-01", "source": "cap"},
    ]
    issues = [_issue("LNK-01", IssueLabel.LINK_MISSING), _issue("LNK-02", IssueLabel.LINK_NOFOLLOW)]
    out = enrich_breakdown(steps, issues)

    # Order: baseline → -60 → -10 → +5 gain → cap last.
    assert [s["delta"] for s in out] == [0, -60, -10, 5, -15]
    # Impact = points lost (>= 0).
    assert out[1]["impact"] == 60 and out[3]["impact"] == 0
    # Deductions carry "how to improve" text from the label registry.
    assert "restore" in (out[1]["recommendation"] or "").lower()
    assert out[2]["recommendation"]
    # Gains never get a recommendation; the cap step explains the ceiling.
    assert "recommendation" not in out[3]
    assert "lift the score ceiling" in (out[4]["recommendation"] or "")
    # The stored dicts were not mutated in place.
    assert "impact" not in steps[1]


def test_enrich_tolerates_old_rows_and_no_issues():
    # Historical rows lack the newer keys entirely — must not raise.
    out = enrich_breakdown([{"code": "SRC-404", "delta": -40, "note": "SOURCE_404"}], None)
    assert out[0]["impact"] == 40
    # Label fallback via the note string still finds guidance.
    assert "restore" in (out[0]["recommendation"] or "").lower()
    assert enrich_breakdown([], []) == []
