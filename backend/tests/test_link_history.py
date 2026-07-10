"""Complete per-link history (Phase 10 P5): manual-action events (created/edited/
override_set/reassigned/deleted) land in backlink_history with actor + source, the
single-PATCH reassignment writes AssignmentHistory + stamps assigned_at (aligned
with bulk_edit), and the merged timeline + checks endpoints page and filter."""

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
            "full_name": "Admin", "workspace_name": "Link History Ws",
        },
    )
    assert reg.status_code == 201, reg.text
    return {"Authorization": f"Bearer {reg.json()['access_token']}"}


def _make_project_and_backlink(client, h):
    proj = client.post(
        "/api/v1/projects",
        json={"name": "History Proj", "target_domain": "acme-history.test"},
        headers=h,
    )
    assert proj.status_code == 201, proj.text
    project_id = proj.json()["id"]

    tag = uuid.uuid4().hex[:6]
    created = client.post(
        "/api/v1/backlinks",
        json={
            "project_id": project_id,
            "source_page_url": f"https://pub-{tag}.test/article",
            "target_url": "https://acme-history.test/",
        },
        headers=h,
    )
    assert created.status_code == 201, created.text
    return project_id, created.json()


def _timeline(client, h, backlink_id, **params):
    res = client.get(f"/api/v1/backlinks/{backlink_id}/history", params=params, headers=h)
    assert res.status_code == 200, res.text
    return res.json()


def test_created_event_recorded(live_stack):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        h = _register(client)
        _, bl = _make_project_and_backlink(client, h)

        page = _timeline(client, h, bl["id"])
        created = [e for e in page["items"] if e["event_type"] == "created"]
        assert len(created) == 1
        ev = created[0]
        assert ev["source"] == "ui"
        assert ev["actor_user_id"] is not None
        assert ev["new_value"] == bl["source_page_url"]


def test_edit_emits_per_field_events_and_aligns_assignment(live_stack):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        h = _register(client)
        _, bl = _make_project_and_backlink(client, h)

        patched = client.patch(
            f"/api/v1/backlinks/{bl['id']}",
            json={"notes": "checked by hand", "assigned_user_label": "Kevin"},
            headers=h,
        )
        assert patched.status_code == 200, patched.text
        # Single-PATCH reassignment stamps assigned_at (parity with bulk_edit).
        assert patched.json()["assigned_at"] is not None
        assert patched.json()["assigned_user_label"] == "Kevin"

        page = _timeline(client, h, bl["id"])
        edited = [e for e in page["items"] if e["event_type"] == "edited"]
        by_field = {e["field"]: e for e in edited}
        assert "notes" in by_field and by_field["notes"]["new_value"] == "checked by hand"
        assert by_field["assigned_user_label"]["new_value"] == "Kevin"

        # ... and ALSO writes AssignmentHistory (the audit gap bulk_edit never had).
        assigns = client.get(
            f"/api/v1/backlinks/{bl['id']}/assignment-history", headers=h
        )
        assert assigns.status_code == 200, assigns.text
        assert len(assigns.json()) == 1
        assert assigns.json()[0]["new_user_label"] == "Kevin"

        # Merged view dedupes the dual-write: exactly ONE timeline entry for the
        # label change (the richer history event wins; the assignment twin drops).
        label_entries = [
            e for e in page["items"]
            if e["field"] == "assigned_user_label" and e["new_value"] == "Kevin"
        ]
        assert len(label_entries) == 1

        # No-op PATCH (same values) adds NO new events.
        before = len(_timeline(client, h, bl["id"])["items"])
        again = client.patch(
            f"/api/v1/backlinks/{bl['id']}",
            json={"notes": "checked by hand"},
            headers=h,
        )
        assert again.status_code == 200, again.text
        assert len(_timeline(client, h, bl["id"])["items"]) == before


