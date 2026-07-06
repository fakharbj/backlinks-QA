"""Analytics + dashboard KPI surface: the analytics summary and dashboard ``kpi``
dict expose the headline HTTP/index/verdict/spam/duplicate/orphaned buckets, the
whitelisted filters narrow (never 500), group-by pivots return groups, and the
Backlinks grid honours the KPI drill-down params (broken/http_status/orphaned/
spam_min). All hermetic — no worker, no external HTTP; buckets may legitimately be
0 in a fresh workspace (we assert the keys exist and the qualified/pass identity)."""

from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.integration

# The headline KPI keys the analytics summary + dashboard.kpi must always expose.
_KPI_KEYS = (
    "http_200", "http_301", "http_302", "http_404", "broken",
    "indexed", "not_indexed", "qualified", "non_qualified",
    "spam", "duplicate", "orphaned",
)


def _register(client):
    email = f"qa+{uuid.uuid4().hex[:8]}@linksentinel.test"
    reg = client.post(
        "/api/v1/auth/register",
        json={
            "email": email, "password": "Password-12345",
            "full_name": "Admin", "workspace_name": "Analytics KPI Ws",
        },
    )
    assert reg.status_code == 201, reg.text
    return {"Authorization": f"Bearer {reg.json()['access_token']}"}


def _make_project(client, h, *, domain="acme-kpi.test"):
    proj = client.post(
        "/api/v1/projects",
        json={"name": "KPI Proj", "target_domain": domain},
        headers=h,
    )
    assert proj.status_code == 201, proj.text
    return proj.json()["id"]


def _add_backlink(client, h, project_id, source_url, *, target="https://acme-kpi.test/"):
    created = client.post(
        "/api/v1/backlinks",
        json={"project_id": project_id, "source_page_url": source_url, "target_url": target},
        headers=h,
    )
    assert created.status_code == 201, created.text
    return created.json()["id"]


def _override(client, h, backlink_id, status_value):
    res = client.post(
        f"/api/v1/backlinks/{backlink_id}/override",
        json={"status": status_value, "note": f"seed {status_value}"},
        headers=h,
    )
    assert res.status_code == 200, res.text
    return res.json()


def _seed(client, h):
    """A project with 4 backlinks: 2 overridden PASS, 1 FAIL, 1 left as-is."""
    project_id = _make_project(client, h)
    tag = uuid.uuid4().hex[:6]
    ids = [
        _add_backlink(client, h, project_id, f"https://pub-{tag}.test/{i}")
        for i in range(4)
    ]
    _override(client, h, ids[0], "PASS")
    _override(client, h, ids[1], "PASS")
    _override(client, h, ids[2], "FAIL")
    return project_id, ids


# ── 1. Summary shape + qualified == pass count ────────────────────────────────
def test_analytics_summary_has_all_kpi_keys(live_stack):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        h = _register(client)
        project_id, _ = _seed(client, h)

        res = client.post(
            "/api/v1/analytics/query",
            json={"filters": {"project_id": project_id}},
            headers=h,
        )
        assert res.status_code == 200, res.text
        summary = res.json()["summary"]

        for key in _KPI_KEYS:
            assert key in summary, f"missing KPI key in analytics summary: {key}"
            # every KPI bucket is an int count (>= 0), never a string/None.
            assert isinstance(summary[key], int) and summary[key] >= 0

        # We overrode exactly two rows to PASS → qualified must equal that.
        assert summary["qualified"] == 2
        # non_qualified mirrors the single FAIL override.
        assert summary["non_qualified"] == 1
        # total reflects the four seeded rows.
        assert summary["total"] == 4


# ── 2. Filters narrow, and never 500 ──────────────────────────────────────────
def test_analytics_filters_narrow_and_are_safe(live_stack):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        h = _register(client)
        project_id, _ = _seed(client, h)

        # status=PASS narrows to the two overridden rows.
        passed = client.post(
            "/api/v1/analytics/query",
            json={"filters": {"project_id": project_id, "status": "PASS"}},
            headers=h,
        )
        assert passed.status_code == 200, passed.text
        assert passed.json()["summary"]["total"] == 2

        # status=FAIL narrows to the single fail.
        failed = client.post(
            "/api/v1/analytics/query",
            json={"filters": {"project_id": project_id, "status": "FAIL"}},
            headers=h,
        )
        assert failed.status_code == 200, failed.text
        assert failed.json()["summary"]["total"] == 1

        # http_status filter: freshly-created rows have no crawl yet (http_status
        # NULL), so an exact "404" filter returns 0 rows — the point is it BINDS a
        # real value and does not error (asyncpg-safe IN-list, no ::type cast bug).
        http = client.post(
            "/api/v1/analytics/query",
            json={"filters": {"project_id": project_id, "http_status": "404"}},
            headers=h,
        )
        assert http.status_code == 200, http.text
        assert http.json()["summary"]["total"] == 0

        # broken flag (http_status >= 400) also binds & runs without a 500.
        broken = client.post(
            "/api/v1/analytics/query",
            json={"filters": {"project_id": project_id, "broken": True}},
            headers=h,
        )
        assert broken.status_code == 200, broken.text

        # An unknown filter key is ignored (whitelist), never a 500.
        junk = client.post(
            "/api/v1/analytics/query",
            json={"filters": {"project_id": project_id, "totally_made_up": "x'; DROP"}},
            headers=h,
        )
        assert junk.status_code == 200, junk.text
        assert junk.json()["summary"]["total"] == 4


