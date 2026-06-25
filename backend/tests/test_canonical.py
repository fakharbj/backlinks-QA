"""Canonical URL + fingerprint pure-logic tests (no DB / no network).

Mirrors the duplicate-detection design: cosmetically-different URLs for the same
page must share a fingerprint; different pages must not.
"""

from app.services.canonical_service import (
    canonical_form,
    fingerprint_for,
    fingerprint_of_raw,
)


def test_fingerprint_is_64_hex_and_deterministic():
    fp = fingerprint_for("https://example.com/page")
    assert len(fp) == 64
    assert all(c in "0123456789abcdef" for c in fp)
    assert fp == fingerprint_for("https://example.com/page")


def test_same_page_variants_share_one_fingerprint():
    # http→https, strip www, strip trailing slash, drop utm_*/ref tracking params.
    variants = [
        "https://techcrunch.com/article/ai",
        "http://www.techcrunch.com/article/ai",
        "https://techcrunch.com/article/ai/",
        "https://techcrunch.com/article/ai?utm_source=nl",
        "http://www.techcrunch.com/article/ai/?utm_source=newsletter&ref=twitter",
    ]
    fingerprints = {fingerprint_of_raw(u) for u in variants}
    assert None not in fingerprints
    assert len(fingerprints) == 1


def test_different_pages_have_different_fingerprints():
    a = fingerprint_of_raw("https://techcrunch.com/article/ai")
    b = fingerprint_of_raw("https://techcrunch.com/article/blockchain")
    assert a is not None and b is not None
    assert a != b


def test_meaningful_query_params_are_preserved():
    # Only tracking params are stripped; a real ?id= is part of the identity.
    with_id = fingerprint_of_raw("https://example.com/p?id=42")
    without_id = fingerprint_of_raw("https://example.com/p")
    assert with_id != without_id


def test_invalid_urls_have_no_fingerprint():
    assert canonical_form("mailto:hi@example.com") is None
    assert fingerprint_of_raw("javascript:void(0)") is None
    assert fingerprint_of_raw("") is None
