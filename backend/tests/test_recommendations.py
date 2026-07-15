"""Recommendation engine — pure helpers (no DB)."""

from app.services.recommendation_service import (
    build_reasons,
    link_type_tokens,
    normalize_link_type,
)


def test_link_type_tokens_tolerant():
    assert link_type_tokens([" Business Listing ", "", None]) == ["business listing"]  # type: ignore[list-item]
    assert link_type_tokens(None) == []


def test_normalize_link_type_variants_collapse():
    # Every real-world spelling of the same thing must compare equal — this is
    # the blogspot.com case (one domain, a dozen "Web 2.0" spellings).
    variants = ["Web2.0", "WEB 2.0", "Web 2.0", "Web 2.o", "web-2.0", "web_2 . 0"]
    assert {normalize_link_type(v) for v in variants} == {"web20"}
    assert normalize_link_type("Book Marking") == normalize_link_type("Bookmarking")
    assert normalize_link_type("GBP - Web 2.0") == normalize_link_type("GBP Web 2.o")
    # Distinct things stay distinct.
    assert normalize_link_type("Article") != normalize_link_type("Web 2.0")
    # The digit-"o" fix never touches ordinary words.
    assert normalize_link_type("Social Bookmarking") == "socialbookmarking"
    assert normalize_link_type(None) == ""


def test_normalize_related_containment_shapes():
    # The SQL related-match (tier 1) is containment on these normalized forms;
    # assert the shapes it depends on hold.
    assert normalize_link_type("Web 2.0") in normalize_link_type("GBP Web 2.o")
    assert normalize_link_type("Article") in normalize_link_type("Article Submission")
    assert normalize_link_type("Blog post") == "blogpost"


def test_reasons_explain_exact_match_with_counts():
    row = {"link_type_match": True, "match": "exact", "matched_type": "WEB 2.0",
           "matched_links": 1990, "backlink_count": 2000, "project_count": 12,
           "da": 92, "spam_score": 2, "qualified_pct": 87.5, "robots_band": "allowed"}
    reasons = build_reasons(row, ["web 2.0"])
    joined = " | ".join(reasons)
    assert "Used 1990× for WEB 2.0 links elsewhere" in joined
    assert "2000 links built across 12 projects" in joined
    assert "DA 92" in joined
    assert "Low spam" in joined
    assert "88% of its links qualified" in joined
    assert "Robots.txt allows crawling" in joined
    assert "Not used in this project yet" in joined


def test_reasons_explain_related_match():
    row = {"link_type_match": True, "match": "related", "matched_type": "GBP Web 2.0",
           "matched_links": 31, "da": 45, "spam_score": 20, "qualified_pct": None,
           "robots_band": "unknown"}
    reasons = build_reasons(row, ["web 2.0"])
    assert any("related type" in r and "GBP Web 2.0" in r for r in reasons)


def test_reasons_honest_when_no_type_history():
    row = {"link_type_match": False, "match": None, "matched_type": None, "da": None,
           "spam_score": 15, "qualified_pct": None, "robots_band": "unknown"}
    reasons = build_reasons(row, ["profile"])
    assert any("No history for this link type" in r for r in reasons)
    assert not any("DA" in r for r in reasons)
