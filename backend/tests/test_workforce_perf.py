"""Workforce + performance gap-closure tests (Phase 9 finalization).

Covers the owner-brief items added after the audit: custom compare windows on
the performance endpoint, per-user productivity overrides (set + remove),
member→project scoping round-trip, and sheet-label auto-provisioning of user
accounts (Viewer role, project-scoped, idempotent).
"""

from __future__ import annotations

import asyncio
import uuid

import pytest

pytestmark = pytest.mark.integration


def test_perf_compare_overrides_member_projects_and_auto_provision(live_stack):
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
                "workspace_name": "Workforce Perf Ws",
            },
        )
        assert reg.status_code == 201, reg.text
        headers = {"Authorization": f"Bearer {reg.json()['access_token']}"}

        proj = client.post("/api/v1/projects", json={"name": "Perf Proj"}, headers=headers)
        assert proj.status_code == 201, proj.text
        project_id = proj.json()["id"]

        # 1) Performance: custom window + CUSTOM compare window round-trips.
        r = client.get(
            "/api/v1/performance/users",
            params={
                "date_from": "2026-01-01T00:00:00Z",
                "date_to": "2026-02-01T00:00:00Z",
                "compare_from": "2025-11-01T00:00:00Z",
                "compare_to": "2025-12-01T00:00:00Z",
            },
            headers=headers,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["compare_from"].startswith("2025-11-01")
        assert body["compare_to"].startswith("2025-12-01")

        # 2) Per-user productivity override: set → listed → removed.
        put = client.put(
            "/api/v1/workforce/productivity",
            json={"link_type_name": "Profile", "links_per_hour": 30, "user_label": "alex"},
            headers=headers,
        )
        assert put.status_code == 200, put.text
        got = client.get("/api/v1/workforce/productivity", headers=headers).json()
        assert any(
            o["user_label"] == "alex" and o["link_type_name"] == "Profile"
            for o in got["overrides"]
        )
        dl = client.delete(
            "/api/v1/workforce/productivity",
            params={"user_label": "alex", "link_type_name": "Profile"},
            headers=headers,
        )
        assert dl.status_code == 200, dl.text
        got = client.get("/api/v1/workforce/productivity", headers=headers).json()
        assert not any(o["user_label"] == "alex" for o in got["overrides"])

        # 3) Member→project scoping: replace-set round-trip, foreign project rejected.
        inv = client.post(
            "/api/v1/team/members",
            json={
                "email": f"lead+{uuid.uuid4().hex[:6]}@linksentinel.test",
                "full_name": "Team Lead",
                "role": "manager",
                "password": "Password-12345",
            },
            headers=headers,
        )
        assert inv.status_code == 201, inv.text
        lead_id = inv.json()["user_id"]
        putp = client.put(
            f"/api/v1/team/members/{lead_id}/projects",
            json={"project_ids": [project_id]},
            headers=headers,
        )
        assert putp.status_code == 200, putp.text
        getp = client.get(f"/api/v1/team/members/{lead_id}/projects", headers=headers)
        assert getp.json()["project_ids"] == [project_id]
        bad = client.put(
            f"/api/v1/team/members/{lead_id}/projects",
            json={"project_ids": [str(uuid.uuid4())]},
            headers=headers,
        )
        assert bad.status_code in (400, 422)

        # Seed a link carrying a sheet "User" name for the provisioning check.
        bl = client.post(
            "/api/v1/backlinks",
            json={
                "project_id": project_id,
                "source_page_url": "https://publisher.test/provision-me",
                "target_url": "https://acme.test/seo",
            },
            headers=headers,
        )
        assert bl.status_code == 201, bl.text
        backlink_id = bl.json()["id"]

    # 4) Auto-provision: label → account (Viewer) + mapping + project access,
    #    rows attributed, second run a no-op.
    async def _provision() -> None:
        from types import SimpleNamespace

        from sqlalchemy import select, text

        from app.core.rbac import Role
        from app.db.session import session_scope
        from app.models.employee import UserEmployeeMapping
        from app.models.project import ProjectMember
        from app.models.user import User, WorkspaceMember
        from app.services.sheet_sync_service import _auto_provision_users

        label = f"Sheet Alex {uuid.uuid4().hex[:6]}"
        async with session_scope() as s:
            ws_id = (
                await s.execute(
                    text("SELECT workspace_id FROM projects WHERE id = :p"),
                    {"p": uuid.UUID(project_id)},
                )
            ).scalar_one()
            await s.execute(
                text("UPDATE backlink_records SET assigned_user_label = :l WHERE id = :b"),
                {"l": label, "b": uuid.UUID(backlink_id)},
            )
            await s.commit()

            source = SimpleNamespace(
                id=uuid.uuid4(), workspace_id=ws_id, project_id=uuid.UUID(project_id)
            )
            created = await _auto_provision_users(s, source, uuid.uuid4())
            assert created == 1

            mapping = (
                await s.execute(
                    select(UserEmployeeMapping).where(
                        UserEmployeeMapping.workspace_id == ws_id,
                        UserEmployeeMapping.sheet_user_label == label,
                    )
                )
            ).scalar_one()
            assert mapping.user_id is not None
            user = await s.get(User, mapping.user_id)
            assert user is not None and user.is_active
            assert user.full_name == label
            member = (
                await s.execute(
                    select(WorkspaceMember).where(
                        WorkspaceMember.workspace_id == ws_id,
                        WorkspaceMember.user_id == user.id,
                    )
                )
            ).scalar_one()
            assert member.role == Role.VIEWER
            pm = (
                await s.execute(
                    select(ProjectMember).where(
                        ProjectMember.project_id == uuid.UUID(project_id),
                        ProjectMember.user_id == user.id,
                    )
                )
            ).scalar_one_or_none()
            assert pm is not None
            attributed = (
                await s.execute(
                    text("SELECT assigned_user_id FROM backlink_records WHERE id = :b"),
                    {"b": uuid.UUID(backlink_id)},
                )
            ).scalar_one()
            assert attributed == user.id

            # Idempotent AND case-insensitive: the same name in a different case
            # must map to the SAME person, never a second account.
            await s.execute(
                text("UPDATE backlink_records SET assigned_user_label = :l WHERE id = :b"),
                {"l": label.upper(), "b": uuid.UUID(backlink_id)},
            )
            await s.commit()
            created_again = await _auto_provision_users(s, source, uuid.uuid4())
            assert created_again == 0

    asyncio.run(_provision())
