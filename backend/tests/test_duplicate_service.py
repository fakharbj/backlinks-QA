"""Duplicate classification + identity-key tests (Phase 3).

These cover the pure logic that drives duplicate detection, so the rule is
verifiable without a database.
"""

import uuid

from app.services import duplicate_service as dup


def test_single_occurrence_is_unique():
    assert dup.classify_duplicate(occurrence_count=1, project_count=1, user_count=1) == dup.UNIQUE


def test_zero_occurrence_is_unique():
    # An identity with no mapped rows is treated as unique (not a duplicate).
    assert dup.classify_duplicate(0, 0, 0) == dup.UNIQUE


def test_same_project_same_user_duplicate():
    # Two rows, same project, same user → same-project duplicate (e.g. two target
    # URLs on the same domain from one source page).
    assert dup.classify_duplicate(2, 1, 1) == dup.DUP_SAME_PROJECT


def test_cross_user_duplicate():
    # Same source+target identity assigned to two different users.
    assert dup.classify_duplicate(2, 1, 2) == dup.DUP_CROSS_USER


def test_cross_project_takes_precedence_over_user():
    # Spanning projects is the most significant conflict — it wins over user.
    assert dup.classify_duplicate(3, 2, 2) == dup.DUP_CROSS_PROJECT


def test_cross_project_with_single_user():
    assert dup.classify_duplicate(2, 2, 1) == dup.DUP_CROSS_PROJECT


def test_identity_key_is_deterministic():
    ws = uuid.UUID("11111111-1111-1111-1111-111111111111")
    k1 = dup.identity_key(ws, "https://a.com/post", "b.com")
    k2 = dup.identity_key(ws, "https://a.com/post", "b.com")
    assert k1 == k2
    assert len(k1) == 64  # sha256 hex


def test_identity_key_varies_with_inputs():
    ws = uuid.UUID("11111111-1111-1111-1111-111111111111")
    base = dup.identity_key(ws, "https://a.com/post", "b.com")
    assert dup.identity_key(ws, "https://a.com/other", "b.com") != base   # source differs
    assert dup.identity_key(ws, "https://a.com/post", "c.com") != base    # target domain differs
    other_ws = uuid.UUID("22222222-2222-2222-2222-222222222222")
    assert dup.identity_key(other_ws, "https://a.com/post", "b.com") != base  # workspace differs


def test_identity_key_handles_empty_target_domain():
    ws = uuid.UUID("11111111-1111-1111-1111-111111111111")
    # None and "" target domains must hash to the same identity (consistent backfill).
    assert dup.identity_key(ws, "https://a.com/post", "") == dup.identity_key(
        ws, "https://a.com/post", None  # type: ignore[arg-type]
    )
