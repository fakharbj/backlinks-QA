"""Temp QA lab endpoints (Phase 11) — isolated candidate backlink tests.

Manager+ only. Everything here is separate from production data: creating a
test, auto-QA'ing its links (isolated worker), reading results, deleting.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.core.deps import AuthContext, AuthCtx, DbSession, ReadSession, require_role
from app.core.rbac import Role
from app.services import qa_test_service

router = APIRouter(prefix="/qa-tests", tags=["qa-tests"])


class QATestCreate(BaseModel):
    candidate_name: str = Field(min_length=1, max_length=200)
    candidate_email: str | None = Field(default=None, max_length=255)
    role_applied: str | None = Field(default=None, max_length=120)
    notes: str | None = Field(default=None, max_length=1000)
    brief: str | None = Field(default=None, max_length=8000)
    links_text: str = Field(min_length=1)
    default_target: str | None = Field(default=None, max_length=500)
    run_now: bool = True


@router.get("")
async def list_tests(
    ctx: AuthCtx, db: ReadSession,
    _: AuthContext = Depends(require_role(Role.MANAGER)),
) -> dict:
    return {"tests": await qa_test_service.list_batches(db, ctx)}


@router.post("", status_code=201)
async def create_test(
    payload: QATestCreate, db: DbSession,
    ctx: AuthContext = Depends(require_role(Role.MANAGER)),
) -> dict:
    batch = await qa_test_service.create_batch(
        db, ctx, candidate_name=payload.candidate_name,
        candidate_email=payload.candidate_email, role_applied=payload.role_applied,
        notes=payload.notes, brief=payload.brief, links_text=payload.links_text,
        default_target=payload.default_target,
    )
    await db.commit()
    if payload.run_now:
        await qa_test_service.mark_running(db, ctx, batch.id)
        await db.commit()
        from app.workers.tasks.qa_test import run_test

        run_test.apply_async(args=[str(batch.id)], queue="qa")
    return await qa_test_service.get_batch(db, ctx, batch.id)


@router.get("/{batch_id}")
async def get_test(
    batch_id: uuid.UUID, ctx: AuthCtx, db: ReadSession,
    _: AuthContext = Depends(require_role(Role.MANAGER)),
) -> dict:
    return await qa_test_service.get_batch(db, ctx, batch_id)


@router.post("/{batch_id}/run")
async def run_test_now(
    batch_id: uuid.UUID, db: DbSession,
    ctx: AuthContext = Depends(require_role(Role.MANAGER)),
) -> dict:
    await qa_test_service.mark_running(db, ctx, batch_id)
    await db.commit()
    from app.workers.tasks.qa_test import run_test

    run_test.apply_async(args=[str(batch_id)], queue="qa")
    return await qa_test_service.get_batch(db, ctx, batch_id)


@router.delete("/{batch_id}")
async def delete_test(
    batch_id: uuid.UUID, db: DbSession,
    ctx: AuthContext = Depends(require_role(Role.MANAGER)),
) -> dict:
    await qa_test_service.delete_batch(db, ctx, batch_id)
    await db.commit()
    return {"ok": True}


# ── Manual row management: every parse is correctable by hand ────────────────
class QATestLinkIn(BaseModel):
    source_url: str | None = Field(default=None, max_length=2000)
    target_url: str | None = Field(default=None, max_length=2000)
    anchor_text: str | None = Field(default=None, max_length=500)
    link_type: str | None = Field(default=None, max_length=80)
    expected_rel: str | None = Field(default=None, max_length=20)
    account_email: str | None = Field(default=None, max_length=255)
    account_password: str | None = Field(default=None, max_length=255)
    claimed_da: int | None = Field(default=None, ge=0, le=100)
    claimed_spam: int | None = Field(default=None, ge=0, le=100)
    is_competitor: bool | None = None


@router.post("/{batch_id}/links", status_code=201)
async def add_test_link(
    batch_id: uuid.UUID, payload: QATestLinkIn, db: DbSession,
    ctx: AuthContext = Depends(require_role(Role.MANAGER)),
) -> dict:
    """Add one row by hand (a link the parser missed, or an extra reference)."""
    await qa_test_service.add_link(db, ctx, batch_id, payload.model_dump(exclude_unset=True))
    await db.commit()
    return await qa_test_service.get_batch(db, ctx, batch_id)


@router.patch("/{batch_id}/links/{link_id}")
async def edit_test_link(
    batch_id: uuid.UUID, link_id: uuid.UUID, payload: QATestLinkIn, db: DbSession,
    ctx: AuthContext = Depends(require_role(Role.MANAGER)),
) -> dict:
    """Correct a parsed row. Changing what we check (URL/target/anchor/type/
    rel/competitor) resets that row to pending — re-run QA to verify it."""
    await qa_test_service.update_link(
        db, ctx, batch_id, link_id, payload.model_dump(exclude_unset=True)
    )
    await db.commit()
    return await qa_test_service.get_batch(db, ctx, batch_id)


@router.delete("/{batch_id}/links/{link_id}")
async def delete_test_link(
    batch_id: uuid.UUID, link_id: uuid.UUID, db: DbSession,
    ctx: AuthContext = Depends(require_role(Role.MANAGER)),
) -> dict:
    await qa_test_service.delete_link(db, ctx, batch_id, link_id)
    await db.commit()
    return await qa_test_service.get_batch(db, ctx, batch_id)
