"""Spam-neighborhood matcher (PQ-06) + dynamic scoring engine — pure unit tests.

Hermetic: no DB, no network. The spam half exercises ``crawler.parse`` internals
directly (word-boundary matcher, boilerplate-vs-content scoping, evidence shape,
allowlist suppression); the scoring half exercises ``qa.scoring.score_issues`` +
``qa.scoring_rules`` (metric-signal deltas, severity fallback, ScoreStep metadata,
band computation).
"""

from __future__ import annotations

from app.crawler.parse import (
    _build_spam_corpus,
    _compile_spam_phrase,
    parse_html,
)
from app.crawler.types import CrawlArtifact, CrawlRequest, FetchError
from app.qa.checks.page_quality import spam_neighborhood
from app.qa.enums import IssueCategory, IssueLabel, Severity
from app.qa.scoring import score_issues
from app.qa.scoring_rules import ResolvedRuleset, metric_bands
from app.qa.types import CheckContext, Issue, QAPolicy, ScoreStep


# ══════════════════════════════════════════════════════════════════════════════
# SPAM — word-boundary matcher
# ══════════════════════════════════════════════════════════════════════════════
def test_word_boundary_does_not_flag_substrings():
    """The compiled matcher is anchored on word boundaries: a spam phrase that is
    a *substring* of a legitimate word must NOT match."""
    porn = _compile_spam_phrase("porn")
    casino = _compile_spam_phrase("casino")
    escort = _compile_spam_phrase("escort")

    # "porn" inside "popcorn" — no match (it's not even a substring position that
    # aligns, but assert the whole legit word is safe).
    assert porn.search("I love popcorn at the movies") is None
    # "casino" as a substring of the legit plural "casinos" must NOT fire.
    assert casino.search("Several casinos operate in the region") is None
    # "escort" inside "escorted" — a legit past-tense verb — must NOT fire.
    assert escort.search("She was escorted to the exit") is None


def test_word_boundary_flags_real_tokens():
    """A standalone spam token (any case, with surrounding punctuation) matches."""
    casino = _compile_spam_phrase("casino")
    viagra = _compile_spam_phrase("viagra")

    assert casino.search("Best online casino bonuses") is not None
    assert casino.search("Play at the CASINO tonight") is not None  # case-insensitive
    assert casino.search("(casino) offers") is not None            # punctuation boundary
    assert viagra.search("cheap viagra online") is not None


def _make_ctx(html: str, *, scope: str = "content", min_hits: int = 1) -> CheckContext:
    """Build a minimal, network-free CheckContext with parsed spam signals."""
    page = parse_html(html, final_url="https://host.test/post")
    art = CrawlArtifact(
        request=CrawlRequest(
            source_url="https://host.test/post", target_url="https://client.test/"
        ),
        fetch_error=FetchError.NONE,
        http_status=200,
        content_type="text/html",
        final_url="https://host.test/post",
        signals=page.signals,
    )
    policy = QAPolicy(spam_enabled=True, spam_scope=scope, spam_min_hits=min_hits)
    return CheckContext(artifact=art, policy=policy)


def test_boilerplate_only_hits_do_not_produce_in_scope_medium():
    """A spam keyword that appears ONLY in nav/footer (boilerplate) must not raise
    the MEDIUM in-content PQ-06; it downgrades to LOW ("flagged for review")."""
    # NOTE: keep spam terms OUT of any anchor text — anchors scan as region
    # "anchor", which is in-scope and would flip severity to MEDIUM. Here the only
    # casino mentions live in bare nav/footer boilerplate text.
    html = """
    <html><body>
      <nav>casino directory of sites</nav>
      <article><p>An honest review of running shoes with plenty of words here.</p></article>
      <footer>casino sponsors and partners</footer>
    </body></html>
    """
    ctx = _make_ctx(html)
    issues = list(spam_neighborhood(ctx))
    assert len(issues) == 1
    iss = issues[0]
    assert iss.code == "PQ-06"
    # Boilerplate-only → LOW, not the MEDIUM main-content penalty.
    assert iss.severity is Severity.LOW
    assert iss.evidence["scope"] == "boilerplate"


def test_content_hits_produce_medium():
    """A spam keyword in the main article content raises the MEDIUM PQ-06."""
    html = """
    <html><body>
      <nav>home about contact</nav>
      <article><p>Visit our casino for the best slots and poker games tonight.</p></article>
      <footer>copyright</footer>
    </body></html>
    """
    ctx = _make_ctx(html)
    issues = list(spam_neighborhood(ctx))
    assert len(issues) == 1
    iss = issues[0]
    assert iss.code == "PQ-06"
    assert iss.severity is Severity.MEDIUM
    assert iss.evidence["scope"] == "content"


def test_evidence_carries_keyword_region_and_snippet():
    """Structured hits from the scanner carry keyword + region + snippet, and the
    PQ-06 evidence surfaces those matches."""
    html = """
    <html><body>
      <article><p>Our online casino review covers the newest slot machines.</p></article>
    </body></html>
    """
    page = parse_html(html, final_url="https://host.test/post")
    hits = page.signals.spam_keyword_hits
    assert hits, "expected at least one structured spam hit"
    hit = hits[0]
    assert hit["keyword"] == "casino"
    assert hit["region"] == "content"
    assert "casino" in hit["snippet"].lower()

    # And the check exposes the same facts in evidence.matches.
    ctx = _make_ctx(html)
    iss = list(spam_neighborhood(ctx))[0]
    assert any(m["keyword"] == "casino" and "region" in m for m in iss.evidence["matches"])


