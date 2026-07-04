"""Final-pass Loop 6 tests: standard-user (viewer) data scoping, self-only
leave requests, employees catalog gating, deactivated-login message and the
/workforce/me self view."""

from __future__ import annotations

import uuid
from datetime import date

import pytest

pytestmark = pytest.mark.integration


def test_viewer_scoping_and_deactivated_login(live_stack):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        admin_email = f"qa+{uuid.uuid4().hex[:8]}@linksentinel.test"
        reg = client.post(
            "/api/v1/auth/register",
            json={
                "email": admin_email, "password": "Password-12345",
                "full_name": "Admin", "workspace_name": "Final Loop6 Ws",
            },
        )
        assert reg.status_code == 201, reg.text
        admin = {"Authorization": f"Bearer {reg.json()['access_token']}"}
        proj = client.post("/api/v1/projects", json={"name": "Loop6 Proj"}, headers=admin)
        project_id = proj.json()["id"]

        # Team-wide plans exist (two other people).
        today = date.today().isoformat()
        for label in ("colleague-a", "colleague-b"):
            client.post(
                "/api/v1/workforce/assignments",
                json={
                    "project_id": project_id, "user_label": label, "day": today,
                    "hours": 4, "link_type_names": [],
                },
                headers=admin,
            )

        # A standard user (viewer), NOT linked to any team label.
        viewer_email = f"viewer+{uuid.uuid4().hex[:6]}@linksentinel.test"
        inv = client.post(
            "/api/v1/team/members",
            json={
                "email": viewer_email, "full_name": "Standard User",
                "role": "viewer", "password": "Password-12345",
            },
            headers=admin,
        )
        assert inv.status_code == 201, inv.text
        viewer_id = inv.json()["user_id"]
        vlogin = client.post(
            "/api/v1/auth/login", json={"email": viewer_email, "password": "Password-12345"}
        )
        viewer = {"Authorization": f"Bearer {vlogin.json()['access_token']}"}

        # /auth/me exposes the role for nav gating.
        assert client.get("/api/v1/auth/me", headers=viewer).json()["role"] == "viewer"

        # LEAK FIXES: a viewer sees NOBODY else's plans, leaves or overrides.
        rep = client.get(
            "/api/v1/workforce/day-report",
            params={"date_from": today, "date_to": today},
            headers=viewer,
        )
        assert rep.status_code == 200 and rep.json() == []
        lv = client.get("/api/v1/workforce/leaves", headers=viewer)
        assert lv.status_code == 200 and lv.json() == []
        perf = client.get("/api/v1/performance/users", headers=viewer)
        assert perf.status_code == 200 and perf.json()["users"] == []

        # Employees catalog (emails + identity mapping) is management-only now.
        assert client.get("/api/v1/employees", headers=viewer).status_code == 403

        # Self-only leave: an unlinked viewer cannot file leave under ANY name.
        steal = client.post(
            "/api/v1/workforce/leaves",
            json={"user_label": "colleague-a", "start_date": today, "end_date": today},
            headers=viewer,
        )
        assert steal.status_code in (400, 422)  # validation error: not linked

        # /workforce/me: honest empty state for the unlinked account.
        mine = client.get(
            "/api/v1/workforce/me",
            params={"date_from": today, "date_to": today},
            headers=viewer,
        ).json()
        assert mine == {"labels": [], "rows": [], "leaves": []}

        # Deactivation blocks login with the friendly message; nothing is deleted.
        off = client.post(
            f"/api/v1/team/members/{viewer_id}/active",
            json={"is_active": False},
            headers=admin,
        )
        assert off.status_code == 200
        dead = client.post(
            "/api/v1/auth/login", json={"email": viewer_email, "password": "Password-12345"}
        )
        assert dead.status_code == 401
        assert "inactive" in dead.json()["error"]["message"].lower()
        # History intact: the workspace's plans are untouched.
        rep2 = client.get(
            "/api/v1/workforce/day-report",
            params={"date_from": today, "date_to": today},
            headers=admin,
        )
        assert len(rep2.json()) == 2
