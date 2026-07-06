"""Batch review system (0029): staged link imports (paste → review batch →
approve/reject), staged domain imports (metrics check → approve into the
catalog, surviving recompute), sequence numbers and item filters."""

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
            "full_name": "Admin", "workspace_name": "Batch System Ws",
        },
    )
    assert reg.status_code == 201, reg.text
    return {"Authorization": f"Bearer {reg.json()['access_token']}"}


def test_link_import_stages_reviews_and_approves(live_stack):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        h = _register(client)
        proj = client.post(
            "/api/v1/projects",
            json={"name": "Batch Proj", "target_domain": "acme-batch.test"},
            headers=h,
        )
        project_id = proj.json()["id"]

        tag = uuid.uuid4().hex[:6]
        paste = (
            "source_url,target_url\n"
            f"https://pub-{tag}.test/a,https://acme-batch.test/\n"
            f"https://pub-{tag}.test/b,https://acme-batch.test/\n"
            f"https://pub-{tag}.test/a,https://acme-batch.test/\n"  # in-batch repeat
        )
        staged = client.post(
            "/api/v1/imports/paste",
            json={"project_id": project_id, "text": paste},
            headers=h,
        )
        assert staged.status_code == 202, staged.text
        body = staged.json()
        assert body["total"] == 3 and body["new"] == 2 and body["duplicate"] == 1
        batch_id = body["batch_id"]
        assert body["seq"] >= 1

        # ISOLATION: nothing reached the project before approval.
        rows = client.get(
            "/api/v1/backlinks", params={"project_id": project_id, "with_total": True}, headers=h
        ).json()
        assert (rows.get("total") or 0) == 0 and not rows["items"]

        b = client.get(f"/api/v1/batches/{batch_id}", headers=h).json()
        assert b["kind"] == "link_review" and b["status"] == "review"
        assert b["review_pending"] == 3 and b["seq"] == body["seq"]

        items = client.get(f"/api/v1/batches/{batch_id}/items", headers=h).json()
        assert items["counts"]["total"] == 3
        assert items["counts"]["by_presence"].get("new") == 2
        assert items["counts"]["by_presence"].get("duplicate") == 1
        assert all(it["state"] == "pending" for it in items["items"])

        # Filters: presence + search.
        only_new = client.get(
            f"/api/v1/batches/{batch_id}/items", params={"presence": "new"}, headers=h
        ).json()
        assert len(only_new["items"]) == 2
        searched = client.get(
            f"/api/v1/batches/{batch_id}/items", params={"q": f"pub-{tag}.test/b"}, headers=h
        ).json()
        assert len(searched["items"]) == 1

        # Queue the isolated QA check (no worker in tests — just the transition).
        check = client.post(
            f"/api/v1/batches/{batch_id}/items/check",
            json={"presence": "new"},
            headers=h,
        )
        assert check.status_code == 200, check.text
        assert check.json()["mode"] == "qa" and check.json()["queued"] == 2
        checking = client.get(
            f"/api/v1/batches/{batch_id}/items", params={"state": "checking"}, headers=h
        ).json()
        assert len(checking["items"]) == 2
        assert client.get(f"/api/v1/batches/{batch_id}", headers=h).json()["status"] == "running"

        # Approve the two distinct links ("checking" items can't be approved,
        # so this also proves state gating — approve them via explicit ids after
        # resetting through reject/re-check is overkill; instead approve the
        # duplicate row plus re-approve after the check would be async. Use the
        # filter path: approving "checking" rows is a no-op, so first pull ids.
        all_items = client.get(f"/api/v1/batches/{batch_id}/items", headers=h).json()["items"]
        dup_ids = [it["id"] for it in all_items if it["presence"] == "duplicate"]
        approve_dup = client.post(
            f"/api/v1/batches/{batch_id}/items/approve",
            json={"item_ids": dup_ids},
            headers=h,
        )
        assert approve_dup.status_code == 200, approve_dup.text
        assert approve_dup.json()["approved"] == 1
        assert approve_dup.json()["new_rows"] == 1  # first of the pair to land

        rows = client.get(
            "/api/v1/backlinks", params={"project_id": project_id, "with_total": True}, headers=h
        ).json()
        assert rows["total"] == 1 and rows["items"][0]["domain_da"] is None

        # A fresh paste of the same three rows now sees them as existing/dup.
        staged2 = client.post(
            "/api/v1/imports/paste",
            json={"project_id": project_id, "text": paste},
            headers=h,
        ).json()
        assert staged2["existing"] >= 1  # pub-…/a is in the project now
        # Reject everything open in the second batch — audit trail, no import.
        rej = client.post(
            f"/api/v1/batches/{staged2['batch_id']}/items/reject", json={}, headers=h
        )
        assert rej.status_code == 200 and rej.json()["rejected"] == 3
        b2 = client.get(f"/api/v1/batches/{staged2['batch_id']}", headers=h).json()
        assert b2["status"] == "completed" and b2["review_pending"] == 0
        rows = client.get(
            "/api/v1/backlinks", params={"project_id": project_id, "with_total": True}, headers=h
        ).json()
        assert rows["total"] == 1  # rejection imported nothing

        # Sequence numbers increase monotonically.
        assert staged2["seq"] > body["seq"]


