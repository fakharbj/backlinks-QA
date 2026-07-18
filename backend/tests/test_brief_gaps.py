"""Production-brief gap coverage: per-weekday capacity hours, data-health
reconciliation checks, project status on the sheets list, account-health
fields on team members, and case-insensitive email uniqueness behavior."""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest

pytestmark = pytest.mark.integration


def _register(client) -> dict:
    email = f"qa+{uuid.uuid4().hex[:8]}@linksentinel.test"
    reg = client.post(
        "/api/v1/auth/register",
        json={
            "email": email, "password": "Password-12345",
            "full_name": "Admin", "workspace_name": "Brief Gaps Ws",
        },
    )
    assert reg.status_code == 201, reg.text
    return {"Authorization": f"Bearer {reg.json()['access_token']}"}


def test_cap_for_resolves_uniform_and_per_day():
    from app.api.v1.workforce import _cap_for

    assert _cap_for(8, 0) == 8.0
    assert _cap_for("6", 4) == 6.0
    assert _cap_for(None, 2) == 8.0                     # garbage → default
    week = [8, 8, 8, 8, 6, 0, 0]                        # part-time Friday, weekend off
    assert _cap_for(week, 4) == 6.0
    assert _cap_for(week, 5) == 0.0
    assert _cap_for(week, 0) == 8.0
    assert _cap_for([30, 8, 8, 8, 8, 8, 8], 0) == 24.0  # clamped to a real day


def test_capacity_per_weekday_schedule_roundtrip(live_stack):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        h = _register(client)
        # Plan someone in so they appear in known labels.
        day = date.today()
        monday = day - timedelta(days=day.weekday())
        mk = client.post(
            "/api/v1/projects",
            json={"name": "Cap Proj", "target_domain": "cap.test"},
            headers=h,
        )
        assert mk.status_code == 201, mk.text
        pid = mk.json()["id"]
        asg = client.post(
            "/api/v1/workforce/assignments",
            json={
                "user_label": "parttimer", "project_id": pid,
                "day": monday.isoformat(), "hours": 7,
            },
            headers=h,
        )
        assert asg.status_code in (200, 201), asg.text

        # Per-weekday schedule: 6h Mon-Thu, 4h Fri, weekend off.
        put = client.put(
            "/api/v1/workforce/daily-hours",
            json={"user_label": "PartTimer", "day_hours": [6, 6, 6, 6, 4, 0, 0]},
            headers=h,
        )
        assert put.status_code == 200, put.text

        cap = client.get(
            f"/api/v1/workforce/capacity?week_start={monday.isoformat()}", headers=h
        )
        assert cap.status_code == 200, cap.text
        row = next(p for p in cap.json()["people"] if p["user_label"] == "parttimer")
        assert row["day_hours"] == [6, 6, 6, 6, 4, 0, 0]
        mon = row["days"][0]
        assert mon["capacity"] == 6.0
        assert mon["assigned"] == 7.0
        assert mon["over"] is True                       # 7 assigned > 6 capacity
        fri = row["days"][4]
        assert fri["capacity"] in (0.0, 4.0)             # 0 if the calendar marks Friday off
        sat = row["days"][5]
        assert sat["capacity"] == 0.0 and sat["working"] is False
        assert row["utilization_pct"] is not None
        assert row["week_capacity"] == sum(
            c["capacity"] for c in row["days"]
        )

        # Uniform value still works and replaces the schedule.
        put2 = client.put(
            "/api/v1/workforce/daily-hours",
            json={"user_label": "parttimer", "hours": 5},
            headers=h,
        )
        assert put2.status_code == 200, put2.text
        cap2 = client.get(
            f"/api/v1/workforce/capacity?week_start={monday.isoformat()}", headers=h
        )
        row2 = next(p for p in cap2.json()["people"] if p["user_label"] == "parttimer")
        assert row2["day_hours"] is None
        assert row2["daily_hours"] == 5.0


def test_data_health_reports_consistency_checks(live_stack):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        h = _register(client)
        res = client.get("/api/v1/team/data-health", headers=h)
        assert res.status_code == 200, res.text
        body = res.json()
        keys = {c["key"] for c in body["checks"]}
        assert {
            "unassigned_links", "future_tasks_inactive_projects",
            "future_tasks_laid_off", "mixed_case_labels",
            "duplicate_emails", "batch_status_mismatch",
        } <= keys
        for c in body["checks"]:
            assert c["ok"] == (c["count"] == 0)
            assert isinstance(c["sample"], list) and isinstance(c["help"], str)


def test_sheets_list_includes_project_status(live_stack):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        h = _register(client)
        res = client.get("/api/v1/sheets", headers=h)
        assert res.status_code == 200, res.text
        for row in res.json():
            assert "project_status" in row


def test_team_members_expose_account_health_never_password(live_stack):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        h = _register(client)
        res = client.get("/api/v1/team/members", headers=h)
        assert res.status_code == 200, res.text
        me = res.json()[0]
        assert me["password_set"] is True
        assert me["failed_login_attempts"] == 0
        assert "locked_until" in me
        # The hash itself must never appear in the payload.
        assert "password" not in {k.lower() for k in me} - {"password_set"}
        assert "password_hash" not in me


def test_account_email_change_is_case_insensitive_conflict(live_stack):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        h = _register(client)
        members = client.get("/api/v1/team/members", headers=h).json()
        my_id = members[0]["user_id"]
        my_email = members[0]["email"]
        # Changing the email to a case-variant of itself is a no-op (same
        # account), never a duplicate-creating rename.
        res = client.patch(
            f"/api/v1/team/members/{my_id}/account",
            json={"email": my_email.upper()},
            headers=h,
        )
        assert res.status_code == 200, res.text
        after = client.get("/api/v1/team/members", headers=h).json()[0]["email"]
        assert after == my_email  # stored lowercase, unchanged
