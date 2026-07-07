"""Batch delete/rollback + QA execution settings + never-empty logs (Tranche G).

Rollback correctness is the risky part, so these prove the exact contract:
* revert deletes ONLY the links a batch created (import_id set on insert),
* links a later batch merely refreshed are preserved,
* unrelated projects are never touched,
* domain-import revert removes catalog-only rows but keeps in-use domains,
* plain delete (revert=false) keeps all approved data,
* QA settings clamp + persist, and logs are never empty.
"""

from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.integration


def _register(client, ws="Rollback Ws"):
    email = f"qa+{uuid.uuid4().hex[:8]}@linksentinel.test"
    reg = client.post(
        "/api/v1/auth/register",
        json={
            "email": email, "password": "Password-12345",
            "full_name": "Admin", "workspace_name": ws,
        },
    )
    assert reg.status_code == 201, reg.text
    return {"Authorization": f"Bearer {reg.json()['access_token']}"}


def _project(client, h, name, domain):
    r = client.post("/api/v1/projects", json={"name": name, "target_domain": domain}, headers=h)
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def _stage_and_approve(client, h, project_id, paste, *, item_ids=None):
    staged = client.post(
        "/api/v1/imports/paste", json={"project_id": project_id, "text": paste}, headers=h
    )
    assert staged.status_code == 202, staged.text
    batch_id = staged.json()["batch_id"]
    body = {"item_ids": item_ids} if item_ids else {}
    appr = client.post(f"/api/v1/batches/{batch_id}/items/approve", json=body, headers=h)
    assert appr.status_code == 200, appr.text
    return batch_id, staged.json(), appr.json()


def _count(client, h, project_id):
    return client.get(
        "/api/v1/backlinks", params={"project_id": project_id, "with_total": True}, headers=h
    ).json().get("total") or 0


def test_revert_deletes_created_keeps_refreshed_and_isolates(live_stack):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        h = _register(client)
        p1 = _project(client, h, "P1", "acme-rb.test")
        p2 = _project(client, h, "P2", "other-rb.test")

        tag = uuid.uuid4().hex[:6]
        pasteA = (
            "source_url,target_url\n"
            f"https://s-{tag}.test/a,https://acme-rb.test/\n"
            f"https://s-{tag}.test/b,https://acme-rb.test/\n"
        )
        # Unrelated project's data — must survive every revert below.
        _stage_and_approve(client, h, p2, f"source_url,target_url\nhttps://x-{tag}.test/z,https://other-rb.test/\n")
        assert _count(client, h, p2) == 1

        batchA, _, apprA = _stage_and_approve(client, h, p1, pasteA)
        assert apprA["new_rows"] == 2
        assert _count(client, h, p1) == 2

        # Batch B: one brand-new link → 1 created row (import_id = impB).
        batchB, _, apprB = _stage_and_approve(
            client, h, p1, f"source_url,target_url\nhttps://s-{tag}.test/c,https://acme-rb.test/\n"
        )
        assert apprB["new_rows"] == 1
        assert _count(client, h, p1) == 3

        # Batch C: re-approve the two A links → they are REFRESHED (updated),
        # keeping their original import_id (impA), so B/C revert must not touch them.
        batchC, _, apprC = _stage_and_approve(client, h, p1, pasteA)
        assert apprC.get("updated_rows", 0) == 2 and apprC.get("new_rows", 0) == 0
        assert _count(client, h, p1) == 3

        # Preview: C created nothing, refreshed two.
        prevC = client.get(f"/api/v1/batches/{batchC}/rollback-preview", headers=h).json()
        assert prevC["created_links"] == 0 and prevC["refreshed_kept"] == 2 and prevC["revertable"]

        # Revert C → deletes nothing (it only refreshed); the 3 links stay.
        dC = client.delete(f"/api/v1/batches/{batchC}", params={"revert": True}, headers=h)
        assert dC.status_code == 200 and dC.json()["reverted_links"] == 0
        assert _count(client, h, p1) == 3

        # Revert B → deletes ONLY the 1 link it created.
        prevB = client.get(f"/api/v1/batches/{batchB}/rollback-preview", headers=h).json()
        assert prevB["created_links"] == 1
        dB = client.delete(f"/api/v1/batches/{batchB}", params={"revert": True}, headers=h)
        assert dB.status_code == 200 and dB.json()["reverted_links"] == 1
        assert _count(client, h, p1) == 2

        # Revert A → deletes the two it created. Project empty.
        dA = client.delete(f"/api/v1/batches/{batchA}", params={"revert": True}, headers=h)
        assert dA.status_code == 200 and dA.json()["reverted_links"] == 2
        assert _count(client, h, p1) == 0

        # Unrelated project untouched throughout.
        assert _count(client, h, p2) == 1
        # The deleted batch is gone from history.
        assert client.get(f"/api/v1/batches/{batchA}", headers=h).status_code == 404


