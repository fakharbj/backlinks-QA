"""Workforce logic (Phase 9 P2): assignments, productivity, calendar, leave.

Performance is snapshot-correct by construction: a day's report joins that day's
``task_assignments`` rows (frozen plan) with the links actually created that day
by that user/project. Approved leave or a non-working day EXCUSES the plan (the
day drops out of the denominator); an unexcused shortfall counts against it.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import AuthContext
from app.core.errors import NotFoundError, ValidationAppError
from app.models.workforce import (
    LeaveRequest,
    LinkTypeProductivity,
    TaskAssignment,
    UserProductivityOverride,
    WorkingDay,
)

_DEFAULT_LPH = 5.0


# ── Productivity ─────────────────────────────────────────────────────────────
async def productivity(db: AsyncSession, ctx: AuthContext) -> dict:
    globals_ = (
        await db.execute(
            select(LinkTypeProductivity)
            .where(LinkTypeProductivity.workspace_id == ctx.workspace_id)
            .order_by(LinkTypeProductivity.link_type_name)
        )
    ).scalars().all()
    overrides = (
        await db.execute(
            select(UserProductivityOverride)
            .where(UserProductivityOverride.workspace_id == ctx.workspace_id)
            .order_by(UserProductivityOverride.user_label, UserProductivityOverride.link_type_name)
        )
    ).scalars().all()
    return {
        "global": [
            {"link_type_name": g.link_type_name, "links_per_hour": float(g.links_per_hour)}
            for g in globals_
        ],
        "overrides": [
            {
                "user_label": o.user_label, "link_type_name": o.link_type_name,
                "links_per_hour": float(o.links_per_hour),
            }
            for o in overrides
        ],
    }


async def set_productivity(
    db: AsyncSession, ctx: AuthContext, *, link_type_name: str,
    links_per_hour: float, user_label: str | None = None,
) -> None:
    if links_per_hour <= 0 or links_per_hour > 1000:
        raise ValidationAppError("Links per hour must be between 0 and 1000.")
    name = link_type_name.strip()[:80]
    if not name:
        raise ValidationAppError("Link type name is required.")
    if user_label:
        stmt = (
            pg_insert(UserProductivityOverride)
            .values(
                workspace_id=ctx.workspace_id, user_label=user_label.strip()[:200],
                link_type_name=name, links_per_hour=links_per_hour,
            )
            .on_conflict_do_update(
                constraint="uq_upo_ws_user_type", set_={"links_per_hour": links_per_hour}
            )
        )
    else:
        stmt = (
            pg_insert(LinkTypeProductivity)
            .values(
                workspace_id=ctx.workspace_id, link_type_name=name, links_per_hour=links_per_hour
            )
            .on_conflict_do_update(
                constraint="uq_ltp_ws_type", set_={"links_per_hour": links_per_hour}
            )
        )
    await db.execute(stmt)
    await db.flush()


async def _lph_map(db: AsyncSession, workspace_id: uuid.UUID) -> tuple[dict, dict]:
    g = {
        r.link_type_name.lower(): float(r.links_per_hour)
        for r in (
            await db.execute(
                select(LinkTypeProductivity).where(
                    LinkTypeProductivity.workspace_id == workspace_id
                )
            )
        ).scalars().all()
    }
    o = {
        (r.user_label, r.link_type_name.lower()): float(r.links_per_hour)
        for r in (
            await db.execute(
                select(UserProductivityOverride).where(
                    UserProductivityOverride.workspace_id == workspace_id
                )
            )
        ).scalars().all()
    }
    return g, o


def _expected(hours: float, types: list[str], user_label: str, g: dict, o: dict) -> int:
    if hours <= 0 or not types:
        return 0
    per_type_hours = hours / len(types)
    total = 0.0
    for t in types:
        key = t.lower()
        lph = o.get((user_label, key), g.get(key, _DEFAULT_LPH))
        total += per_type_hours * lph
    return int(round(total))


# ── Assignments ──────────────────────────────────────────────────────────────
async def upsert_assignment(
    db: AsyncSession, ctx: AuthContext, *, project_id: uuid.UUID, user_label: str,
    day: date, hours: float, link_type_names: list[str],
    expected_links: int | None = None, note: str | None = None,
) -> TaskAssignment:
    ctx.assert_project(project_id)
    if hours < 0 or hours > 24:
        raise ValidationAppError("Hours must be between 0 and 24.")
    label = user_label.strip()[:200]
    if not label:
        raise ValidationAppError("User is required.")
    types = [t.strip()[:80] for t in link_type_names if t.strip()][:12]
    if expected_links is None:
        g, o = await _lph_map(db, ctx.workspace_id)
        expected_links = _expected(hours, types, label, g, o)
    stmt = (
        pg_insert(TaskAssignment)
        .values(
            workspace_id=ctx.workspace_id, project_id=project_id, user_label=label,
            day=day, hours=hours, link_type_names=types,
            expected_links=max(0, int(expected_links)), note=(note or "")[:300] or None,
            created_by=ctx.user.id,
        )
        .on_conflict_do_update(
            constraint="uq_task_ws_proj_user_day",
            set_={
                "hours": hours, "link_type_names": types,
                "expected_links": max(0, int(expected_links)),
                "note": (note or "")[:300] or None, "created_by": ctx.user.id,
            },
        )
        .returning(TaskAssignment.id)
    )
    row_id = (await db.execute(stmt)).scalar_one()
    await db.flush()
    return await db.get(TaskAssignment, row_id)


async def delete_assignment(db: AsyncSession, ctx: AuthContext, assignment_id: uuid.UUID) -> None:
    row = await db.get(TaskAssignment, assignment_id)
    if row is None or row.workspace_id != ctx.workspace_id:
        raise NotFoundError("Assignment not found")
    await db.execute(delete(TaskAssignment).where(TaskAssignment.id == assignment_id))
    await db.flush()


def _default_working(d: date) -> bool:
    return d.weekday() != 6  # Sunday off by default (owners can override any date)


async def day_report(
    db: AsyncSession, ctx: AuthContext, *, date_from: date, date_to: date,
    project_id: uuid.UUID | None = None, user_label: str | None = None,
) -> list[dict]:
    """Assignments in the window joined with actual links created + excusals."""
    if (date_to - date_from).days > 92:
        raise ValidationAppError("Choose a window of 3 months or less.")
    if project_id is not None:
        ctx.assert_project(project_id)

    stmt = select(TaskAssignment).where(
        TaskAssignment.workspace_id == ctx.workspace_id,
        TaskAssignment.day >= date_from,
        TaskAssignment.day <= date_to,
    )
    if project_id is not None:
        stmt = stmt.where(TaskAssignment.project_id == project_id)
    if user_label:
        stmt = stmt.where(TaskAssignment.user_label == user_label)
    rows = (
        await db.execute(stmt.order_by(TaskAssignment.day.desc(), TaskAssignment.user_label))
    ).scalars().all()
    if not rows:
        return []

    overrides = {
        w.day: w.is_working
        for w in (
            await db.execute(
                select(WorkingDay).where(
                    WorkingDay.workspace_id == ctx.workspace_id,
                    WorkingDay.day >= date_from, WorkingDay.day <= date_to,
                )
            )
        ).scalars().all()
    }
    leaves = (
        await db.execute(
            select(LeaveRequest).where(
                LeaveRequest.workspace_id == ctx.workspace_id,
                LeaveRequest.status == "approved",
                LeaveRequest.start_date <= date_to,
                LeaveRequest.end_date >= date_from,
            )
        )
    ).scalars().all()

    def on_leave(label: str, d: date) -> bool:
        return any(lv.user_label == label and lv.start_date <= d <= lv.end_date for lv in leaves)

    # Actual links per (project, user, day) in one query.
    actuals: dict[tuple, int] = {}
    result = await db.execute(
        text(
            """
            SELECT project_id, coalesce(nullif(assigned_user_label, ''), '(unassigned)') AS u,
                   created_at::date AS d, count(*) AS n
            FROM backlink_records
            WHERE workspace_id = :ws AND created_at::date >= :f AND created_at::date <= :t
            GROUP BY 1, 2, 3
            """
        ),
        {"ws": ctx.workspace_id, "f": date_from, "t": date_to},
    )
    for r in result.mappings().all():
        actuals[(r["project_id"], r["u"], r["d"])] = int(r["n"])

    out = []
    for a in rows:
        working = overrides.get(a.day, _default_working(a.day))
        excused = (not working) or on_leave(a.user_label, a.day)
        actual = actuals.get((a.project_id, a.user_label, a.day), 0)
        completion = (
            None if excused or a.expected_links <= 0
            else round(100.0 * actual / a.expected_links, 1)
        )
        out.append(
            {
                "id": str(a.id), "day": a.day.isoformat(), "project_id": str(a.project_id),
                "user_label": a.user_label, "hours": float(a.hours),
                "link_type_names": a.link_type_names or [],
                "expected_links": a.expected_links, "actual_links": actual,
                "completion_pct": completion,
                "excused": excused,
                "excuse_reason": (
                    None if not excused
                    else ("On approved leave" if on_leave(a.user_label, a.day) else "Non-working day")
                ),
                "note": a.note,
            }
        )
    return out


# ── Working days ─────────────────────────────────────────────────────────────
async def month_calendar(db: AsyncSession, ctx: AuthContext, *, year: int, month: int) -> list[dict]:
    first = date(year, month, 1)
    nxt = date(year + (month == 12), (month % 12) + 1, 1)
    overrides = {
        w.day: w.is_working
        for w in (
            await db.execute(
                select(WorkingDay).where(
                    WorkingDay.workspace_id == ctx.workspace_id,
                    WorkingDay.day >= first, WorkingDay.day < nxt,
                )
            )
        ).scalars().all()
    }
    days = []
    d = first
    while d < nxt:
        days.append(
            {
                "day": d.isoformat(),
                "is_working": overrides.get(d, _default_working(d)),
                "is_override": d in overrides,
            }
        )
        d += timedelta(days=1)
    return days


async def set_working_day(
    db: AsyncSession, ctx: AuthContext, *, day: date, is_working: bool
) -> None:
    stmt = (
        pg_insert(WorkingDay)
        .values(workspace_id=ctx.workspace_id, day=day, is_working=is_working)
        .on_conflict_do_update(constraint="uq_working_day", set_={"is_working": is_working})
    )
    await db.execute(stmt)
    await db.flush()


# ── Leave ────────────────────────────────────────────────────────────────────
async def request_leave(
    db: AsyncSession, ctx: AuthContext, *, user_label: str, start_date: date,
    end_date: date, reason: str | None,
) -> LeaveRequest:
    if end_date < start_date:
        raise ValidationAppError("End date is before the start date.")
    if (end_date - start_date).days > 60:
        raise ValidationAppError("A single request can cover at most 60 days.")
    row = LeaveRequest(
        workspace_id=ctx.workspace_id, user_label=user_label.strip()[:200],
        start_date=start_date, end_date=end_date, reason=(reason or "")[:300] or None,
        status="pending", requested_by=ctx.user.id,
    )
    db.add(row)
    await db.flush()
    return row


async def list_leaves(
    db: AsyncSession, ctx: AuthContext, *, status: str | None = None, limit: int = 200
) -> list[LeaveRequest]:
    stmt = select(LeaveRequest).where(LeaveRequest.workspace_id == ctx.workspace_id)
    if status in ("pending", "approved", "rejected"):
        stmt = stmt.where(LeaveRequest.status == status)
    stmt = stmt.order_by(LeaveRequest.created_at.desc()).limit(limit)
    return list((await db.execute(stmt)).scalars().all())


async def decide_leave(
    db: AsyncSession, ctx: AuthContext, leave_id: uuid.UUID, *, approve: bool
) -> LeaveRequest:
    from datetime import datetime, timezone

    row = await db.get(LeaveRequest, leave_id)
    if row is None or row.workspace_id != ctx.workspace_id:
        raise NotFoundError("Leave request not found")
    row.status = "approved" if approve else "rejected"
    row.decided_by = ctx.user.id
    row.decided_at = datetime.now(timezone.utc)
    await db.flush()
    return row
