"""Final batch 3: admin user-dashboard endpoint (hours/plan/links/compare,
project scoping, viewer protection) and the project-effort rollup."""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest

pytestmark = pytest.mark.integration


def _next_weekday(d: date) -> date:
    while d.weekday() == 6:
        d += timedelta(days=1)
    return d


def test_user_dashboard_and_project_effort(live_stack):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        email = f"qa+{uuid.uuid4().hex[:8]}@linksentinel.test"
        reg = client.post(
            "/api/v1/auth/register",
            json={
                "email": email, "password": "Password-12345",
                "full_name": "Admin", "workspace_name": "Final Batch3 Ws",
            },
        )
        assert reg.status_code == 201, reg.text
        h = {"Authorization": f"Bearer {reg.json()['access_token']}"}
        proj = client.post("/api/v1/projects", json={"name": "B3 Proj"}, headers=h)
        project_id = proj.json()["id"]
        label = f"dash-{uuid.uuid4().hex[:6]}"

        # A plan for TODAY (2h, manual target 10) + one produced link on the same
        # day. Today may be a Sunday — force it to be a working day so the plan
        # counts toward the target instead of being excused.
        day = date.today()
        client.put(
            "/api/v1/workforce/calendar",
            json={"day": day.isoformat(), "is_working": True},
            headers=h,
        )
        a = client.post(
            "/api/v1/workforce/assignments",
            json={
                "project_id": project_id, "user_label": label, "day": day.isoformat(),
                "hours": 2, "link_type_names": ["Article"], "expected_links": 10,
                "priority": "high",
            },
            headers=h,
        )
        assert a.status_code == 200, a.text
        bl = client.post(
            "/api/v1/backlinks",
            json={
                "project_id": project_id,
                "source_page_url": f"https://blog-{label}.test/post",
                "target_url": "https://acme.test/",
            },
            headers=h,
        )
        assert bl.status_code == 201, bl.text
        # Attribute the link to the person (normally the sheet import does this).
        upd = client.patch(
            f"/api/v1/backlinks/{bl.json()['id']}",
            json={"assigned_user_label": label},
            headers=h,
        )
        assert upd.status_code == 200, upd.text

        d = client.get(
            "/api/v1/performance/user-dashboard",
            params={"user_label": label, "days": 30, "compare": "true"},
            headers=h,
        )
        assert d.status_code == 200, d.text
        body = d.json()
        assert body["plan"]["hours_assigned"] == 2.0
        assert body["plan"]["target"] == 10
        assert body["plan"]["done"] == 1
        assert body["plan"]["completion_pct"] == 10.0
        assert body["links"]["links"] == 1 and body["links"]["qa_pending"] == 1
        assert body["previous"] is not None  # compare window present
        assert body["projects"] and body["projects"][0]["project_id"] == project_id
        assert body["projects"][0]["hours"] == 2.0 and body["projects"][0]["target"] == 10

        # Project scoping: a different project id yields an empty dashboard.
        other = client.post("/api/v1/projects", json={"name": "B3 Other"}, headers=h)
        d2 = client.get(
            "/api/v1/performance/user-dashboard",
            params={"user_label": label, "project_id": other.json()["id"]},
            headers=h,
        ).json()
        assert d2["links"]["links"] == 0 and d2["plan"]["target"] == 0

        # Project effort rollup.
        pe = client.get(
            "/api/v1/performance/project-effort",
            params={"project_id": project_id, "days": 30},
            headers=h,
        )
        assert pe.status_code == 200, pe.text
        eff = pe.json()
        assert eff["totals"]["hours"] == 2.0 and eff["totals"]["target"] == 10
        assert eff["totals"]["links"] == 1 and eff["totals"]["users"] == 1
        mine = next(u for u in eff["users"] if u["user_label"] == label)
        assert mine["qa_pending"] == 1 and mine["completion_pct"] == 10.0
        assert eff["by_type"]  # link-type distribution present

        # Viewer protection: a standard user cannot open other people's dashboards.
        inv = client.post(
            "/api/v1/team/members",
            json={
                "email": f"viewer+{uuid.uuid4().hex[:6]}@linksentinel.test",
                "full_name": "Viewer", "role": "viewer", "password": "Password-12345",
            },
            headers=h,
        )
        vtok = client.post(
            "/api/v1/auth/login",
            json={"email": inv.json()["email"], "password": "Password-12345"},
        ).json()["access_token"]
        blocked = client.get(
            "/api/v1/performance/user-dashboard",
            params={"user_label": label},
            headers={"Authorization": f"Bearer {vtok}"},
        )
        assert blocked.status_code == 404
