"""Duplicate management enterprise (0034): pure comparison helpers
(field_matrix / similarity_score / duplicate_reason), the conflict list/detail
views with enriched members + field matrix + suggested keep, the expanded
whitelist filters, bulk / keep-one resolution actions with the audit trail, and
the summary rollup.

The integration tests seed a real conflict by staging + approving two paste-
imported links that share ONE source page (different targets) so they group under
one canonical → one conflict of member_count 2, then drive the real routers via
TestClient (rebuild / recompute run inline — no worker needed)."""

from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.integration


# ── 1. PURE helpers (no DB, no network) ──────────────────────────────────────

def test_field_matrix_all_same_and_distinct():
    from app.services import conflict_service as cs

    # Two members: identical everything except target + anchor.
    m1 = {
        "source_domain": "pub.test",
        "target_url_normalized": "https://acme.test/a",
        "target_domain": "acme.test",
        "current_anchor_text": "buy now",
        "current_rel": "follow",
        "project_id": "11111111-1111-1111-1111-111111111111",
        "assigned_user_label": "alex",
        "link_type": "guest_post",
    }
    m2 = dict(m1)
    m2["target_url_normalized"] = "https://acme.test/b"
    m2["current_anchor_text"] = "click here"

    matrix = cs.field_matrix([m1, m2])
    by_field = {r["field"] for r in matrix}
    assert {"source_domain", "target_url_normalized", "anchor", "rel", "project_id",
            "assigned_user_label", "link_type"} <= by_field

    idx = {r["field"]: r for r in matrix}
    # Shared → all_same, distinct 1.
    assert idx["source_domain"]["all_same"] is True and idx["source_domain"]["distinct"] == 1
    assert idx["rel"]["all_same"] is True
    assert idx["project_id"]["all_same"] is True
    # Differing → not all_same, distinct 2, sampled values present.
    assert idx["target_url_normalized"]["all_same"] is False
    assert idx["target_url_normalized"]["distinct"] == 2
    assert set(idx["target_url_normalized"]["values"]) == {
        "https://acme.test/a", "https://acme.test/b"
    }
    assert idx["anchor"]["all_same"] is False and idx["anchor"]["distinct"] == 2


def test_similarity_score_identical_is_100_and_drops_on_differences():
    from app.services import conflict_service as cs

    base = {
        "source_domain": "pub.test",
        "target_url_normalized": "https://acme.test/a",
        "target_domain": "acme.test",
        "current_anchor_text": "buy now",
        "current_rel": "follow",
        "project_id": "11111111-1111-1111-1111-111111111111",
        "assigned_user_label": "alex",
        "link_type": "guest_post",
    }
    identical = cs.similarity_score(cs.field_matrix([dict(base), dict(base)]))
    assert identical == 100

    differ = dict(base)
    differ["target_url_normalized"] = "https://acme.test/b"
    differ["current_anchor_text"] = "click here"
    lower = cs.similarity_score(cs.field_matrix([dict(base), differ]))
    assert 0 <= lower < identical

    # Three members with a spread → still bounded and no higher than identical.
    third = dict(base)
    third["assigned_user_label"] = "sam"
    three = cs.similarity_score(cs.field_matrix([dict(base), differ, third]))
    assert 0 <= three <= 100 and three <= identical


def test_duplicate_reason_is_a_nonempty_sentence():
    from app.services import conflict_service as cs

    base = {
        "source_domain": "pub.test",
        "target_url_normalized": "https://acme.test/a",
        "current_anchor_text": "buy now",
        "current_rel": "follow",
        "project_id": "11111111-1111-1111-1111-111111111111",
        "assigned_user_label": "alex",
        "link_type": "guest_post",
    }
    differ = dict(base)
    differ["target_url_normalized"] = "https://acme.test/b"
    matrix = cs.field_matrix([base, differ])

    reason = cs.duplicate_reason(cs.SAME_PROJECT, matrix, 2)
    assert isinstance(reason, str) and reason.strip()
    assert reason.endswith(".")
    assert "2" in reason
    # A differing field is called out.
    assert "target URL" in reason

    # Identical members → "otherwise identical" tail, still a full sentence.
    same_reason = cs.duplicate_reason(cs.SAME_PROJECT, cs.field_matrix([base, dict(base)]), 2)
    assert same_reason.strip() and same_reason.endswith(".")


# ── Integration harness (mirrors test_batch_system.py) ───────────────────────

