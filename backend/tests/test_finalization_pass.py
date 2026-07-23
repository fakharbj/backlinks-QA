"""Finalization pass — SERP index-time sort, viewer batch scoping, and the
company dashboard counts strip only reaching unrestricted users.

Each behaviour maps to an owner requirement:
  * backlinks sort by index_checked_at (per-result SERP time), not score;
  * viewers see ONLY their own review batches (task-sheet submissions), and
    cannot read another user's batch logs/items;
  * a project-scoped manager does not receive (and cannot be contradicted by)
    the workspace-wide entity-counts strip; an admin still does.
"""

from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.integration


def _register(client, name="Fin Admin"):
    email = f"fin+{uuid.uuid4().hex[:8]}@linksentinel.test"
    reg = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "Password-12345",
              "full_name": name, "workspace_name": f"Fin Ws {uuid.uuid4().hex[:5]}"},
    )
    assert reg.status_code == 201, reg.text
    return email, {"Authorization": f"Bearer {reg.json()['access_token']}"}


def test_backlinks_sort_index_checked_at_accepted(live_stack):
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        _, headers = _register(client)
        # The new per-result sort key must be accepted (was silently falling
        # through to score before it was whitelisted).
        r = client.get(
            "/api/v1/backlinks?sort=index_checked_at&direction=desc&limit=10",
            headers=headers,
        )
        assert r.status_code == 200, r.text
        # And the export endpoint accepts the index date range params.
        r2 = client.get(
            "/api/v1/backlinks/export?index_from=2026-01-01&index_to=2026-12-31&format=csv",
            headers=headers,
        )
        assert r2.status_code == 200, r2.text


def test_viewer_sees_only_own_batches(live_stack):
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        _, admin = _register(client)
        proj = client.post("/api/v1/projects", json={"name": "Fin Proj"}, headers=admin)
        project_id = proj.json()["id"]

        # Admin stages a link_review batch (started_by = admin).
        staged = client.post(
            "/api/v1/imports/paste",
            json={"project_id": project_id,
                  "text": "https://src.example.com/post\thttps://target.example.com/"},
            headers=admin,
        )
        assert staged.status_code in (200, 202), staged.text
        admin_batch = staged.json()["batch_id"]

        # A viewer in the same workspace.
        vemail = f"viewer+{uuid.uuid4().hex[:8]}@linksentinel.test"
        inv = client.post(
            "/api/v1/team/members",
            json={"email": vemail, "full_name": "Fin Viewer",
                  "role": "viewer", "password": "Password-12345"},
            headers=admin,
        )
        assert inv.status_code in (200, 201), inv.text
        login = client.post(
            "/api/v1/auth/login", json={"email": vemail, "password": "Password-12345"}
        )
        assert login.status_code == 200, login.text
        viewer = {"Authorization": f"Bearer {login.json()['access_token']}"}

        # The viewer must NOT see the admin's batch, and cannot read its logs.
        vbatches = client.get("/api/v1/batches", headers=viewer)
        assert vbatches.status_code == 200, vbatches.text
        assert all(b["id"] != admin_batch for b in vbatches.json())
        logs = client.get(f"/api/v1/batches/{admin_batch}/logs", headers=viewer)
        assert logs.status_code == 404
        items = client.get(f"/api/v1/batches/{admin_batch}/items", headers=viewer)
        assert items.status_code == 404

        # The admin still sees their own batch.
        abatches = client.get("/api/v1/batches", headers=admin)
        assert any(b["id"] == admin_batch for b in abatches.json())


def test_company_counts_only_for_unrestricted(live_stack):
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        _, admin = _register(client)
        proj = client.post("/api/v1/projects", json={"name": "Counts Proj"}, headers=admin)
        project_id = proj.json()["id"]

        # Admin (unrestricted) sees the company entity-counts strip.
        adash = client.get("/api/v1/dashboard", headers=admin)
        assert adash.status_code == 200, adash.text
        assert "counts" in adash.json() and adash.json()["counts"], adash.text

        # A manager scoped to a project (ProjectMember) must NOT get the strip.
        memail = f"mgr+{uuid.uuid4().hex[:8]}@linksentinel.test"
        inv = client.post(
            "/api/v1/team/members",
            json={"email": memail, "full_name": "Scoped Mgr",
                  "role": "manager", "password": "Password-12345"},
            headers=admin,
        )
        assert inv.status_code in (200, 201), inv.text
        mid = inv.json()["user_id"]
        scope = client.put(
            f"/api/v1/team/members/{mid}/projects",
            json={"project_ids": [project_id]}, headers=admin,
        )
        assert scope.status_code in (200, 204), scope.text
        login = client.post(
            "/api/v1/auth/login", json={"email": memail, "password": "Password-12345"}
        )
        assert login.status_code == 200, login.text
        mgr = {"Authorization": f"Bearer {login.json()['access_token']}"}
        mdash = client.get("/api/v1/dashboard", headers=mgr)
        assert mdash.status_code == 200, mdash.text
        # No workspace-wide counts leaked to a project-scoped manager.
        assert not mdash.json().get("counts"), mdash.json().get("counts")
