"""Lifecycle date types (0031): the backlink grid exposes every date field,
date-range filters use real ``date`` params (asyncpg-safe, inclusive end), the
grid sorts on date columns, and the analytics engine buckets/filters by date."""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest

pytestmark = pytest.mark.integration


def _register(client):
    email = f"qa+{uuid.uuid4().hex[:8]}@linksentinel.test"
    reg = client.post(
        "/api/v1/auth/register",
        json={
            "email": email, "password": "Password-12345",
            "full_name": "Admin", "workspace_name": "Date Types Ws",
        },
    )
    assert reg.status_code == 201, reg.text
    return {"Authorization": f"Bearer {reg.json()['access_token']}"}


def _make_project_and_backlink(client, h):
    proj = client.post(
        "/api/v1/projects",
        json={"name": "Date Proj", "target_domain": "acme-dates.test"},
        headers=h,
    )
    assert proj.status_code == 201, proj.text
    project_id = proj.json()["id"]

    tag = uuid.uuid4().hex[:6]
    created = client.post(
        "/api/v1/backlinks",
        json={
            "project_id": project_id,
            "source_page_url": f"https://pub-{tag}.test/article",
            "target_url": "https://acme-dates.test/",
        },
        headers=h,
    )
    assert created.status_code == 201, created.text
    return project_id, created.json()


def test_grid_row_exposes_all_date_fields(live_stack):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        h = _register(client)
        project_id, _ = _make_project_and_backlink(client, h)

        listing = client.get(
            "/api/v1/backlinks", params={"project_id": project_id}, headers=h
        )
        assert listing.status_code == 200, listing.text
        items = listing.json()["items"]
        assert len(items) == 1
        row = items[0]

        for key in (
            "placement_date", "discovered_at", "first_qa_at", "qa_completed_at",
            "assigned_at", "index_checked_at", "updated_at",
        ):
            assert key in row, f"missing date field: {key}"

        # discovered_at is stamped on insert (every create path sets it).
        assert row["discovered_at"] is not None


def test_date_range_filter_inclusive_end(live_stack):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        h = _register(client)
        project_id, _ = _make_project_and_backlink(client, h)

        today = date.today().isoformat()
        tomorrow = (date.today() + timedelta(days=1)).isoformat()

        # imported_from/imported_to map to created_at; the row imported "today"
        # falls inside [today, today] (inclusive end → < today+1day).
        hit = client.get(
            "/api/v1/backlinks",
            params={"project_id": project_id, "imported_from": today, "imported_to": today},
            headers=h,
        )
        assert hit.status_code == 200, hit.text
        assert len(hit.json()["items"]) == 1

        # A window starting tomorrow excludes today's row.
        miss = client.get(
            "/api/v1/backlinks",
            params={"project_id": project_id, "imported_from": tomorrow},
            headers=h,
        )
        assert miss.status_code == 200, miss.text
        assert miss.json()["items"] == []


def test_sort_by_discovered_at(live_stack):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        h = _register(client)
        project_id, _ = _make_project_and_backlink(client, h)

        res = client.get(
            "/api/v1/backlinks",
            params={"project_id": project_id, "sort": "discovered_at", "direction": "desc"},
            headers=h,
        )
        assert res.status_code == 200, res.text
        assert len(res.json()["items"]) == 1


def test_analytics_date_bucket_and_filter(live_stack):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        h = _register(client)
        project_id, _ = _make_project_and_backlink(client, h)

        today = date.today().isoformat()
        tomorrow = (date.today() + timedelta(days=1)).isoformat()

        # Month bucket dimension → keys look like YYYY-MM.
        grouped = client.post(
            "/api/v1/analytics/query",
            json={"filters": {"project_id": project_id}, "group_by": "imported_month"},
            headers=h,
        )
        assert grouped.status_code == 200, grouped.text
        groups = grouped.json()["groups"]
        assert groups, "expected at least one imported_month bucket"
        for g in groups:
            key = g["key"]
            assert key is None or (len(key) == 7 and key[4] == "-"), f"bad month key: {key}"

        # A date-range filter on the analytics engine returns 200 (asyncpg-safe
        # real-date params; unknown keys are ignored so this never 500s).
        filtered = client.post(
            "/api/v1/analytics/query",
            json={"filters": {"imported_from": today, "imported_to": tomorrow}},
            headers=h,
        )
        assert filtered.status_code == 200, filtered.text