def test_allowlist_suppresses_a_phrase():
    """An allowlisted phrase is dropped from the effective corpus and can no longer
    be matched. Built directly against a stubbed settings object so the test stays
    hermetic (no reliance on process-wide config)."""
    import app.core.config as config_mod
    import app.crawler.parse as parse_mod

    class _FakeSettings:
        QA_SPAM_ALLOWLIST = ["casino"]
        QA_SPAM_EXTRA_KEYWORDS: list[str] = []

    # _build_spam_corpus reads settings via a local ``import app.core.config``.
    original = config_mod.settings
    config_mod.settings = _FakeSettings()  # type: ignore[assignment]
    try:
        corpus = _build_spam_corpus()
    finally:
        config_mod.settings = original
    _ = parse_mod  # module handle kept for clarity of where the corpus builder lives

    phrases = {entry["phrase"] for entry in corpus}
    assert "casino" not in phrases          # suppressed by the allowlist
    assert "viagra" in phrases              # other defaults survive

    # No compiled pattern in the built corpus matches the allowlisted token, so a
    # page mentioning it produces no hit for that phrase.
    for entry in corpus:
        assert entry["pattern"].search("Play casino games here.") is None or entry["phrase"] != "casino"
    assert all(entry["phrase"] != "casino" for entry in corpus)


# ══════════════════════════════════════════════════════════════════════════════
# SCORING — score_issues + scoring_rules
# ══════════════════════════════════════════════════════════════════════════════
def _issue(severity, label=IssueLabel.NONE, code="X-01", category=IssueCategory.HTTP):
    return Issue(code=code, label=label, category=category, severity=severity, message="m")


def test_metric_signal_delta_and_breakdown_metadata():
    """A configured metric signal drops the score by the configured points and the
    breakdown carries a step with parameter_key/outcome_key/source=metric_signal."""
    rs = ResolvedRuleset(rules={"source_da_band": {"low": -30}})
    score, breakdown = score_issues([], rs, signals={"source_da_band": "low"})
    assert score == 70  # 100 - 30

    steps = [
        s for s in breakdown
        if s.parameter_key == "source_da_band" and s.outcome_key == "low"
    ]
    assert len(steps) == 1
    step = steps[0]
    assert step.source == "metric_signal"
    assert step.delta == -30
    assert step.configured_points == -30


def test_unmapped_issue_uses_severity_fallback():
    """An issue whose code/label is not in the registry falls back to its severity
    deduction (unchanged legacy behavior), even under a non-empty ruleset."""
    rs = ResolvedRuleset(rules={"link_rel": {"nofollow": -5}})
    # ZZZ-99 / NONE is unmapped → HIGH severity fallback (-25).
    unmapped = _issue(Severity.HIGH, code="ZZZ-99", category=IssueCategory.PQ)
    score, breakdown = score_issues([unmapped], rs)
    assert score == 75  # 100 - 25 (severity), not touched by the link_rel override

    step = next(s for s in breakdown if s.code == "ZZZ-99")
    assert step.source == "severity"
    assert step.parameter_key is None
    assert step.configured_points is None


def test_scorestep_to_dict_includes_new_metadata_fields():
    """ScoreStep.to_dict exposes the additive explainability fields."""
    step = ScoreStep(
        code="C",
        severity=Severity.INFO,
        delta=-30,
        parameter_key="source_da_band",
        parameter_label="Source domain authority (Moz DA)",
        outcome_key="low",
        outcome_label="Low (<30)",
        source="metric_signal",
        configured_points=-30,
    )
    d = step.to_dict()
    for key in (
        "parameter_key", "parameter_label", "outcome_key",
        "outcome_label", "source", "configured_points",
    ):
        assert key in d, f"ScoreStep.to_dict missing {key}"
    assert d["parameter_key"] == "source_da_band"
    assert d["outcome_key"] == "low"
    assert d["source"] == "metric_signal"
    assert d["configured_points"] == -30


# ── Band computation ──────────────────────────────────────────────────────────
_BAND_CUTOFFS = dict(
    da_high=60, da_medium=30, as_high=50, as_medium=25,
    age_old_days=1825, age_medium_days=365,
)


def test_metric_bands_da_classification():
    """DA 65→high, 40→medium, 10→low, None→(absent, i.e. unknown)."""
    assert metric_bands(65, None, None, **_BAND_CUTOFFS)["source_da_band"] == "high"
    assert metric_bands(40, None, None, **_BAND_CUTOFFS)["source_da_band"] == "medium"
    assert metric_bands(10, None, None, **_BAND_CUTOFFS)["source_da_band"] == "low"
    # A missing metric emits NO key → treated as "unknown" downstream.
    assert "source_da_band" not in metric_bands(None, None, None, **_BAND_CUTOFFS)
