"""Link-type merge/rename EXECUTION path (DB-backed).

The pure-normalizer tests can't catch SQL that only runs on a real merge —
the tab-constants statement 500'd every merge for weeks because `:new::text`
never binds (the text() cast gotcha). These tests drive the actual endpoints:
propose → preview → merge → alias resolution → rename.
"""

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
            "full_name": "QA Specialist", "workspace_name": "LT Merge Ws",
        },
    )
    assert reg.status_code == 201, reg.text
    return {"Authorization": f"Bearer {reg.json()['access_token']}"}


def test_merge_and_rename_execute_end_to_end(live_stack):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        h = _register(client)
        # Two spellings of the same thing.
        a = client.post("/api/v1/link-types", json={"name": "Business Listing"}, headers=h)
        b = client.post("/api/v1/link-types", json={"name": "Busniess Listing"}, headers=h)
        assert a.status_code == 201 and b.status_code == 201, (a.text, b.text)
        a_id, b_id = a.json()["id"], b.json()["id"]

        # The scanner groups them and suggests the well-spelled master.
        prop = client.get("/api/v1/link-types/merge-proposal", headers=h)
        assert prop.status_code == 200, prop.text
        groups = prop.json()["groups"]
        grp = next((g for g in groups if len(g["members"]) == 2), None)
        assert grp is not None, groups
        assert {m["id"] for m in grp["members"]} == {a_id, b_id}

        # Dry-run preview never mutates.
        prev = client.get(
            f"/api/v1/link-types/{b_id}/merge-preview", params={"winner_id": a_id}, headers=h
        )
        assert prev.status_code == 200, prev.text
        assert "will_update" in prev.json()

        # THE actual merge — this is the statement path that used to 500.
        merged = client.post(
            f"/api/v1/link-types/{b_id}/merge",
            json={"winner_id": a_id, "rename_tabs": False},
            headers=h,
        )
        assert merged.status_code == 200, merged.text
        body = merged.json()
        assert body["merged"]["id"] == b_id and body["into"]["id"] == a_id

        # The alias layer folds the misspelling back into the master forever:
        # re-creating the merged name must resolve to the surviving type.
        again = client.post("/api/v1/link-types", json={"name": "Busniess Listing"}, headers=h)
        assert again.status_code in (200, 201), again.text
        assert again.json()["id"] == a_id, again.json()

        # Rename-everywhere is the same rewrite machinery — must also succeed.
        renamed = client.post(
            f"/api/v1/link-types/{a_id}/rename",
            json={"name": "Business Listings", "rename_tabs": False},
            headers=h,
        )
        assert renamed.status_code == 200, renamed.text
        assert renamed.json()["renamed"]["to"] == "Business Listings"

        # The catalog shows one active master with the new spelling.
        lst = client.get("/api/v1/link-types", headers=h)
        names = [t["name"] for t in lst.json()]
        assert "Business Listings" in names
        assert "Busniess Listing" not in names