# ── 3. Group-by pivots ────────────────────────────────────────────────────────
def test_analytics_group_by_dimensions(live_stack):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        h = _register(client)
        project_id, _ = _seed(client, h)

        by_http = client.post(
            "/api/v1/analytics/query",
            json={"filters": {"project_id": project_id}, "group_by": "http_status"},
            headers=h,
        )
        assert by_http.status_code == 200, by_http.text
        assert isinstance(by_http.json()["groups"], list)

        by_band = client.post(
            "/api/v1/analytics/query",
            json={"filters": {"project_id": project_id}, "group_by": "score_band"},
            headers=h,
        )
        assert by_band.status_code == 200, by_band.text
        groups = by_band.json()["groups"]
        assert isinstance(groups, list)
        # Each group carries the shared metric block (total + pass/fail counts).
        for g in groups:
            assert "key" in g and "total" in g

        # status group-by should surface a PASS bucket with n=2.
        by_status = client.post(
            "/api/v1/analytics/query",
            json={"filters": {"project_id": project_id}, "group_by": "status"},
            headers=h,
        ).json()["groups"]
        pass_group = [g for g in by_status if g["key"] == "PASS"]
        assert pass_group and pass_group[0]["total"] == 2

        # An unknown/unwhitelisted dimension yields no groups (never a 500).
        junk = client.post(
            "/api/v1/analytics/query",
            json={"filters": {"project_id": project_id}, "group_by": "not_a_dimension"},
            headers=h,
        )
        assert junk.status_code == 200, junk.text
        assert junk.json()["groups"] == []


# ── 4. Backlinks KPI drill-down params ────────────────────────────────────────
def test_backlinks_kpi_drilldown_params_are_safe(live_stack):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        h = _register(client)
        project_id, _ = _seed(client, h)

        for params in (
            {"broken": "true"},
            {"http_status": "200"},
            {"orphaned": "true"},
            {"spam_min": 30},
        ):
            q = {"project_id": project_id, **params}
            res = client.get("/api/v1/backlinks", params=q, headers=h)
            assert res.status_code == 200, f"{params} -> {res.status_code}: {res.text}"
            body = res.json()
            assert "items" in body and isinstance(body["items"], list)

        # orphaned=true: fresh links have no source_domains aggregate row, so all
        # four match (sd.id IS NULL) — proves the LEFT JOIN filter path runs.
        orph = client.get(
            "/api/v1/backlinks",
            params={"project_id": project_id, "orphaned": "true", "with_total": True},
            headers=h,
        ).json()
        assert (orph.get("total") or 0) == 4

        # spam_min with no aggregate rows → 0 matches, still 200 + shaped items.
        spam = client.get(
            "/api/v1/backlinks",
            params={"project_id": project_id, "spam_min": 50, "with_total": True},
            headers=h,
        ).json()
        assert (spam.get("total") or 0) == 0 and spam["items"] == []


# ── 5. Dashboard KPI dict ─────────────────────────────────────────────────────
def test_dashboard_exposes_kpi_keys(live_stack):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        h = _register(client)
        project_id, _ = _seed(client, h)

        # Company (all-projects) dashboard.
        res = client.get("/api/v1/dashboard", headers=h)
        assert res.status_code == 200, res.text
        kpi = res.json()["kpi"]
        for key in _KPI_KEYS:
            assert key in kpi, f"missing KPI key in dashboard.kpi: {key}"
            assert isinstance(kpi[key], int) and kpi[key] >= 0
        assert kpi["qualified"] == 2 and kpi["non_qualified"] == 1

        # Project-scoped dashboard resolves the same keys.
        scoped = client.get(
            "/api/v1/dashboard", params={"project_id": project_id}, headers=h
        )
        assert scoped.status_code == 200, scoped.text
        pk = scoped.json()["kpi"]
        for key in _KPI_KEYS:
            assert key in pk
        assert pk["qualified"] == 2 and pk["non_qualified"] == 1