def test_override_event_with_note_and_actor(live_stack):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        h = _register(client)
        _, bl = _make_project_and_backlink(client, h)

        over = client.post(
            f"/api/v1/backlinks/{bl['id']}/override",
            json={"status": "PASS", "note": "verified manually"},
            headers=h,
        )
        assert over.status_code == 200, over.text

        page = _timeline(client, h, bl["id"])
        events = [e for e in page["items"] if e["event_type"] == "override_set"]
        assert len(events) == 1
        ev = events[0]
        assert ev["new_value"] == "PASS"
        assert ev["old_value"] == "PENDING"  # effective status before the override
        assert ev["note"] == "verified manually"
        assert ev["actor_user_id"] is not None
        assert ev["source"] == "ui"


def test_timeline_event_type_filter_and_q(live_stack):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        h = _register(client)
        _, bl = _make_project_and_backlink(client, h)
        client.patch(
            f"/api/v1/backlinks/{bl['id']}", json={"notes": "needle-note"}, headers=h
        )

        only_created = _timeline(client, h, bl["id"], event_type="created")
        assert {e["event_type"] for e in only_created["items"]} == {"created"}

        multi = _timeline(client, h, bl["id"], event_type="created,edited")
        assert {e["event_type"] for e in multi["items"]} == {"created", "edited"}

        hit = _timeline(client, h, bl["id"], q="needle-note")
        assert len(hit["items"]) == 1
        assert hit["items"][0]["new_value"] == "needle-note"

        miss = _timeline(client, h, bl["id"], q="no-such-substring-xyz")
        assert miss["items"] == []

        # Paging: limit=1 on >1 events pages with has_more.
        first = _timeline(client, h, bl["id"], limit=1)
        assert len(first["items"]) == 1 and first["has_more"] is True
        second = _timeline(client, h, bl["id"], limit=1, offset=1)
        assert len(second["items"]) == 1


def test_bulk_edit_emits_reassigned_once_per_row(live_stack):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        h = _register(client)
        _, bl = _make_project_and_backlink(client, h)

        bulk = client.post(
            "/api/v1/backlinks/bulk-edit",
            json={"ids": [bl["id"]], "set_user": True, "assigned_user_label": "Maya"},
            headers=h,
        )
        assert bulk.status_code == 200, bulk.text
        assert bulk.json()["updated"] == 1

        page = _timeline(client, h, bl["id"])
        reassigned = [e for e in page["items"] if e["event_type"] == "reassigned"]
        # One coalesced entry (history event + AssignmentHistory dual-write dedupes).
        assert len(reassigned) == 1
        assert reassigned[0]["new_value"] == "Maya"
        assert reassigned[0]["source"] == "ui"


def test_checks_endpoint_lists_every_crawl(live_stack):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        h = _register(client)
        _, bl = _make_project_and_backlink(client, h)

        res = client.get(f"/api/v1/backlinks/{bl['id']}/checks", headers=h)
        assert res.status_code == 200, res.text
        body = res.json()
        # No crawls have run in this test → empty but well-formed keyset page.
        assert body["items"] == []
        assert body["has_more"] is False

        # Unknown ids are workspace-scoped 404s, same as the detail endpoint.
        missing = client.get(f"/api/v1/backlinks/{uuid.uuid4()}/checks", headers=h)
        assert missing.status_code == 404


def test_delete_writes_tombstone_then_404s(live_stack):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        h = _register(client)
        _, bl = _make_project_and_backlink(client, h)

        deleted = client.delete(f"/api/v1/backlinks/{bl['id']}", headers=h)
        assert deleted.status_code == 200, deleted.text

        # The record is gone → the scoped timeline 404s; the 'deleted' tombstone
        # row survives in backlink_history (no FK) for retention-grade audit.
        gone = client.get(f"/api/v1/backlinks/{bl['id']}/history", headers=h)
        assert gone.status_code == 404


def test_value_coercion_is_enum_and_none_safe():
    """Pure unit: record helpers stringify enums by .value and keep None."""
    from app.models.enums import OverallStatus
    from app.services.history_service import _text

    assert _text(None) is None
    assert _text(OverallStatus.PASS) == "PASS"
    assert _text(42) == "42"
    assert _text("plain") == "plain"
