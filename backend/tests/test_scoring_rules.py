"""Dynamic scoring engine — backward-compat (golden) + override behaviour.

The critical guarantee: an empty rule set (the seeded global v1) reproduces the
legacy severity model EXACTLY, so deploying the engine changes no scores. Beyond
that, explicit per-parameter overrides, configurable bands, and metric signals
move the score as configured.
"""

from __future__ import annotations

from app.crawler.types import CrawlArtifact, CrawlRequest
from app.qa.classification import classify
from app.qa.enums import IssueCategory, IssueLabel, OverallStatus, Severity
from app.qa.scoring import score_issues
from app.qa.scoring_rules import ResolvedRuleset, param_outcome_for
from app.qa.types import Issue


def _issue(code, label, category, severity, evidence=None):
    return Issue(
        code=code, label=label, category=category, severity=severity, message="x",
        evidence=evidence or {},
    )


_LINK_MISSING = _issue("LNK-02", IssueLabel.LINK_MISSING, IssueCategory.LNK, Severity.CRITICAL)
_NOFOLLOW = _issue("REL-02", IssueLabel.LINK_NOFOLLOW, IssueCategory.REL, Severity.HIGH)
_ANCHOR = _issue("ANC-04", IssueLabel.ANCHOR_CHANGED, IssueCategory.ANC, Severity.MEDIUM)


# ── Golden: empty rule set == legacy severity model ──────────────────────────
def test_empty_ruleset_reproduces_legacy_scores():
    cases = [
        [],
        [_NOFOLLOW],
        [_ANCHOR],
        [_NOFOLLOW, _ANCHOR],
        [_LINK_MISSING],  # CRITICAL → capped at 25
    ]
    for issues in cases:
        legacy, _ = score_issues(issues)  # ruleset=None → DEFAULT
        explicit, _ = score_issues(issues, ResolvedRuleset())  # empty overrides
        assert legacy == explicit
    # Known absolute values from the legacy model.
    assert score_issues([])[0] == 100
    assert score_issues([_NOFOLLOW])[0] == 75
    assert score_issues([_ANCHOR])[0] == 90
    assert score_issues([_LINK_MISSING])[0] == 25  # 100-60=40, CRITICAL caps to 25


# ── Per-parameter overrides ──────────────────────────────────────────────────
def test_override_changes_only_the_targeted_parameter():
    rs = ResolvedRuleset(rules={"link_rel": {"nofollow": -5}})
    assert score_issues([_NOFOLLOW], rs)[0] == 95  # -5 instead of -25
    # An unrelated issue is untouched by the override.
    assert score_issues([_ANCHOR], rs)[0] == 90


def test_override_can_make_a_parameter_harsher():
    rs = ResolvedRuleset(rules={"anchor_match": {"changed": -40}})
    assert score_issues([_ANCHOR], rs)[0] == 60


# ── Metric signals (DA / Semrush / age / index / duplicate) ──────────────────
def test_metric_signal_only_applies_when_configured():
    # Not configured → no contribution even though the signal is present.
    assert score_issues([], ResolvedRuleset(), signals={"source_da_band": "low"})[0] == 100
    # Configured → applied.
    rs = ResolvedRuleset(rules={"source_da_band": {"low": -30}})
    assert score_issues([], rs, signals={"source_da_band": "low"})[0] == 70


# ── Configurable bands ───────────────────────────────────────────────────────
def test_bands_shift_classification_thresholds():
    art = CrawlArtifact(
        request=CrawlRequest(source_url="https://p.test/x", target_url="https://t.test/"),
        http_status=200, content_type="text/html",
    )
    assert classify(art, [], 85) == OverallStatus.PASS
    assert classify(art, [], 85, bands={"fail_below": 30, "warn_below": 90}) == OverallStatus.WARNING
    assert classify(art, [], 40, bands={"fail_below": 50, "warn_below": 90}) == OverallStatus.FAIL


# ── Registry mapping ─────────────────────────────────────────────────────────
def test_param_outcome_mapping_and_fallback():
    assert param_outcome_for(_LINK_MISSING) == ("link_presence", "missing")
    assert param_outcome_for(_NOFOLLOW) == ("link_rel", "nofollow")
    # Placement region comes from evidence.
    lnk17 = _issue("LNK-17", IssueLabel.NONE, IssueCategory.LNK, Severity.LOW, {"region": "footer"})
    assert param_outcome_for(lnk17) == ("link_placement", "footer")
    # Unknown code/label → None → severity fallback (never raises).
    unknown = _issue("ZZZ-99", IssueLabel.NONE, IssueCategory.PQ, Severity.LOW)
    assert param_outcome_for(unknown) is None
