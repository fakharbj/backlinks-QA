"""Intern management (owner final brief #7/#8): a dedicated review surface.

Interns submit links into isolated ``link_review`` batches (never straight to
production). This router gives managers/admins the ANALYSIS layer over that
data: per-intern submission metrics (from their batches + staged items and the
QA verdicts stored in item payloads), reviewer feedback + promotion-readiness
(one Setting row ``intern_reviews``), and the batch list backing the review
flow. Promotion itself is the normal Team role change; data transfer is the
normal approve pipeline — nothing here duplicates those.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text

from app.core.deps import AuthContext, DbSession, ReadSession, require_role
from app.core.rbac import Role
from app.models.enums import AuditAction
from app.models.settings import Setting
from app.models.user import User, WorkspaceMember
from app.services import audit_service

router = APIRouter(prefix="/interns", tags=["interns"])

_REVIEWS_KEY = "intern_reviews"


async def _reviews(db, workspace_id: uuid.UUID) -> dict:
    row = (
        await db.execute(
            select(Setting).where(
                Setting.workspace_id == workspace_id, Setting.key == _REVIEWS_KEY
            )
        )
    ).scalar_one_or_none()
    return dict(row.value) if row is not None and isinstance(row.value, dict) else {}


@router.get("")
async def list_interns(
    db: ReadSession,
    ctx: AuthContext = Depends(require_role(Role.MANAGER)),
) -> dict:
    """Every intern account + their submission analytics, computed live from
    their review batches (total/approved/rejected/open items, failed checks,
    QA pass counts + average staged score, last activity) + reviewer state."""
    members = (
        await db.execute(
            select(WorkspaceMember, User)
            .join(User, User.id == WorkspaceMember.user_id)
            .where(
                WorkspaceMember.workspace_id == ctx.workspace_id,
                WorkspaceMember.role == Role.INTERN,
            )
            .order_by(User.full_name)
        )
    ).all()
    uids = [u.id for _, u in members]
    stats: dict[str, dict] = {}
    if uids:
        rows = (
            await db.execute(
                text(
                    """
                    SELECT b.started_by AS uid,
                           count(DISTINCT b.id)                                    AS batches,
                           count(i.id)                                             AS items,
                           count(*) FILTER (WHERE i.state = 'approved')            AS approved,
                           count(*) FILTER (WHERE i.state = 'rejected')            AS rejected,
                           count(*) FILTER (WHERE i.state IN ('pending','checking','checked')) AS open_items,
                           count(*) FILTER (WHERE i.state = 'failed')              AS failed_checks,
                           count(*) FILTER (WHERE i.payload->'qa'->>'status' = 'PASS') AS qa_pass,
                           avg(NULLIF(i.payload->'qa'->>'score', '')::numeric)     AS avg_score,
                           max(b.started_at)                                       AS last_at
                    FROM batches b
                    LEFT JOIN batch_items i ON i.batch_id = b.id
                    WHERE b.workspace_id = :ws AND b.kind = 'link_review'
                      AND b.started_by = ANY(:uids)
                    GROUP BY b.started_by
                    """
                ).bindparams(ws=ctx.workspace_id, uids=uids)
            )
        ).mappings().all()
        stats = {str(r["uid"]): dict(r) for r in rows}
    reviews = await _reviews(db, ctx.workspace_id)

    out = []
    for member, user in members:
        st = stats.get(str(user.id), {})
        items = int(st.get("items") or 0)
        approved = int(st.get("approved") or 0)
        rejected = int(st.get("rejected") or 0)
        decided = approved + rejected
        rv = reviews.get(str(user.id), {})
        avg_score = st.get("avg_score")
        out.append(
            {
                "user_id": str(user.id),
                "full_name": user.full_name,
                "email": user.email,
                "active": bool(user.is_active),
                "avatar_data_uri": user.avatar_data_uri,
                "joined": member.created_at.isoformat() if member.created_at else None,
                "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
                "batches": int(st.get("batches") or 0),
                "items": items,
                "approved": approved,
                "rejected": rejected,
                "open_items": int(st.get("open_items") or 0),
                "failed_checks": int(st.get("failed_checks") or 0),
                "qa_pass": int(st.get("qa_pass") or 0),
                "avg_score": round(float(avg_score), 1) if avg_score is not None else None,
                "approval_rate": round(100.0 * approved / decided, 1) if decided else None,
                "qa_pass_rate": round(100.0 * int(st.get("qa_pass") or 0) / items, 1) if items else None,
                "last_submission_at": st["last_at"].isoformat() if st.get("last_at") else None,
                "ready": bool(rv.get("ready")),
                "notes": list(rv.get("notes") or [])[-10:],
            }
        )
    totals = {
        "interns": len(out),
        "active": sum(1 for r in out if r["active"]),
        "items": sum(r["items"] for r in out),
        "approved": sum(r["approved"] for r in out),
        "open_items": sum(r["open_items"] for r in out),
        "ready": sum(1 for r in out if r["ready"]),
    }
    return {"items": out, "totals": totals}


class FeedbackIn(BaseModel):
    note: str | None = Field(default=None, max_length=500)
    ready: bool | None = None  # set/unset "ready for promotion"


@router.post("/{user_id}/feedback")
async def intern_feedback(
    user_id: uuid.UUID,
    payload: FeedbackIn,
    db: DbSession,
    ctx: AuthContext = Depends(require_role(Role.MANAGER)),
) -> dict:
    """Reviewer feedback + promotion-readiness flag. Notes are an append-only
    history (who + when); audited."""
    member = (
        await db.execute(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == ctx.workspace_id,
                WorkspaceMember.user_id == user_id,
                WorkspaceMember.role == Role.INTERN,
            )
        )
    ).scalar_one_or_none()
    if member is None:
        from app.core.errors import NotFoundError

        raise NotFoundError("Intern not found")
    row = (
        await db.execute(
            select(Setting).where(
                Setting.workspace_id == ctx.workspace_id, Setting.key == _REVIEWS_KEY
            )
        )
    ).scalar_one_or_none()
    data = dict(row.value) if row is not None and isinstance(row.value, dict) else {}
    entry = dict(data.get(str(user_id)) or {})
    changed_bits = []
    if payload.note and payload.note.strip():
        notes = list(entry.get("notes") or [])
        notes.append(
            {
                "note": payload.note.strip()[:500],
                "by": ctx.user.full_name or ctx.user.email,
                "at": datetime.now(timezone.utc).isoformat(),
            }
        )
        entry["notes"] = notes[-50:]
        changed_bits.append("feedback added")
    if payload.ready is not None:
        entry["ready"] = bool(payload.ready)
        changed_bits.append("marked READY for promotion" if payload.ready else "readiness cleared")
    data[str(user_id)] = entry
    if row is None:
        db.add(Setting(workspace_id=ctx.workspace_id, key=_REVIEWS_KEY, value=data, is_secret=False))
    else:
        row.value = data
        # JSONB column: reassignment above replaces the whole value (tracked).
    await audit_service.record(
        db, action=AuditAction.UPDATE, actor_user_id=ctx.user.id, workspace_id=ctx.workspace_id,
        entity_type="intern_review", entity_id=user_id,
        summary=f"Intern review — {', '.join(changed_bits) or 'no change'}",
    )
    await db.commit()
    return {"ok": True, "ready": bool(entry.get("ready")), "notes": entry.get("notes", [])[-10:]}