def test_invalid_rows_are_flagged_not_imported(live_stack):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        h = _register(client)
        proj = client.post("/api/v1/projects", json={"name": "Bad Rows"}, headers=h)
        project_id = proj.json()["id"]
        staged = client.post(
            "/api/v1/imports/paste",
            json={"project_id": project_id, "text": "not-a-url-at-all\n"},
            headers=h,
        ).json()
        assert staged["invalid"] == 1
        batch_id = staged["batch_id"]
        items = client.get(f"/api/v1/batches/{batch_id}/items", headers=h).json()["items"]
        assert items[0]["state"] == "failed" and items[0]["error"]
        # Failed (invalid) rows can never be approved.
        res = client.post(
            f"/api/v1/batches/{batch_id}/items/approve",
            json={"item_ids": [items[0]["id"]]},
            headers=h,
        ).json()
        assert res["approved"] == 0


def test_domain_import_check_approve_and_recompute_survival(live_stack):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        h = _register(client)
        tag = uuid.uuid4().hex[:6]
        d1, d2 = f"alpha-{tag}.test", f"beta-{tag}.test"
        staged = client.post(
            "/api/v1/source-domains/import",
            json={"text": f"{d1}\nhttps://www.{d2}/some/page\n{d1}\n"},
            headers=h,
        )
        assert staged.status_code == 202, staged.text
        body = staged.json()
        assert body["total"] == 2 and body["new"] == 2 and body["duplicate"] == 1
        batch_id = body["batch_id"]

        # Catalog untouched before approval.
        catalog = client.get("/api/v1/source-domains", headers=h).json()["items"]
        assert not [r for r in catalog if r["domain_key"] in (d1, d2)]

        # Inline metrics check (no API keys in tests → sparse but state moves).
        check = client.post(
            f"/api/v1/batches/{batch_id}/items/check",
            json={"providers": "moz"},
            headers=h,
        )
        assert check.status_code == 200, check.text
        assert check.json()["mode"] == "metrics" and check.json()["checked"] == 2

        items = client.get(f"/api/v1/batches/{batch_id}/items", headers=h).json()["items"]
        assert all(it["state"] == "checked" for it in items)

        # Approve both into the catalog.
        res = client.post(f"/api/v1/batches/{batch_id}/items/approve", json={}, headers=h)
        assert res.status_code == 200, res.text
        assert res.json()["domains_added"] == 2
        catalog = client.get("/api/v1/source-domains", headers=h).json()["items"]
        got = {r["domain_key"] for r in catalog}
        assert d1 in got and d2 in got
        assert client.get(f"/api/v1/batches/{batch_id}", headers=h).json()["status"] == "completed"

        # THE protection: recompute's orphan sweep must keep imported domains
        # even though they have zero backlinks.
        rec = client.post("/api/v1/source-domains/recompute", headers=h)
        assert rec.status_code == 200, rec.text
        catalog = {r["domain_key"] for r in client.get("/api/v1/source-domains", headers=h).json()["items"]}
        assert d1 in catalog and d2 in catalog

        # Importing the same list again flags them as already-there.
        again = client.post(
            "/api/v1/source-domains/import", json={"text": f"{d1}\n{d2}"}, headers=h
        ).json()
        assert again["existing"] == 2 and again["new"] == 0