def _register(client):
    email = f"qa+{uuid.uuid4().hex[:8]}@linksentinel.test"
    reg = client.post(
        "/api/v1/auth/register",
        json={
            "email": email, "password": "Password-12345",
            "full_name": "Admin", "workspace_name": "Duplicates Ent Ws",
        },
    )
    assert reg.status_code == 201, reg.text
    return {"Authorization": f"Bearer {reg.json()['access_token']}"}


def _seed_two_backlink_conflict(client, h, project_id, target_domain):
    """Stage + approve two paste rows sharing ONE source page (different targets)
    → two backlinks under one canonical → one conflict of member_count 2. Returns
    the source URL used (for search assertions)."""
    tag = uuid.uuid4().hex[:6]
    source = f"https://dup-{tag}.test/post"
    paste = (
        "source_url,target_url\n"
        f"{source},https://{target_domain}/a\n"
        f"{source},https://{target_domain}/b\n"
    )
    staged = client.post(
        "/api/v1/imports/paste",
        json={"project_id": project_id, "text": paste},
        headers=h,
    )
    assert staged.status_code == 202, staged.text
    body = staged.json()
    # Same source, DIFFERENT targets → two distinct NEW rows (not a duplicate).
    assert body["total"] == 2 and body["new"] == 2, body
    batch_id = body["batch_id"]

    # Approve both (pending items approve directly; no QA needed to import).
    approve = client.post(
        f"/api/v1/batches/{batch_id}/items/approve", json={}, headers=h
    )
    assert approve.status_code == 200, approve.text
    assert approve.json()["new_rows"] == 2, approve.json()

    rows = client.get(
        "/api/v1/backlinks",
        params={"project_id": project_id, "with_total": True}, headers=h,
    ).json()
    assert rows["total"] == 2, rows
    return source


# ── 2. Seed a duplicate → rebuild → list → detail ────────────────────────────

def test_conflict_rebuild_list_and_detail(live_stack):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        h = _register(client)
        td = f"acme-{uuid.uuid4().hex[:6]}.test"
        proj = client.post(
            "/api/v1/projects", json={"name": "Dup Proj", "target_domain": td}, headers=h
        )
        project_id = proj.json()["id"]
        source = _seed_two_backlink_conflict(client, h, project_id, td)

        # Rebuild the workspace conflict groups (runs inline).
        rb = client.post("/api/v1/conflicts/rebuild", headers=h)
        assert rb.status_code == 200, rb.text
        assert rb.json()["total"] >= 1

        listed = client.get("/api/v1/conflicts", headers=h)
        assert listed.status_code == 200, listed.text
        body = listed.json()
        assert body["total"] >= 1 and body["items"]
        group = next(g for g in body["items"] if g["member_count"] == 2)
        conflict_id = group["id"]
        assert group["similarity"] is not None and 0 <= group["similarity"] <= 100
        assert group["reason"] and isinstance(group["reason"], str)
        assert group["resolution_status"] == "open"

        detail = client.get(f"/api/v1/conflicts/{conflict_id}", headers=h)
        assert detail.status_code == 200, detail.text
        d = detail.json()
        assert d["member_count"] == 2 and len(d["members"]) == 2
        # Members are enriched (target/anchor/rel fields present in the schema).
        assert all("target_url_normalized" in m for m in d["members"])
        assert d["field_matrix"] and any(r["field"] == "target_url_normalized"
                                         for r in d["field_matrix"])
        # target URL differs across the two members → not all_same in the matrix.
        tgt_row = next(r for r in d["field_matrix"] if r["field"] == "target_url_normalized")
        assert tgt_row["all_same"] is False
        assert d["suggested_keep"] is not None
        member_ids = {m["backlink_id"] for m in d["members"]}
        assert d["suggested_keep"] in member_ids
        assert source  # sanity: the seed source URL is defined


# ── 3. Filters ───────────────────────────────────────────────────────────────

def test_conflict_list_filters(live_stack):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        h = _register(client)
        td = f"acme-{uuid.uuid4().hex[:6]}.test"
        proj = client.post(
            "/api/v1/projects", json={"name": "Filter Proj", "target_domain": td}, headers=h
        )
        project_id = proj.json()["id"]
        _seed_two_backlink_conflict(client, h, project_id, td)
        assert client.post("/api/v1/conflicts/rebuild", headers=h).status_code == 200

        # min_members=2 → the 2-member group is present.
        keep = client.get("/api/v1/conflicts", params={"min_members": 2}, headers=h).json()
        assert any(g["member_count"] == 2 for g in keep["items"])

        # min_members=3 → the 2-member group is excluded.
        excl = client.get("/api/v1/conflicts", params={"min_members": 3}, headers=h).json()
        assert all(g["member_count"] >= 3 for g in excl["items"])
        assert not any(g["member_count"] == 2 for g in excl["items"])

        # scope filter is accepted (whitelisted) and returns 200.
        scoped = client.get(
            "/api/v1/conflicts", params={"scope": "same_project"}, headers=h
        )
        assert scoped.status_code == 200, scoped.text
        assert all(g["scope"] == "same_project" for g in scoped.json()["items"])


