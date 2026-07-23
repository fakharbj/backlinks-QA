"""Sheet-sync rename resilience: renaming a Google-Sheet TAB (or reordering
rows) must NOT duplicate the links. Before the fix, sheet links were keyed only
by (sheet_source, tab_name, row) — so a canonical tab-name cleanup made every
re-synced row miss its old record and INSERT a copy. The fix adopts the single
existing (source, target) link in that sheet+project and repoints it.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest

pytestmark = pytest.mark.integration


def test_tab_rename_does_not_duplicate(live_stack):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        email = f"qa+{uuid.uuid4().hex[:8]}@linksentinel.test"
        reg = client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": "Password-12345",
                  "full_name": "Sheet QA", "workspace_name": "Rename Ws"},
        )
        assert reg.status_code == 201, reg.text
        headers = {"Authorization": f"Bearer {reg.json()['access_token']}"}
        proj = client.post("/api/v1/projects", json={"name": "Rename Proj"}, headers=headers)
        project_id = proj.json()["id"]

    src_a = f"https://blog-{uuid.uuid4().hex[:6]}.example.test/a"
    src_b = f"https://blog-{uuid.uuid4().hex[:6]}.example.test/b"

    async def _run() -> None:
        from sqlalchemy import func, select, text

        from app.db.session import session_scope
        from app.models.backlink import BacklinkRecord
        from app.models.enums import ImportSource, ImportStatus
        from app.models.imports import Import
        from app.models.sheets import SheetSource
        from app.services import import_service

        pid = uuid.UUID(project_id)

        async def sync(tab: str) -> Import:
            """One tab sync: two rows (A at row 2, B at row 3)."""
            async with session_scope() as s:
                ws = (await s.execute(
                    text("SELECT workspace_id FROM projects WHERE id = :p"), {"p": pid}
                )).scalar_one()
                ss = (await s.execute(
                    select(SheetSource).where(SheetSource.project_id == pid)
                )).scalar_one_or_none()
                if ss is None:
                    ss = SheetSource(
                        workspace_id=ws, project_id=pid, project_name="Rename Proj",
                        spreadsheet_id="sheet-xyz",
                    )
                    s.add(ss)
                    await s.flush()
                imp = Import(
                    workspace_id=ws, project_id=pid, source=ImportSource.GOOGLE_SHEETS,
                    status=ImportStatus.PENDING, column_mapping={},
                    sheet_source_id=ss.id, sheet_tab=tab,
                )
                s.add(imp)
                await s.flush()
                # stage_rows numbers rows sequentially; both syncs keep the same
                # order so only the TAB NAME differs between runs.
                await import_service.stage_rows(s, imp, [
                    {"source_page_url": src_a, "target_url": "https://acme.test/x"},
                    {"source_page_url": src_b, "target_url": "https://acme.test/x"},
                ])
                await s.commit()
                await import_service.process(s, imp.id)
                return await s.get(Import, imp.id)

        first = await sync("Web2.0")
        assert first.new_rows == 2, f"first sync new_rows={first.new_rows}"

        # Rename the tab → re-sync. Must ADOPT both existing links, not insert.
        second = await sync("Web 2.0")
        assert (second.new_rows or 0) == 0, f"rename re-inserted {second.new_rows} rows"
        assert second.updated_rows == 2

        async with session_scope() as s:
            n = (await s.execute(
                select(func.count()).select_from(BacklinkRecord).where(
                    BacklinkRecord.project_id == pid
                )
            )).scalar_one()
            assert n == 2, f"expected 2 links after rename, got {n} (duplicated!)"
            # The stored tab name was repointed to the new canonical name.
            tabs = set((await s.execute(
                select(BacklinkRecord.sheet_tab).where(BacklinkRecord.project_id == pid)
            )).scalars().all())
            assert tabs == {"Web 2.0"}, tabs

        from app.db.session import engine, read_engine
        await engine.dispose()
        await read_engine.dispose()

    asyncio.run(_run())
