"""Final-pass Loop 5 tests: assignment snapshots (rate source + lph + priority),
manual-target priority, smart warnings (leave / non-working / over-allocation)
and the plannable-labels endpoint."""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest

pytestmark = pytest.mark.integration


def _next_weekday(d: date) -> date:
    while d.weekday() == 6:  # skip Sunday (default non-working)
        d += timedelta(days=1)
    return d


def test_assignment_snapshots_warnings_and_labels(live_stack):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        email = f"qa+{uuid.uuid4().hex[:8]}@linksentinel.test"
        reg = client.post(
            "/api/v1/auth/register",
            json={
                "email": email, "password": "Password-12345",
                "full_name": "QA Specialist", "workspace_name": "Final Loop5 Ws",
            },
        )
        assert reg.status_code == 201, reg.text
        headers = {"Authorization": f"Bearer {reg.json()['access_token']}"}
        proj = client.post("/api/v1/projects", json={"name": "Loop5 Proj"}, headers=headers)
        project_id = proj.json()["id"]

        day = _next_weekday(date.today() + timedelta(days=1)).isoformat()
        label = f"worker-{uuid.uuid4().hex[:6]}"

        # Global rate for the type, then a personal override that must win.
        put = client.put(
            "/api/v1/workforce/productivity",
            json={"link_type_name": "Profile", "links_per_hour": 10},
            headers=headers,
        )
        assert put.status_code == 200
        put2 = client.put(
            "/api/v1/workforce/productivity",
            json={"link_type_name": "Profile", "links_per_hour": 15, "user_label": label},
            headers=headers,
        )
        assert put2.status_code == 200

        # Auto target uses the personal rate → snapshot says 'override'.
        a1 = client.post(
            "/api/v1/workforce/assignments",
            json={
                "project_id": project_id, "user_label": label, "day": day,
                "hours": 2, "link_type_names": ["Profile"], "priority": "high",
                "note": "Only niche relevant",
            },
            headers=headers,
        )
        assert a1.status_code == 200, a1.text
        b1 = a1.json()
        assert b1["expected_links"] == 30  # 2h × 15/hr personal rate
        assert b1["rate_source"] == "override" and b1["lph_used"] == 15.0

        # Manual target beats everything → snapshot says 'manual'.
        proj2 = client.post("/api/v1/projects", json={"name": "Loop5 Proj B"}, headers=headers)
        project2_id = proj2.json()["id"]
        a2 = client.post(
            "/api/v1/workforce/assignments",
            json={
                "project_id": project2_id, "user_label": label, "day": day,
                "hours": 7, "link_type_names": ["Profile"], "expected_links": 12,
            },
            headers=headers,
        )
        assert a2.status_code == 200, a2.text
        b2 = a2.json()
        assert b2["rate_source"] == "manual" and b2["expected_links"] == 12
        # 2h + 7h = 9h on one day → over-allocation warning fires.
        assert any("more than" in w for w in b2["warnings"]), b2["warnings"]

        # Approved leave on the day → warning on subsequent planning.
        lv = client.post(
            "/api/v1/workforce/leaves",
            json={"user_label": label, "start_date": day, "end_date": day},
            headers=headers,
        )
        leave_id = lv.json()["id"]
        client.patch(f"/api/v1/workforce/leaves/{leave_id}?approve=true", headers=headers)
        # NB: same (project, user, day) → this UPDATES the first plan in place.
        a3 = client.post(
            "/api/v1/workforce/assignments",
            json={
                "project_id": project_id, "user_label": label, "day": day,
                "hours": 1, "link_type_names": ["Profile"], "priority": "high",
            },
            headers=headers,
        )
        assert any("APPROVED LEAVE" in w for w in a3.json()["warnings"])

        # Day report carries the snapshot fields.
        rep = client.get(
            "/api/v1/workforce/day-report",
            params={"date_from": day, "date_to": day},
            headers=headers,
        ).json()
        mine = [r for r in rep if r["user_label"] == label]
        assert mine and all("rate_source" in r and "priority" in r for r in mine)
        assert any(r["priority"] == "high" for r in mine)

        # Plannable labels include this person (via assignments).
        labels = client.get("/api/v1/workforce/labels", headers=headers).json()
        assert label in labels
