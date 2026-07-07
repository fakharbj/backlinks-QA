"""Company Gmail account tracking (Tranche H): catalog + assignment history to
users/projects, reassignment closing the prior active row, revoke, retire, and
the by-user / by-project views."""

from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.integration


def _register(client):
    email = f"qa+{uuid.uuid4().hex[:8]}@linksentinel.test"
    reg = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "Password-12345", "full_name": "Owner", "workspace_name": "Gmail Ws"},
    )
    assert reg.status_code == 201, reg.text
    return {"Authorization": f"Bearer {reg.json()['access_token']}"}


def test_gmail_lifecycle(live_stack):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        h = _register(client)
        me = client.get("/api/v1/auth/me", headers=h).json()
        my_uid = me["user"]["id"]
        pid = client.post("/api/v1/projects", json={"name": "GM", "target_domain": "gm.test"}, headers=h).json()["id"]

        addr = f"outreach-{uuid.uuid4().hex[:6]}@techsa.com"
        # Create (email normalised to lowercase; dedup on re-create).
        acc = client.post("/api/v1/gmail/accounts", json={"email": addr.upper(), "display_name": "Outreach 1"}, headers=h)
        assert acc.status_code == 200, acc.text
        aid = acc.json()["id"]
        assert acc.json()["email"] == addr.lower()
        dup = client.post("/api/v1/gmail/accounts", json={"email": addr}, headers=h)
        assert dup.json()["id"] == aid  # reused, not duplicated

        # Assign to a user and a project.
        au = client.post("/api/v1/gmail/assign", json={"account_id": aid, "scope": "user", "user_id": my_uid}, headers=h)
        assert au.status_code == 200, au.text
        ap = client.post("/api/v1/gmail/assign", json={"account_id": aid, "scope": "project", "project_id": pid}, headers=h)
        assert ap.status_code == 200, ap.text

        listed = client.get("/api/v1/gmail/accounts", headers=h).json()
        row = next(a for a in listed if a["id"] == aid)
        assert row["user_count"] == 1 and row["project_count"] == 1
        assert len(row["assignments"]) == 2

        # by-user / by-project views.
        bu = client.get(f"/api/v1/gmail/by-user/{my_uid}", headers=h).json()
        assert len(bu) == 1 and bu[0]["email"] == addr.lower()
        bp = client.get(f"/api/v1/gmail/by-project/{pid}", headers=h).json()
        assert len(bp) == 1 and bp[0]["account_id"] == aid

        # Reassigning the SAME address to the same user again closes the prior
        # active row (history kept) — still exactly one active user assignment.
        client.post("/api/v1/gmail/assign", json={"account_id": aid, "scope": "user", "user_id": my_uid}, headers=h)
        row2 = next(a for a in client.get("/api/v1/gmail/accounts", headers=h).json() if a["id"] == aid)
        assert row2["user_count"] == 1

        # Mark used sets last_used_at.
        used = client.post(f"/api/v1/gmail/accounts/{aid}/used", headers=h)
        assert used.status_code == 200 and used.json()["last_used_at"]

        # Revoke the project assignment.
        proj_asg = next(a for a in row2["assignments"] if a["scope"] == "project")
        rv = client.post(f"/api/v1/gmail/assignments/{proj_asg['id']}/revoke", headers=h)
        assert rv.status_code == 200
        assert not client.get(f"/api/v1/gmail/by-project/{pid}", headers=h).json()

        # Retire the account → inactive, remaining active assignments revoked.
        ret = client.delete(f"/api/v1/gmail/accounts/{aid}", headers=h)
        assert ret.status_code == 200
        assert not any(a["id"] == aid for a in client.get("/api/v1/gmail/accounts", headers=h).json())
        assert any(a["id"] == aid for a in client.get("/api/v1/gmail/accounts?include_retired=true", headers=h).json())
        assert not client.get(f"/api/v1/gmail/by-user/{my_uid}", headers=h).json()


def test_gmail_validation(live_stack):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        h = _register(client)
        bad = client.post("/api/v1/gmail/accounts", json={"email": "not-an-email"}, headers=h)
        assert bad.status_code == 422
        acc = client.post("/api/v1/gmail/accounts", json={"email": f"v-{uuid.uuid4().hex[:6]}@techsa.com"}, headers=h).json()
        # Scope=user without a user_id is rejected.
        notarget = client.post("/api/v1/gmail/assign", json={"account_id": acc["id"], "scope": "user"}, headers=h)
        assert notarget.status_code == 422
