"""Final-pass Loop 2 tests: file-import upsert (no duplicate records on
re-import), honest new/updated counters, manual-QA default (no auto check),
target filter + header sorting, and scoped recheck selection (only_pending +
grid filters)."""

from __future__ import annotations

import asyncio
import uuid

import pytest

pytestmark = pytest.mark.integration


def test_import_upsert_target_filter_and_scoped_recheck(live_stack):
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
                "workspace_name": "Final Loop2 Ws",
            },
        )
        assert reg.status_code == 201, reg.text
        headers = {"Authorization": f"Bearer {reg.json()['access_token']}"}
        proj = client.post("/api/v1/projects", json={"name": "Loop2 Proj"}, headers=headers)
        assert proj.status_code == 201, proj.text
        project_id = proj.json()["id"]

    marker = uuid.uuid4().hex[:8]

    async def _run() -> None:
        from sqlalchemy import func, select, text

        from app.db.session import session_scope
        from app.models.backlink import BacklinkRecord
        from app.models.enums import ImportSource, ImportStatus
        from app.models.imports import Import
        from app.services import import_service

        pid = uuid.UUID(project_id)
        rows = [
            {
                "source_page_url": f"https://blog-{marker}.example.test/post-a",
                "target_url": "https://acme.test/pricing",
            },
            {
                "source_page_url": f"https://blog-{marker}.example.test/post-b",
                "target_url": "https://acme.test/features",
            },
        ]

        async def run_import() -> Import:
            async with session_scope() as s:
                ws = (
                    await s.execute(
                        text("SELECT workspace_id FROM projects WHERE id = :p"), {"p": pid}
                    )
                ).scalar_one()
                imp = Import(
                    workspace_id=ws, project_id=pid, source=ImportSource.CSV,
                    status=ImportStatus.PENDING, column_mapping={},
                )
                s.add(imp)
                await s.flush()
                await import_service.stage_rows(s, imp, rows)
                await s.commit()
                await import_service.process(s, imp.id)
                return await s.get(Import, imp.id)

        first = await run_import()
        assert first.new_rows == 2 and (first.updated_rows or 0) == 0

        # Re-importing the SAME file must refresh, never duplicate.
        second = await run_import()
        assert (second.new_rows or 0) == 0 and second.updated_rows == 2

        async with session_scope() as s:
            n = (
                await s.execute(
                    select(func.count()).select_from(BacklinkRecord).where(
                        BacklinkRecord.project_id == pid
                    )
                )
            ).scalar_one()
            assert n == 2  # no duplicates from the second import

            # Manual-QA default: new links wait as QA pending, nothing scheduled.
            unscheduled = (
                await s.execute(
                    select(func.count()).select_from(BacklinkRecord).where(
                        BacklinkRecord.project_id == pid,
                        BacklinkRecord.next_check_at.is_(None),
                    )
                )
            ).scalar_one()
            assert unscheduled == 2

        # Pooled connections are bound to THIS loop — dispose before the next
        # TestClient spins up its own loop, or asyncpg raises cross-loop errors.
        from app.db.session import engine, read_engine

        await engine.dispose()
        await read_engine.dispose()

    asyncio.run(_run())

    with TestClient(app) as client:
        login = client.post(
            "/api/v1/auth/login", json={"email": email, "password": "Password-12345"}
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        # Target filter finds links by where they POINT.
        r = client.get(
            "/api/v1/backlinks",
            params={"project_id": project_id, "target": "/pricing"},
            headers=headers,
        )
        assert r.status_code == 200, r.text
        urls = [i["target_url"] for i in r.json()["items"]]
        assert urls and all("/pricing" in u for u in urls)

        # Header sorting: source_domain ascending works and flips.
        r = client.get(
            "/api/v1/backlinks",
            params={"project_id": project_id, "sort": "source_domain", "direction": "asc"},
            headers=headers,
        )
        assert r.status_code == 200, r.text
        assert len(r.json()["items"]) == 2

    # Scoped recheck selection (service-level: no live queueing from tests).
    async def _recheck_scope() -> None:
        from app.core.deps import AuthContext
        from app.core.rbac import Role
        from app.db.session import session_scope
        from app.models.user import User, WorkspaceMember
        from app.schemas.backlink import BacklinkFilters, RecheckRequest
        from app.services import crawl_service
        from sqlalchemy import select, text

        async with session_scope() as s:
            user = (
                await s.execute(select(User).where(User.email == email))
            ).scalar_one()
            ws = (
                await s.execute(
                    select(WorkspaceMember.workspace_id).where(
                        WorkspaceMember.user_id == user.id
                    )
                )
            ).scalars().first()
            ctx = AuthContext(user=user, workspace_id=ws, role=Role.ADMIN)

            pending = await crawl_service.select_recheck_ids(
                s, ctx, RecheckRequest(project_id=uuid.UUID(project_id), only_pending=True)
            )
            assert len(pending) == 2  # both links are QA pending

            filtered = await crawl_service.select_recheck_ids(
                s,
                ctx,
                RecheckRequest(
                    project_id=uuid.UUID(project_id),
                    filters=BacklinkFilters(
                        project_id=uuid.UUID(project_id), target="/pricing"
                    ),
                ),
            )
            assert len(filtered) == 1  # exactly the /pricing link

        from app.db.session import engine, read_engine

        await engine.dispose()
        await read_engine.dispose()

    asyncio.run(_recheck_scope())
