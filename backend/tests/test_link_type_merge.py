"""Link-type standardization — the pure grouping/normalization logic (no DB).

The merge/rename executors are exercised live (they need pg + Google); the part
that decides WHAT to merge — the normalizer + typo dictionary + GBP boundary —
is pure and covered here against the real production variants."""

from app.services.link_type_merge_service import _is_gbpish, _norm_key, _title_case


def test_norm_key_folds_production_business_listing_variants():
    variants = [
        "Business Listing", "Businesss Listing", "Busniees Listing",
        "Busniess Listing", "business listing", "Business Listings",
        "Business Lisitng", "Biz Listing",
    ]
    keys = {_norm_key(v) for v in variants}
    assert keys == {"businesslisting"}


def test_norm_key_folds_web20_spellings():
    variants = ["Web 2.0", "WEB2.0", "web 2.0", "WEB 2.0", "web2.0", "web-2.0", "Web2.0", "Web 2.o"]
    assert {_norm_key(v) for v in variants} == {"web20"}


def test_norm_key_folds_bookmarking_and_typos():
    assert _norm_key("Book Marking") == _norm_key("Bookmarking")
    assert _norm_key("Social Bookamrking") == _norm_key("Social Bookmarking")
    assert _norm_key("Socail Media") == _norm_key("Social Media")
    assert _norm_key("Classified Ads posting") == _norm_key("Classified Ad Posting")


def test_norm_key_keeps_distinct_types_apart():
    # Different real types must never share a key.
    assert _norm_key("Guest Post") != _norm_key("Blog Post")
    assert _norm_key("Article Submission") != _norm_key("Image Submission")
    assert _norm_key("Profile") != _norm_key("Profile Forum")  # combo type is distinct


def test_gbp_boundary():
    assert _is_gbpish("GBP - Web 2.0") and _is_gbpish("GMB Web 2.0")
    assert not _is_gbpish("Web 2.0")
    # The grouping prefixes gbp: so "GBP - Web 2.0" never merges into "Web 2.0".
    assert ("gbp:" + _norm_key("GBP - Web 2.0")) != _norm_key("Web 2.0")


def test_title_case_preserves_acronyms():
    assert _title_case("business listing") == "Business Listing"
    assert _title_case("SBM") == "SBM"          # acronyms untouched
    assert _title_case("guest post old") == "Guest Post Old"
