"""Recommendation engine — pure helpers (no DB)."""

from app.services.recommendation_service import build_reasons, link_type_tokens


def test_link_type_tokens_tolerant():
    assert link_type_tokens([" Business Listing ", "", None]) == ["business listing"]  # type: ignore[list-item]
    assert link_type_tokens(None) == []


def test_reasons_explain_match_and_quality():
    row = {"link_type_match": True, "matched_type": "Business Listing", "da": 45,
           "spam_score": 2, "qualified_pct": 87.5, "robots_band": "allowed"}
    reasons = build_reasons(row, ["business listing"])
    joined = " | ".join(reasons)
    assert "Business Listing" in joined
    assert "DA 45" in joined
    assert "Low spam" in joined
    assert "88% of its links qualified" in joined
    assert "Robots.txt allows crawling" in joined
    assert "Not used in this project yet" in joined


def test_reasons_honest_when_no_type_history():
    row = {"link_type_match": False, "matched_type": None, "da": None,
           "spam_score": 15, "qualified_pct": None, "robots_band": "unknown"}
    reasons = build_reasons(row, ["profile"])
    assert any("No history for this link type" in r for r in reasons)
    assert not any("DA" in r for r in reasons)
