"""Workforce endpoints (Phase 9 P2): tasks, productivity, calendar, leave.

Reads are open to any member; plan/calendar/decision writes require
ASSIGN_MEMBERS (admin + manager/TeamLead); leave requests can be submitted by
any member (a user asking for their own day off).
"""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.core.deps import AuthContext, AuthCtx, DbSession, ReadSession, require
from app.core.rbac import Permission
from app.models.enums import AuditAction
from app.schemas.common import Message
from app.services import audit_service, workforce_service

router = APIRouter(prefix="/workforce", tags=["workforce"])


# ── Productivity ─────────────────────────────────────────────────────────────
class ProductivitySet(BaseModel):
    link_type_name: str
    links_per_hour: float = Field(gt=0, le=1000)
    user_label: str | None = None  # set → per-user override, else global


@router.get("/productivity")
async def get_productivity(ctx: AuthCtx, db: ReadSession) -> dict:
    return await workforce_service.productivity(db, ctx)


@router.put("/productivity", response_model=Message)
async def put_productivity(
    payload: ProductivitySet, db: DbSession,
    ctx: AuthContext = Depends(require(Permission.ASSIGN_MEMBERS)),
) -> Message:
    await workforce_service.set_productivity(
        db, ctx, link_type_name=payload.link_type_name,
        links_per_hour=payload.links_per_hour, user_label=payload.user_label,
    )
    await db.commit()
    return Message(message="Productivity saved")


@router.delete("/productivity", response_model=Message)
async def remove_productivity_override(
    db: DbSession,
    user_label: str = Query(...),
    link_type_name: str = Query(...),
    ctx: AuthContext = Depends(require(Permission.ASSIGN_MEMBERS)),
) -> Message:
    await workforce_service.delete_productivity_override(
        db, ctx, user_label=user_label, link_type_name=link_type_name
    )
    await db.commit()
    return Message(message="Override removed — global rate applies again")


# ── Assignments ──────────────────────────────────────────────────────────────
class AssignmentUpsert(BaseModel):
    project_id: uuid.UUID
    user_label: str
    day: date
    hours: float = Field(ge=0, le=24)
    link_type_names: list[str] = Field(default_factory=list)
    expected_links: int | None = None  # blank → computed from productivity
    priority: str | None = None        # high | medium | low
    note: str | None = None


@router.post("/assignments")
async def upsert_assignment(
    payload: AssignmentUpsert, db: DbSession,
    ctx: AuthContext = Depends(require(Permission.ASSIGN_MEMBERS)),
) -> dict:
    row, warnings = await workforce_service.upsert_assignment(
        db, ctx, project_id=payload.project_id, user_label=payload.user_label,
        day=payload.day, hours=payload.hours, link_type_names=payload.link_type_names,
        expected_links=payload.expected_links, note=payload.note,
        priority=payload.priority,
    )
    await audit_service.record(
        db, action=AuditAction.UPDATE, actor_user_id=ctx.user.id, workspace_id=ctx.workspace_id,
        entity_type="task_assignment", entity_id=row.id,
        summary=f"Assigned {payload.user_label} · {payload.day} · {payload.hours}h",
    )
    await db.commit()
    return {
        "id": str(row.id),
        "expected_links": row.expected_links,
        "rate_source": row.rate_source,
        "lph_used": float(row.lph_used) if row.lph_used is not None else None,
        "warnings": warnings,
    }


@router.get("/labels")
async def known_labels(ctx: AuthCtx, db: ReadSession) -> list[str]:
    """Everyone the caller can plan for (employee catalog + past assignments)."""
    return await workforce_service.known_labels(db, ctx)


# ── Weekly templates ("set the week up once") ────────────────────────────────
class TemplateWeek(BaseModel):
    week_start: date  # any day of the target week — normalized to Monday


@router.post("/templates/save-week")
async def save_week_template(
    payload: TemplateWeek, db: DbSession,
    ctx: AuthContext = Depends(require(Permission.ASSIGN_MEMBERS)),
) -> dict:
    """Capture that week's plans as the standing weekly template."""
    saved = await workforce_service.save_week_as_template(db, ctx, week_start=payload.week_start)
    await audit_service.record(
        db, action=AuditAction.UPDATE, actor_user_id=ctx.user.id, workspace_id=ctx.workspace_id,
        entity_type="task_template", entity_id=ctx.workspace_id,
        summary=f"Weekly template saved ({saved} entries)",
    )
    await db.commit()
    return {"saved": saved, "message": f"Template saved — {saved} entries. Next weeks fill automatically."}


