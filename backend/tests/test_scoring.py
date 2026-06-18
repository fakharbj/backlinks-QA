"""Deterministic scoring tests (PRD §8.8)."""

from app.qa.enums import IssueCategory, IssueLabel, Severity
from app.qa.scoring import score_issues
from app.qa.types import Issue


def _issue(severity, label=IssueLabel.NONE, code="X-01"):
    return Issue(
        code=code, label=label, category=IssueCategory.HTTP, severity=severity, message="m"
    )


def test_empty_is_100():
    score, breakdown = score_issues([])
    assert score == 100
    assert breakdown[0].code == "START"


def test_severity_deductions():
    assert score_issues([_issue(Severity.HIGH)])[0] == 75
    assert score_issues([_issue(Severity.MEDIUM)])[0] == 90
    assert score_issues([_issue(Severity.LOW)])[0] == 97
    assert score_issues([_issue(Severity.INFO)])[0] == 100


def test_critical_caps_at_25():
    score, breakdown = score_issues([_issue(Severity.CRITICAL)])
    assert score == 25
    assert any(step.cap_applied == 25 for step in breakdown)


def test_multiple_criticals_floor_at_zero_then_cap():
    score, _ = score_issues([_issue(Severity.CRITICAL), _issue(Severity.HIGH, code="Y")])
    # 100 - 60 - 25 = 15, clamped >=0, cap(25) does not raise it.
    assert score == 15


def test_captcha_label_caps_even_when_info():
    score, _ = score_issues([_issue(Severity.INFO, IssueLabel.CAPTCHA_DETECTED, code="BOT-01")])
    assert score == 25


def test_score_never_negative():
    issues = [_issue(Severity.CRITICAL, code=f"C{i}") for i in range(5)]
    score, _ = score_issues(issues)
    assert 0 <= score <= 100
