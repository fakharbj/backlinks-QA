"""End-to-end API test (PRD §14 acceptance criteria).

Uses FastAPI's TestClient (which drives the ASGI app + lifespan in its own loop,
sidestepping async-fixture loop pitfalls). Skips automatically unless Postgres +
Redis are reachable (see ``live_stack``).
"""

from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.integration


def test_register_project_backlink_dashboard_flow(live_stack):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        email = f"qa+{uuid.uuid4().hex[:8]}@linksentinel.test"
        reg = client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "password": "Password-12345",
                "full_name": "QA Specialist",
                "workspace_name": "Acme Link Ops",
            },
        )
        assert reg.status_code == 201, reg.text
        access = reg.json()["access_token"]
        headers = {"Authorization": f"Bearer {access}"}

        # Auth context resolves.
        me = client.get("/api/v1/auth/me", headers=headers)
        assert me.status_code == 200
        assert me.json()["role"] == "admin"

        # Create a project.
        proj = client.post("/api/v1/projects", json={"name": "Acme Backlinks"}, headers=headers)
        assert proj.status_code == 201, proj.text
        project_id = proj.json()["id"]

        # Create a backlink (normalized + PENDING).
        bl = client.post(
            "/api/v1/backlinks",
            json={
                "project_id": project_id,
                "source_page_url": "https://publisher.test/best-tools",
                "target_url": "https://acme.test/seo",
                "expected_anchor_text": "Acme SEO",
            },
            headers=headers,
        )
        assert bl.status_code == 201, bl.text
        assert bl.json()["status"] == "PENDING"

        # Grid lists it (keyset envelope).
        grid = client.get(
            f"/api/v1/backlinks?project_id={project_id}&with_total=true", headers=headers
        )
        assert grid.status_code == 200
        body = grid.json()
        assert body["total"] == 1
        assert body["items"][0]["source_page_url"] == "https://publisher.test/best-tools"

        # Dashboard responds from the materialized views.
        dash = client.get(f"/api/v1/dashboard?project_id={project_id}", headers=headers)
        assert dash.status_code == 200
        assert "totals" in dash.json()

        # RBAC: unauthenticated request is rejected.
        assert client.get("/api/v1/projects").status_code == 401


def test_login_rejects_bad_password(live_stack):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        email = f"qa+{uuid.uuid4().hex[:8]}@linksentinel.test"
        client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "password": "Password-12345",
                "full_name": "QA",
                "workspace_name": "WS",
            },
        )
        bad = client.post("/api/v1/auth/login", json={"email": email, "password": "wrong"})
        assert bad.status_code == 401
