"""Analytics filter-builder tests (Phase 5).

Covers the whitelisted WHERE construction: scoping, known/unknown keys, special
cases, and facet exclusion — all without a database.
"""

import uuid
from types import SimpleNamespace

from app.services import analytics_service as a


def _ctx(allowed=None):
    return SimpleNamespace(workspace_id=uuid.uuid4(), allowed_project_ids=allowed)


def test_scope_always_present_and_unknown_keys_ignored():
    where, params = a._build_where(_ctx(), {"definitely_not_a_filter": "x"})
    assert "b.workspace_id = :ws" in where
    assert "ws" in params
    assert "definitely_not_a_filter" not in where


def test_empty_values_skipped():
    where, params = a._build_where(_ctx(), {"link_type": "", "status": None, "rel": []})
    assert where == "b.workspace_id = :ws"


def test_known_filters_add_clauses():
    where, params = a._build_where(_ctx(), {"status": "FAIL", "rel": "nofollow"})
    assert "coalesce(b.override_status, b.status) = :status" in where
    assert params["status"] == "FAIL"
    assert "b.current_rel = :rel" in where
    assert params["rel"] == "nofollow"


def test_index_unchecked_is_null_check():
    where, _ = a._build_where(_ctx(), {"index_status": "unchecked"})
    assert "b.index_status IS NULL" in where


def test_duplicate_any_uses_flag():
    where, _ = a._build_where(_ctx(), {"duplicate_status": "duplicate"})
    assert "b.is_duplicate IS TRUE" in where


def test_http_class_range():
    where, _ = a._build_where(_ctx(), {"http_class": "4xx"})
    assert "b.http_status >= 400 AND b.http_status < 500" in where


def test_project_scoping_adds_any():
    pid = uuid.uuid4()
    where, params = a._build_where(_ctx(allowed={pid}), {})
    assert "b.project_id = ANY(:pids)" in where
    assert params["pids"] == [pid]


def test_facet_exclude_drops_own_filter():
    # When faceting on 'status', the status filter itself must be excluded so the
    # facet shows counts for every status under the other filters.
    where, _ = a._build_where(_ctx(), {"status": "FAIL", "rel": "nofollow"}, exclude="status")
    assert "= :status" not in where
    assert "b.current_rel = :rel" in where


def test_dimensions_are_whitelisted():
    dims = a.allowed_dimensions()
    assert "user" in dims and "project" in dims and "link_type" in dims
    assert "; drop" not in " ".join(dims)
