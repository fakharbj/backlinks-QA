"""Conflict scope classification + comparison helpers — pure logic (no DB / no network)."""

import uuid

from app.services.conflict_service import (
    CROSS_PROJECT,
    CROSS_USER,
    SAME_PROJECT,
    classify_scope,
    duplicate_reason,
    field_matrix,
    similarity_score,
)


def test_single_project_single_user_is_same_project():
    assert classify_scope(1, 1) == SAME_PROJECT


def test_multiple_projects_is_cross_project():
    assert classify_scope(2, 1) == CROSS_PROJECT


def test_project_spanning_wins_over_user_spanning():
    assert classify_scope(3, 5) == CROSS_PROJECT


def test_multiple_users_one_project_is_cross_user():
    assert classify_scope(1, 2) == CROSS_USER


# ── Comparison helpers (pure) ────────────────────────────────────────────────

_P1 = uuid.uuid4()


def _member(**over):
    base = {
        "backlink_id": uuid.uuid4(),
        "project_id": _P1,
        "source_domain": "blog.example.com",
        "target_url_normalized": "https://acme.com/",
        "target_domain": "acme.com",
        "current_anchor_text": "acme",
        "expected_anchor_text": None,
        "current_rel": "dofollow",
        "expected_rel": "dofollow",
        "assigned_user_label": "alex",
        "link_type": "guest_post",
        "placement_date": None,
        "score": 50,
        "created_at": None,
    }
    base.update(over)
    return base


def test_field_matrix_all_same_when_identical():
    members = [_member(), _member()]
    matrix = {r["field"]: r for r in field_matrix(members)}
    assert matrix["target_url_normalized"]["all_same"] is True
    assert matrix["anchor"]["all_same"] is True
    assert matrix["project_id"]["all_same"] is True


def test_field_matrix_detects_difference():
    members = [_member(), _member(target_url_normalized="https://acme.com/x")]
    matrix = {r["field"]: r for r in field_matrix(members)}
    assert matrix["target_url_normalized"]["all_same"] is False
    assert matrix["target_url_normalized"]["distinct"] == 2


def test_anchor_coalesces_expected_when_current_missing():
    members = [
        _member(current_anchor_text=None, expected_anchor_text="acme"),
        _member(current_anchor_text="acme", expected_anchor_text=None),
    ]
    matrix = {r["field"]: r for r in field_matrix(members)}
    assert matrix["anchor"]["all_same"] is True


def test_similarity_full_when_identical():
    members = [_member(), _member()]
    assert similarity_score(field_matrix(members)) == 100


def test_similarity_drops_when_fields_differ():
    members = [
        _member(),
        _member(project_id=uuid.uuid4(), assigned_user_label="sam",
                target_url_normalized="https://acme.com/x"),
    ]
    score = similarity_score(field_matrix(members))
    # target(30)+project(15)+user(10) lost of 100 → 45 remaining.
    assert score == 45


def test_similarity_is_bounded():
    s = similarity_score(field_matrix([_member(), _member(link_type="niche_edit",
                                                          current_rel="nofollow")]))
    assert 0 <= s <= 100


def test_duplicate_reason_mentions_differences():
    members = [_member(), _member(target_url_normalized="https://acme.com/x")]
    reason = duplicate_reason(SAME_PROJECT, field_matrix(members), len(members))
    assert "target URL" in reason
    assert "2 records" in reason


def test_duplicate_reason_identical():
    reason = duplicate_reason(SAME_PROJECT, field_matrix([_member(), _member()]), 2)
    assert "otherwise identical" in reason