@router.post("/templates/apply")
async def apply_week_template(
    payload: TemplateWeek, db: DbSession,
    ctx: AuthContext = Depends(require(Permission.ASSIGN_MEMBERS)),
) -> dict:
    """Copy the standing weekly template into the given week right now."""
    result = await workforce_service.apply_template_to_week(db, ctx, week_start=payload.week_start)
    await db.commit()
    return result


@router.get("/templates")
async def get_template_summary(ctx: AuthCtx, db: ReadSession) -> dict:
    return await workforce_service.template_summary(db, ctx)


@router.get("/me")
async def my_work(
    ctx: AuthCtx,
    db: ReadSession,
    date_from: date = Query(...),
    date_to: date = Query(...),
) -> dict:
    """The caller's OWN plans, completion and leave — the standard-user view."""
    return await workforce_service.my_work(db, ctx, date_from=date_from, date_to=date_to)


@router.delete("/assignments/{assignment_id}", response_model=Message)
async def remove_assignment(
    assignment_id: uuid.UUID, db: DbSession,
    ctx: AuthContext = Depends(require(Permission.ASSIGN_MEMBERS)),
) -> Message:
    await workforce_service.delete_assignment(db, ctx, assignment_id)
    await db.commit()
    return Message(message="Assignment removed")


@router.get("/day-report")
async def day_report(
    ctx: AuthCtx,
    db: ReadSession,
    date_from: date = Query(...),
    date_to: date = Query(...),
    project_id: uuid.UUID | None = Query(None),
    user_label: str | None = Query(None),
) -> list[dict]:
    return await workforce_service.day_report(
        db, ctx, date_from=date_from, date_to=date_to,
        project_id=project_id, user_label=user_label,
    )


# ── Working-days calendar ────────────────────────────────────────────────────
class WorkingDaySet(BaseModel):
    day: date
    is_working: bool


@router.get("/calendar")
async def month_calendar(
    ctx: AuthCtx, db: ReadSession, year: int = Query(...), month: int = Query(..., ge=1, le=12)
) -> list[dict]:
    return await workforce_service.month_calendar(db, ctx, year=year, month=month)


@router.put("/calendar", response_model=Message)
async def set_working_day(
    payload: WorkingDaySet, db: DbSession,
    ctx: AuthContext = Depends(require(Permission.ASSIGN_MEMBERS)),
) -> Message:
    await workforce_service.set_working_day(db, ctx, day=payload.day, is_working=payload.is_working)
    await db.commit()
    return Message(message="Calendar updated")


# ── Leave ────────────────────────────────────────────────────────────────────
class LeaveCreate(BaseModel):
    user_label: str
    start_date: date
    end_date: date
    reason: str | None = None


class LeaveOut(BaseModel):
    id: uuid.UUID
    user_label: str
    start_date: date
    end_date: date
    reason: str | None
    status: str


@router.post("/leaves", response_model=LeaveOut, status_code=201)
async def request_leave(payload: LeaveCreate, ctx: AuthCtx, db: DbSession) -> LeaveOut:
    row = await workforce_service.request_leave(
        db, ctx, user_label=payload.user_label, start_date=payload.start_date,
        end_date=payload.end_date, reason=payload.reason,
    )
    await db.commit()
    return LeaveOut(
        id=row.id, user_label=row.user_label, start_date=row.start_date,
        end_date=row.end_date, reason=row.reason, status=row.status,
    )


@router.get("/leaves", response_model=list[LeaveOut])
async def list_leaves(
    ctx: AuthCtx, db: ReadSession, status: str | None = Query(None)
) -> list[LeaveOut]:
    rows = await workforce_service.list_leaves(db, ctx, status=status)
    return [
        LeaveOut(
            id=r.id, user_label=r.user_label, start_date=r.start_date,
            end_date=r.end_date, reason=r.reason, status=r.status,
        )
        for r in rows
    ]


@router.patch("/leaves/{leave_id}", response_model=LeaveOut)
async def decide_leave(
    leave_id: uuid.UUID, approve: bool, db: DbSession,
    ctx: AuthContext = Depends(require(Permission.ASSIGN_MEMBERS)),
) -> LeaveOut:
    row = await workforce_service.decide_leave(db, ctx, leave_id, approve=approve)
    await audit_service.record(
        db, action=AuditAction.UPDATE, actor_user_id=ctx.user.id, workspace_id=ctx.workspace_id,
        entity_type="leave_request", entity_id=row.id,
        summary=f"Leave {row.user_label} {row.start_date}→{row.end_date}: {row.status}",
    )
    await db.commit()
    return LeaveOut(
        id=row.id, user_label=row.user_label, start_date=row.start_date,
        end_date=row.end_date, reason=row.reason, status=row.status,
    )
