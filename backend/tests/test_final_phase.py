"""Final-phase tests: import-target defaulting (project target fills the missing
target column), competitor parent grouping (one parent per registrable domain
across uploads), and a few phase route contracts."""

from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.integration


def _register(client):
    email = f"qa+{uuid.uuid4().hex[:8]}@linksentinel.test"
    reg = client.post(
        "/api/v1/auth/register",
        json={
            "email": email, "password": "Password-12345",
            "full_name": "QA Specialist", "workspace_name": "Final Phase Ws",
        },
    )
    assert reg.status_code == 201, reg.text
    return {"Authorization": f"Bearer {reg.json()['access_token']}"}


def test_import_target_defaulting(live_stack):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        h = _register(client)
        proj = client.post(
            "/api/v1/projects",
            json={"name": "Target Default Proj", "target_domain": "acme-final.test"},
            headers=h,
        )
        assert proj.status_code == 201, proj.text
        project_id = proj.json()["id"]

        tag = uuid.uuid4().hex[:6]
        # Bare source URLs — no header row, no target column.
        paste = f"https://pub-{tag}.test/a\nhttps://pub-{tag}.test/b\n"
        staged = client.post(
            "/api/v1/imports/paste",
            json={"project_id": project_id, "text": paste},
            headers=h,
        )
        assert staged.status_code == 202, staged.text
        body = staged.json()
        assert body["invalid"] == 0
        assert body["new"] == 2
        assert body["default_target"] == "https://acme-final.test"
        batch_id = body["batch_id"]

        # Every staged item picked up the project target as its target_url.
        items = client.get(f"/api/v1/batches/{batch_id}/items", headers=h).json()["items"]
        assert len(items) == 2
        for it in items:
            assert it["payload"]["mapped"]["target_url"] == "https://acme-final.test"

        # Approve all → both land as real backlinks.
        approve = client.post(
            f"/api/v1/batches/{batch_id}/items/approve", json={}, headers=h
        )
        assert approve.status_code == 200, approve.text
        assert approve.json()["new_rows"] == 2

        rows = client.get(
            "/api/v1/backlinks",
            params={"project_id": project_id, "with_total": True},
            headers=h,
        ).json()
        assert rows["total"] == 2
        assert all(
            r["target_url"].rstrip("/") == "https://acme-final.test" for r in rows["items"]
        )

        # A project WITHOUT a target_domain still enforces the target column:
        # a bare source URL is invalid (missing target, no default to fall back on).
        proj2 = client.post(
            "/api/v1/projects", json={"name": "No Target Proj"}, headers=h
        )
        assert proj2.status_code == 201, proj2.text
        project2_id = proj2.json()["id"]
        staged2 = client.post(
            "/api/v1/imports/paste",
            json={"project_id": project2_id, "text": f"https://pub-{tag}.test/c\n"},
            headers=h,
        ).json()
        assert staged2["invalid"] == 1
        assert staged2.get("default_target") is None


def test_competitor_parents_grouping(live_stack):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        h = _register(client)
        proj = client.post("/api/v1/projects", json={"name": "Parents Proj"}, headers=h)
        assert proj.status_code == 201, proj.text
        project_id = proj.json()["id"]

        tag = uuid.uuid4().hex[:6]
        rival = f"rival-{tag}.com"

        # First upload: same competitor domain, name falls back to the domain.
        first = client.post(
            "/api/v1/competitors/ingest",
            json={
                "project_id": project_id,
                "competitor_url": f"https://{rival}",
                "name": "",
                "text": f"https://blog-{tag}.test/a\nhttps://blog-{tag}.test/b",
            },
            headers=h,
        )
        assert first.status_code == 201, first.text
        assert first.json()["total_rows"] == 2

        # Second upload: SAME competitor domain, now with a real name + new links.
        second = client.post(
            "/api/v1/competitors/ingest",
            json={
                "project_id": project_id,
                "competitor_url": f"https://{rival}",
                "name": "Rival Inc",
                "text": f"https://fresh-{tag}.test/1\nhttps://fresh-{tag}.test/2\nhttps://fresh-{tag}.test/3",
            },
            headers=h,
        )
        assert second.status_code == 201, second.text
        assert second.json()["total_rows"] == 3

        # Rolled up to exactly one parent for the domain.
        parents = client.get(
            "/api/v1/competitors/parents", params={"project_id": project_id}, headers=h
        ).json()
        mine = [p for p in parents if p["competitor"] == rival]
        assert len(mine) == 1
        parent = mine[0]
        assert parent["uploads"] == 2
        assert parent["display_name"] == "Rival Inc"
        assert parent["total_rows"] == 5

        # Parent backlinks span both uploads and carry the upload name.
        links = client.get(
            "/api/v1/competitors/parents/backlinks",
            params={"project_id": project_id, "competitor": rival},
            headers=h,
        )
        assert links.status_code == 200, links.text
        rows = links.json()
        assert len(rows) == 5
        assert all("upload_name" in r for r in rows)
        assert {r["upload_name"] for r in rows} == {rival, "Rival Inc"}

        # Search narrows across the parent's links.
        narrowed = client.get(
            "/api/v1/competitors/parents/backlinks",
            params={"project_id": project_id, "competitor": rival, "q": f"fresh-{tag}"},
            headers=h,
        ).json()
        assert len(narrowed) == 3
        assert all(f"fresh-{tag}" in r["url"] for r in narrowed)


def test_phase_contracts(live_stack):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        h = _register(client)

        perf = client.get(
            "/api/v1/performance/users", params={"days": 30, "compare": "false"}, headers=h
        )
        assert perf.status_code == 200, perf.text
        assert "users" in perf.json()

        bl = client.get(
            "/api/v1/backlinks", params={"status": "PASS", "limit": 5}, headers=h
        )
        assert bl.status_code == 200, bl.text
        assert "items" in bl.json()