# ── 4. Bulk / actions (keep-one + bulk acknowledge) ──────────────────────────

def test_keep_one_deletes_other_member_and_collapses_group(live_stack):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        h = _register(client)
        td = f"acme-{uuid.uuid4().hex[:6]}.test"
        proj = client.post(
            "/api/v1/projects", json={"name": "KeepOne Proj", "target_domain": td}, headers=h
        )
        project_id = proj.json()["id"]
        _seed_two_backlink_conflict(client, h, project_id, td)
        assert client.post("/api/v1/conflicts/rebuild", headers=h).status_code == 200

        listed = client.get("/api/v1/conflicts", headers=h).json()
        group = next(g for g in listed["items"] if g["member_count"] == 2)
        conflict_id = group["id"]
        detail = client.get(f"/api/v1/conflicts/{conflict_id}", headers=h).json()
        member_ids = [m["backlink_id"] for m in detail["members"]]
        keep_id, other_id = member_ids[0], member_ids[1]

        ko = client.post(
            f"/api/v1/conflicts/{conflict_id}/keep-one",
            json={"keep_backlink_id": keep_id},
            headers=h,
        )
        assert ko.status_code == 200, ko.text
        assert ko.json()["deleted_count"] == 1

        # The OTHER member is gone; backlink count dropped from 2 → 1.
        rows = client.get(
            "/api/v1/backlinks",
            params={"project_id": project_id, "with_total": True}, headers=h,
        ).json()
        assert rows["total"] == 1
        remaining = {r["id"] for r in rows["items"]}
        assert keep_id in remaining and other_id not in remaining

        # The group collapsed (< 2 members) → gone from the list.
        after = client.get("/api/v1/conflicts", headers=h).json()
        assert not any(g["id"] == conflict_id for g in after["items"])

        # The keep_one action is on the audit trail.
        actions = client.get(f"/api/v1/conflicts/{conflict_id}/actions", headers=h)
        assert actions.status_code == 200, actions.text
        assert any(a["action"] == "keep_one" for a in actions.json())


def test_bulk_acknowledge_changes_status(live_stack):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        h = _register(client)
        td = f"acme-{uuid.uuid4().hex[:6]}.test"
        proj = client.post(
            "/api/v1/projects", json={"name": "Bulk Proj", "target_domain": td}, headers=h
        )
        project_id = proj.json()["id"]
        _seed_two_backlink_conflict(client, h, project_id, td)
        assert client.post("/api/v1/conflicts/rebuild", headers=h).status_code == 200

        group = next(
            g for g in client.get("/api/v1/conflicts", headers=h).json()["items"]
            if g["member_count"] == 2
        )
        conflict_id = group["id"]
        assert group["resolution_status"] == "open"

        bulk = client.post(
            "/api/v1/conflicts/bulk",
            json={"conflict_ids": [conflict_id], "action": "acknowledge"},
            headers=h,
        )
        assert bulk.status_code == 200, bulk.text
        assert bulk.json()["updated"] == 1

        after = client.get(f"/api/v1/conflicts/{conflict_id}", headers=h).json()
        assert after["resolution_status"] == "acknowledged"


# ── 5. Summary ───────────────────────────────────────────────────────────────

def test_conflict_summary_shape(live_stack):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        h = _register(client)
        td = f"acme-{uuid.uuid4().hex[:6]}.test"
        proj = client.post(
            "/api/v1/projects", json={"name": "Summary Proj", "target_domain": td}, headers=h
        )
        project_id = proj.json()["id"]
        _seed_two_backlink_conflict(client, h, project_id, td)
        assert client.post("/api/v1/conflicts/rebuild", headers=h).status_code == 200

        summ = client.get("/api/v1/conflicts/summary", headers=h)
        assert summ.status_code == 200, summ.text
        s = summ.json()
        assert "by_status" in s and isinstance(s["by_status"], dict)
        assert s["by_status"].get("open", 0) >= 1
        # avg_similarity present (may be None only if no similarity stored; we have one).
        assert "avg_similarity" in s and s["avg_similarity"] is not None
        # One 2-member group → at least one redundant link.
        assert s["total_duplicate_links"] >= 1
        assert s["total"] >= 1
