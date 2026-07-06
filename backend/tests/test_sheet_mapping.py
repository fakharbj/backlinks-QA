"""Flexible column-mapping coverage: the PURE parse/auto-map metadata, the
DB-level staging merge (field constants + default target inheritance), and the
``header_row`` signature on the Google Sheets reader. No network is touched —
live Google Sheets reads are intentionally NOT exercised here (creds/network);
we assert the signature accepts ``header_row`` and unit-test the rest.
"""

from __future__ import annotations

import inspect
import uuid

import pytest
from sqlalchemy import select

pytestmark = pytest.mark.integration


def _register(client):
    email = f"qa+{uuid.uuid4().hex[:8]}@linksentinel.test"
    reg = client.post(
        "/api/v1/auth/register",
        json={
            "email": email, "password": "Password-12345",
            "full_name": "Admin", "workspace_name": "Sheet Mapping Ws",
        },
    )
    assert reg.status_code == 201, reg.text
    return email, {"Authorization": f"Bearer {reg.json()['access_token']}"}


def test_import_parse_field_meta():
    """CANONICAL_FIELDS and CANONICAL_FIELD_META describe exactly the same set of
    fields; source_page_url is the only required one; auto_map_report splits known
    vs unknown headers correctly (pure, no I/O)."""
    from app.services import import_parse

    field_set = set(import_parse.CANONICAL_FIELDS)
    meta_keys = [m["key"] for m in import_parse.CANONICAL_FIELD_META]
    # Exactly one meta entry per field, and vice versa (no dupes, no gaps).
    assert len(meta_keys) == len(set(meta_keys)), "duplicate keys in CANONICAL_FIELD_META"
    assert set(meta_keys) == field_set

    by_key = {m["key"]: m for m in import_parse.CANONICAL_FIELD_META}
    assert by_key["source_page_url"]["required"] is True
    # Everything else is optional.
    assert all(
        by_key[k]["required"] is False for k in field_set if k != "source_page_url"
    )

    report = import_parse.auto_map_report(["Source URL", "Target URL", "Weird Col"])
    assert report["mapping"] == {
        "Source URL": "source_page_url",
        "Target URL": "target_url",
    }
    assert len(report["matched"]) == 2
    assert set(report["matched"]) == {"Source URL", "Target URL"}
    assert report["unmatched"] == ["Weird Col"]


def test_stage_rows_constants_and_target_default(live_stack):
    """DB-level: build a real Import via import_service, stage bare-source rows
    (no target) with a header mapping + a link_type constant + a default_target,
    process it, and assert the created backlinks inherited both.

    NOTE (summary): this constructs a real Import through
    import_service.create_import / stage_rows / process on a live_stack session —
    NOT the dict-only fallback. The project is created WITHOUT a target_domain on
    purpose: _process_row prefers the project's main domain when present, so a
    domainless project lets the staged default_target flow through to target_url.
    """
    from fastapi.testclient import TestClient

    from app.core.deps import AuthContext
    from app.core.rbac import Role
    from app.db.session import SessionLocal
    from app.main import app
    from app.models.backlink import BacklinkRecord
    from app.models.enums import ImportSource
    from app.models.user import User, WorkspaceMember
    from app.services import import_service

    with TestClient(app) as client:
        email, h = _register(client)
        # Project with NO target_domain, so default_target is the effective target.
        proj = client.post(
            "/api/v1/projects", json={"name": "Mapping Proj"}, headers=h
        )
        assert proj.status_code in (200, 201), proj.text
        project_id = uuid.UUID(proj.json()["id"])

    async def _run() -> list[dict]:
        from app.db.session import engine, read_engine

        try:
            return await _run_inner()
        finally:
            # asyncio.run() closes this loop; dispose the shared engines so their
            # pooled connections don't leak into the next test's loop (the known
            # asyncpg "attached to a different loop" flake).
            await engine.dispose()
            await read_engine.dispose()

    async def _run_inner() -> list[dict]:
        async with SessionLocal() as db:
            user = (
                await db.execute(select(User).where(User.email == email))
            ).scalar_one()
            member = (
                await db.execute(
                    select(WorkspaceMember).where(WorkspaceMember.user_id == user.id)
                )
            ).scalars().first()
            ctx = AuthContext(user=user, workspace_id=member.workspace_id, role=Role.ADMIN)

            imp = await import_service.create_import(
                db,
                ctx,
                project_id=project_id,
                source=ImportSource.PASTE,
                # header→canonical mapping; only the source column is mapped.
                column_mapping={"src": "source_page_url"},
            )
            tag = uuid.uuid4().hex[:6]
            raw_rows = [
                {"src": f"https://blog-{tag}.test/one"},
                {"src": f"https://blog-{tag}.test/two"},
            ]
            await import_service.stage_rows(
                db,
                imp,
                raw_rows,
                field_constants={"link_type": "Guest Post"},
                default_target="https://acme.test/",
            )
            await db.commit()
            import_id = imp.id

        # process() manages its own commits internally.
        async with SessionLocal() as db:
            await import_service.process(db, import_id)

        async with SessionLocal() as db:
            rows = (
                await db.execute(
                    select(BacklinkRecord).where(BacklinkRecord.import_id == import_id)
                )
            ).scalars().all()
            return [
                {"target_url": r.target_url, "link_type": r.link_type} for r in rows
            ]

    import asyncio

    created = asyncio.run(_run())
    assert len(created) == 2, created
    assert all("acme.test" in (r["target_url"] or "") for r in created), created
    assert all(r["link_type"] == "Guest Post" for r in created), created


def test_read_project_sheet_header_row_signature():
    """The Google Sheets reader accepts a ``header_row`` kwarg so sheets whose
    headers are not on row 1 can be mapped. Signature-only — no network call."""
    from app.integrations import google_sheets

    sig = inspect.signature(google_sheets.read_project_sheet)
    assert "header_row" in sig.parameters
    # Backwards-compatible default keeps prior behaviour.
    assert sig.parameters["header_row"].default == 1
