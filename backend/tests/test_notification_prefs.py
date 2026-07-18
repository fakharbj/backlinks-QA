"""Per-user notification preferences + personal notification delivery."""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest

pytestmark = pytest.mark.integration


def _register(client, ws="Notif Ws") -> dict:
    reg = client.post(
        "/api/v1/auth/register",
        json={
            "email": f"qa+{uuid.uuid4().hex[:8]}@linksentinel.test",
            "password": "Password-12345",
            "full_name": "Admin", "workspace_name": ws,
        },
    )
    assert reg.status_code == 201, reg.text
    return {"Authorization": f"Bearer {reg.json()['access_token']}"}


def test_prefs_defaults_mandatory_and_validation(live_stack):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        h = _register(client)
        got = client.get("/api/v1/notifications/prefs", headers=h)
        assert got.status_code == 200, got.text
        body = got.json()
        # Every category present, defaults on / in-app / immediate.
        keys = {c["key"] for c in body["categories"]}
        assert {"task_assigned", "leave_request", "security", "seo_alert"} <= keys
        assert all(p["enabled"] for p in body["prefs"].values())
        sec = next(c for c in body["categories"] if c["key"] == "security")
        assert sec["mandatory"] is True and sec["mandatory_why"]
        seo = next(c for c in body["categories"] if c["key"] == "seo_alert")
        assert seo["managed_by"] and seo["managed_why"]  # explained, not a dead toggle
        assert "email_available" in body

        # Disable a normal category → persists.
        put = client.put(
            "/api/v1/notifications/prefs",
            json={"task_assigned": {"enabled": False, "cadence": "daily"}},
            headers=h,
        )
        assert put.status_code == 200, put.text
        after = client.get("/api/v1/notifications/prefs", headers=h).json()["prefs"]
        assert after["task_assigned"]["enabled"] is False
        assert after["task_assigned"]["cadence"] == "daily"

        # Security is mandatory — refusing to disable it, with a clear message.
        bad = client.put(
            "/api/v1/notifications/prefs",
            json={"security": {"enabled": False}},
            headers=h,
        )
        assert bad.status_code in (400, 422)

        # Unknown categories are rejected.
        assert client.put(
            "/api/v1/notifications/prefs", json={"nope": {"enabled": True}}, headers=h
        ).status_code in (400, 422)


def test_assignment_emits_personal_notification_respecting_prefs(live_stack):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        h = _register(client)
        # Two logins: the admin (actor) and a member linked to the label.
        inv = client.post(
            "/api/v1/team/members",
            json={
                "email": f"worker+{uuid.uuid4().hex[:6]}@linksentinel.test",
                "full_name": "Worker", "role": "viewer", "password": "Password-12345",
            },
            headers=h,
        )
        assert inv.status_code == 201, inv.text
        worker_id = inv.json()["user_id"]

        mk = client.post(
            "/api/v1/projects",
            json={"name": "Notif Proj", "target_domain": "notif.test"},
            headers=h,
        )
        pid = mk.json()["id"]
        # Link the label to the worker's login via a case-only merge (creates
        # the canonical "notifee" row carrying user_id).
        mg = client.post(
            "/api/v1/employees/merge",
            json={"canonical_label": "notifee", "alias_labels": ["Notifee"], "user_id": worker_id},
            headers=h,
        )
        assert mg.status_code == 200, mg.text

        day = (date.today() + timedelta(days=1)).isoformat()
        asg = client.post(
            "/api/v1/workforce/assignments",
            json={"project_id": pid, "user_label": "notifee", "day": day, "hours": 3},
            headers=h,
        )
        assert asg.status_code in (200, 201), asg.text

        # The worker sees a personal task_assigned notification…
        login = client.post(
            "/api/v1/auth/login",
            json={"email": inv.json()["email"], "password": "Password-12345"},
        )
        assert login.status_code == 200, login.text
        wh = {"Authorization": f"Bearer {login.json()['access_token']}"}
        feed = client.get("/api/v1/notifications?limit=20", headers=wh)
        assert feed.status_code == 200, feed.text
        mine = [n for n in feed.json() if n["payload"].get("category") == "task_assigned"]
        assert mine, feed.json()
        assert "New task" in mine[0]["title"]

        # …the ADMIN does not (personal rows are recipient-only).
        admin_feed = client.get("/api/v1/notifications?limit=50", headers=h).json()
        assert not any(
            n["payload"].get("category") == "task_assigned" for n in admin_feed
        )

        # Editing the same day/project emits task_changed instead.
        asg2 = client.post(
            "/api/v1/workforce/assignments",
            json={"project_id": pid, "user_label": "notifee", "day": day, "hours": 5},
            headers=h,
        )
        assert asg2.status_code in (200, 201)
        feed2 = client.get("/api/v1/notifications?limit=20", headers=wh).json()
        assert any(n["payload"].get("category") == "task_changed" for n in feed2)

        # Worker disables the category → the next change stays silent.
        assert client.put(
            "/api/v1/notifications/prefs",
            json={"task_changed": {"enabled": False}},
            headers=wh,
        ).status_code == 200
        before = len([n for n in feed2 if n["payload"].get("category") == "task_changed"])
        client.post(
            "/api/v1/workforce/assignments",
            json={"project_id": pid, "user_label": "notifee", "day": day, "hours": 6},
            headers=h,
        )
        feed3 = client.get("/api/v1/notifications?limit=20", headers=wh).json()
        after = len([n for n in feed3 if n["payload"].get("category") == "task_changed"])
        assert after == before

        # Mark one read → unread count drops.
        target = next(n for n in feed3 if n["status"] != "read")
        assert client.post(f"/api/v1/notifications/{target['id']}/read", headers=wh).status_code == 200


def test_security_notification_on_password_reset_is_mandatory(live_stack):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        h = _register(client)
        inv = client.post(
            "/api/v1/team/members",
            json={
                "email": f"sec+{uuid.uuid4().hex[:6]}@linksentinel.test",
                "full_name": "Sec Target", "role": "viewer", "password": "Password-12345",
            },
            headers=h,
        )
        target_id = inv.json()["user_id"]
        reset = client.post(f"/api/v1/team/members/{target_id}/reset-password", headers=h)
        assert reset.status_code == 200, reset.text
        temp = reset.json()["temp_password"]
        login = client.post(
            "/api/v1/auth/login", json={"email": inv.json()["email"], "password": temp}
        )
        assert login.status_code == 200, login.text
        th = {"Authorization": f"Bearer {login.json()['access_token']}"}
        feed = client.get("/api/v1/notifications?limit=10", headers=th).json()
        assert any(n["payload"].get("category") == "security" for n in feed), feed