def test_plain_delete_keeps_data(live_stack):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        h = _register(client)
        pid = _project(client, h, "Keep", "keep-rb.test")
        tag = uuid.uuid4().hex[:6]
        batch, _, _ = _stage_and_approve(
            client, h, pid, f"source_url,target_url\nhttps://k-{tag}.test/a,https://keep-rb.test/\n"
        )
        assert _count(client, h, pid) == 1
        # revert defaults to False → housekeeping only.
        d = client.delete(f"/api/v1/batches/{batch}", headers=h)
        assert d.status_code == 200 and d.json()["reverted"] is False
        assert _count(client, h, pid) == 1  # data stays


def test_domain_revert_removes_catalog_only_keeps_in_use(live_stack):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        h = _register(client)
        pid = _project(client, h, "Dom", "dom-rb.test")
        tag = uuid.uuid4().hex[:6]
        catalog = f"catalog-{tag}.test"
        inuse = f"inuse-{tag}.test"

        # Put a real link on `inuse` so its source domain is in use.
        _stage_and_approve(
            client, h, pid, f"source_url,target_url\nhttps://{inuse}/p,https://dom-rb.test/\n"
        )

        # Domain-import both: one catalog-only, one already in use.
        staged = client.post(
            "/api/v1/source-domains/import", json={"text": f"{catalog}\n{inuse}\n"}, headers=h
        )
        assert staged.status_code == 202, staged.text
        bid = staged.json()["batch_id"]
        appr = client.post(f"/api/v1/batches/{bid}/items/approve", json={}, headers=h)
        assert appr.status_code == 200, appr.text

        prev = client.get(f"/api/v1/batches/{bid}/rollback-preview", headers=h).json()
        # catalog-only is removable; the in-use one is kept.
        assert prev["domains_removable"] == 1 and prev["domains_kept"] == 1

        d = client.delete(f"/api/v1/batches/{bid}", params={"revert": True}, headers=h)
        assert d.status_code == 200
        assert d.json()["reverted_domains"] == 1 and d.json()["kept_domains"] == 1

        # The in-use domain and its link remain.
        assert _count(client, h, pid) == 1


def test_qa_settings_roundtrip_and_clamp(live_stack):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        h = _register(client)
        got = client.get("/api/v1/qa-settings", headers=h)
        assert got.status_code == 200, got.text
        base = got.json()
        assert "effective" in base and "meta" in base
        assert base["meta"]["chunk_size"]["overridden"] is False

        # Set valid + out-of-range values → clamped, persisted, marked overridden.
        put = client.put(
            "/api/v1/qa-settings",
            json={"overrides": {"chunk_size": 25, "total_timeout": 99999, "render_enabled": True,
                                "render_wait_until": "load", "read_timeout": -5}},
            headers=h,
        )
        assert put.status_code == 200, put.text
        eff = put.json()["effective"]
        assert eff["chunk_size"] == 25
        assert eff["total_timeout"] == 600  # clamped to max
        assert eff["read_timeout"] == 1     # clamped to min
        assert eff["render_enabled"] is True
        assert eff["render_wait_until"] == "load"
        assert put.json()["meta"]["chunk_size"]["overridden"] is True

        # Persisted across a fresh GET.
        again = client.get("/api/v1/qa-settings", headers=h).json()
        assert again["effective"]["chunk_size"] == 25

        # Clearing a knob (null) reverts it to the config default.
        default_chunk = again["meta"]["chunk_size"]["default"]
        cleared = client.put(
            "/api/v1/qa-settings", json={"overrides": {"chunk_size": None}}, headers=h
        ).json()
        assert cleared["effective"]["chunk_size"] == default_chunk
        assert cleared["meta"]["chunk_size"]["overridden"] is False


