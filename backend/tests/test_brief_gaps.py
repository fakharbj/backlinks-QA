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


def test_case_merge_never_creates_ghosts_and_tasks_stay_visible(live_stack):
    """Owner rule: 'Usman' and 'usman' are ONE person. A case merge must
    (a) keep the person's tasks findable under the lowercase label,
    (b) leave NO capitalized ghost in the planner picker or the People grid,
    (c) never surface the deactivated alias row as a laid-off person."""
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        h = _register(client)
        mk = client.post(
            "/api/v1/projects",
            json={"name": "Ghost Proj", "target_domain": "ghost.test"},
            headers=h,
        )
        pid = mk.json()["id"]
        day = date.today() + timedelta(days=1)
        # The API lowercases on write even when the admin types 'USMAN'.
        asg = client.post(
            "/api/v1/workforce/assignments",
            json={"project_id": pid, "user_label": "USMAN", "day": day.isoformat(), "hours": 4},
            headers=h,
        )
        assert asg.status_code in (200, 201), asg.text

        # Merge a capitalized alias into the person — canonical folds lowercase.
        # Link the identity to the calling account so /workforce/me resolves it.
        me_id = client.get("/api/v1/team/members", headers=h).json()[0]["user_id"]
        mg = client.post(
            "/api/v1/employees/merge",
            json={"canonical_label": "Usman", "alias_labels": ["USMAN", "Usman"], "user_id": me_id},
            headers=h,
        )
        assert mg.status_code == 200, mg.text
        assert mg.json()["canonical_label"] == "usman"

        # /workforce/me must resolve ONE lowercase identity — never the retired
        # alias spelling (labels[0]='Usman' used to blank the This-week strip
        # and the whole personal dashboard).
        mine = client.get(
            f"/api/v1/workforce/me?date_from={day.isoformat()}&date_to={day.isoformat()}",
            headers=h,
        ).json()
        assert mine["labels"] == ["usman"], mine["labels"]
        assert any(r["user_label"] == "usman" for r in mine["rows"])

        labels = client.get("/api/v1/workforce/labels", headers=h).json()
        assert "usman" in labels
        assert not any(l != l.lower() for l in labels), labels  # no capitalized ghosts

        people = client.get("/api/v1/workforce/people", headers=h).json()
        by_label = {p["user_label"]: p["active"] for p in people}
        assert by_label.get("usman") is True                  # the real person, active
        assert "Usman" not in by_label and "USMAN" not in by_label  # no ghost rows

        # The task is still there, under the lowercase person.
        rep = client.get(
            f"/api/v1/workforce/day-report?date_from={day.isoformat()}&date_to={day.isoformat()}",
            headers=h,
        ).json()
        assert any(r["user_label"] == "usman" and r["hours"] == 4 for r in rep)


def test_teamlead_labels_stored_lowercase(live_stack):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        h = _register(client)
        members = client.get("/api/v1/team/members", headers=h).json()
        me = members[0]["user_id"]
        put = client.put(
            "/api/v1/team/leads",
            json={"manager_user_id": me, "labels": ["ALEX", "Tony "]},
            headers=h,
        )
        assert put.status_code == 200, put.text
        rows = client.get("/api/v1/team/leads", headers=h).json()
        mine = next(r for r in rows if r["manager_user_id"] == me)
        assert sorted(mine["labels"]) == ["alex", "tony"]