def test_revert_recomputes_surviving_conflict_group(live_stack):
    """The HIGH finding: reverting a batch must recompute (not leave stale) the
    conflict groups its links belonged to."""
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        h = _register(client)
        tag = uuid.uuid4().hex[:6]
        src = f"https://shared-{tag}.test/page"  # one page linking to 3 projects
        projects = []
        batches = []
        for i in range(3):
            pid = _project(client, h, f"CG{i}", f"cg{i}-{tag}.test")
            projects.append(pid)
            bid, _, _ = _stage_and_approve(
                client, h, pid, f"source_url,target_url\n{src},https://cg{i}-{tag}.test/\n"
            )
            batches.append(bid)

        summ = client.get("/api/v1/conflicts/summary", headers=h).json()
        assert summ["total"] == 1 and summ["total_duplicate_links"] == 2  # 3 members

        # Revert the 3rd batch → its link goes; the group SURVIVES with 2 members
        # and its aggregates must be refreshed (not stale at 3).
        d = client.delete(f"/api/v1/batches/{batches[2]}", params={"revert": True}, headers=h)
        assert d.status_code == 200 and d.json()["reverted_links"] == 1

        summ2 = client.get("/api/v1/conflicts/summary", headers=h).json()
        assert summ2["total"] == 1 and summ2["total_duplicate_links"] == 1  # now 2 members
        groups = client.get("/api/v1/conflicts", headers=h).json()["items"]
        assert groups and groups[0]["member_count"] == 2

        # Revert another → group collapses (a group of 1 is no duplicate).
        d2 = client.delete(f"/api/v1/batches/{batches[1]}", params={"revert": True}, headers=h)
        assert d2.status_code == 200
        summ3 = client.get("/api/v1/conflicts/summary", headers=h).json()
        assert summ3["total"] == 0


def test_revert_blocked_while_check_running(live_stack):
    """The MEDIUM finding: a batch mid-QA must not be revertible (race guard)."""
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        h = _register(client)
        pid = _project(client, h, "Run", "run-rb.test")
        tag = uuid.uuid4().hex[:6]
        staged = client.post(
            "/api/v1/imports/paste",
            json={"project_id": pid, "text": f"source_url,target_url\nhttps://r-{tag}.test/a,https://run-rb.test/\n"},
            headers=h,
        )
        bid = staged.json()["batch_id"]
        # Begin the QA check → batch flips to "running" (no worker in tests).
        chk = client.post(f"/api/v1/batches/{bid}/items/check", json={"presence": "new"}, headers=h)
        assert chk.status_code == 200
        assert client.get(f"/api/v1/batches/{bid}", headers=h).json()["status"] == "running"
        # Revert must be refused while running.
        d = client.delete(f"/api/v1/batches/{bid}", params={"revert": True}, headers=h)
        assert d.status_code == 422, d.text
        # Batch still exists.
        assert client.get(f"/api/v1/batches/{bid}", headers=h).status_code == 200


def test_batch_logs_never_empty(live_stack):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        h = _register(client)
        pid = _project(client, h, "Logs", "logs-rb.test")
        tag = uuid.uuid4().hex[:6]
        staged = client.post(
            "/api/v1/imports/paste",
            json={"project_id": pid, "text": f"source_url,target_url\nhttps://l-{tag}.test/a,https://logs-rb.test/\n"},
            headers=h,
        )
        bid = staged.json()["batch_id"]
        logs = client.get(f"/api/v1/batches/{bid}/logs", headers=h).json()
        assert len(logs) >= 1 and logs[0]["message"]  # staged line, never empty
