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
    # New plan or an edit? (Decides task_assigned vs task_changed below —
    # checked BEFORE the upsert since on_conflict_do_update hides the answer.)
    from sqlalchemy import select as _select

    from app.models.workforce import TaskAssignment as _TA

    was_new = (
        await db.execute(
            _select(_TA.id).where(
                _TA.workspace_id == ctx.workspace_id,
                _TA.project_id == payload.project_id,
                _TA.user_label == payload.user_label.strip().lower()[:200],
                _TA.day == payload.day,
            )
        )
    ).scalar_one_or_none() is None
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
    # Tell the person (their linked login) — preference-aware, fail-open.
    from app.services import notification_service as ns

    target = await ns.user_id_for_label(db, ctx.workspace_id, payload.user_label)
    if target:
        await ns.notify(
            ctx.workspace_id,
            "task_assigned" if was_new else "task_changed",
            (f"New task: {payload.day} · {payload.hours}h"
             if was_new else f"Task updated: {payload.day} · {payload.hours}h"),
            body=f"Target: {row.expected_links} links.",
            user_ids=[target], exclude_user_id=ctx.user.id,
            project_id=payload.project_id, ref={"tab": "mywork"},
        )
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


@router.get("/people")
async def all_people(
    ctx: AuthCtx, db: ReadSession, project_id: uuid.UUID | None = None
) -> list[dict]:
    """Everyone to show in the User Dashboards grid (incl. laid-off), each flagged
    active. In project scope: people who worked on it PLUS people assigned to it
    (even if they never logged a link there)."""
    return await workforce_service.all_people(db, ctx, project_id=project_id)


# ── Weekly templates ("set the week up once") ────────────────────────────────
class TemplateWeek(BaseModel):
    week_start: date  # any day of the target week — normalized to Monday
    # "week" (this week) | "month" (next calendar month) | "range" (explicit dates)
    mode: str = "week"
    clear: bool = True       # override: wipe existing future assignments in range first
    range_from: date | None = None   # mode="range": first day to materialize
    range_to: date | None = None     # mode="range": last day (inclusive, ≤120 days)
    preview: bool = False    # dry-run: return the counts, write nothing


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
    """Apply the standing weekly template to this week, the next whole month,
    or ANY explicit date range — with a dry-run preview (``preview=true``) that
    returns exactly how many assignments would be created/replaced."""
    mode = payload.mode if payload.mode in ("week", "month", "range") else "week"
    result = await workforce_service.apply_template_to_week(
        db, ctx, week_start=payload.week_start, mode=mode, clear=payload.clear,
        range_from=payload.range_from, range_to=payload.range_to,
        preview=payload.preview,
    )
    if not payload.preview:
        await db.commit()
    return result


@router.get("/templates")
async def get_template_summary(ctx: AuthCtx, db: ReadSession) -> dict:
    return await workforce_service.template_summary(db, ctx)


class TemplateEntryUpsert(BaseModel):
    user_label: str
    weekday: int = Field(ge=0, le=6)  # 0=Mon … 6=Sun
    project_id: uuid.UUID
    hours: float = Field(ge=0, le=24)
    link_type_names: list[str] = Field(default_factory=list)
    priority: str | None = None        # high | medium | low
    note: str | None = None
    expected_links: int | None = None  # blank → computed from productivity


@router.put("/templates/entry")
async def upsert_template_entry(
    payload: TemplateEntryUpsert, db: DbSession,
    ctx: AuthContext = Depends(require(Permission.ASSIGN_MEMBERS)),
) -> dict:
    """Edit ONE standing-plan cell — lands in the current AND next week now."""
    result = await workforce_service.upsert_template_entry(
        db, ctx, user_label=payload.user_label, weekday=payload.weekday,
        project_id=payload.project_id, hours=payload.hours,
        link_type_names=payload.link_type_names, priority=payload.priority,
        note=payload.note, expected_links=payload.expected_links,
    )
    await audit_service.record(
        db, action=AuditAction.UPDATE, actor_user_id=ctx.user.id, workspace_id=ctx.workspace_id,
        entity_type="task_template", entity_id=ctx.workspace_id,
        summary=f"Template cell saved: {payload.user_label} · day {payload.weekday} · {payload.hours}h",
    )
    await db.commit()
    return result


@router.delete("/templates/entry")
async def delete_template_entry(
    db: DbSession,
    user_label: str = Query(...),
    weekday: int = Query(..., ge=0, le=6),
    project_id: uuid.UUID = Query(...),
    remove_assignments: bool = Query(True),
    ctx: AuthContext = Depends(require(Permission.ASSIGN_MEMBERS)),
) -> dict:
    result = await workforce_service.delete_template_entry(
        db, ctx, user_label=user_label, weekday=weekday,
        project_id=project_id, remove_assignments=remove_assignments,
    )
    await audit_service.record(
        db, action=AuditAction.DELETE, actor_user_id=ctx.user.id, workspace_id=ctx.workspace_id,
        entity_type="task_template", entity_id=ctx.workspace_id,
        summary=f"Template cell removed: {user_label} · day {weekday}",
    )
    await db.commit()
    return result


@router.get("/me")
async def my_work(
    ctx: AuthCtx,
    db: ReadSession,
    date_from: date = Query(...),
    date_to: date = Query(...),
) -> dict:
    """The caller's OWN plans, completion and leave — the standard-user view."""
    return await workforce_service.my_work(db, ctx, date_from=date_from, date_to=date_to)


@router.get("/assignments/{assignment_id}/domain-suggestions")
async def assignment_domain_suggestions(
    assignment_id: uuid.UUID, ctx: AuthCtx, db: ReadSession,
    limit: int = Query(20, ge=1, le=50),
) -> dict:
    """Source domains recommended for THIS task (project + link types + quality +
    robots filters; blocked/used/spammy excluded). Self-scoped: viewers can only
    ask about their own assignments."""
    from app.services import recommendation_service

    return await recommendation_service.suggest_for_task(db, ctx, assignment_id, limit=limit)


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
    # Approvers get a heads-up (admins + managers, never the requester).
    from app.services import notification_service as ns

    await ns.notify(
        ctx.workspace_id, "leave_request",
        f"Leave request: {row.user_label} · {row.start_date} → {row.end_date}",
        body=row.reason or None,
        to_admins=True, include_managers=True, exclude_user_id=ctx.user.id,
        ref={"tab": "tasks"},
    )
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
    # Tell the requester (their linked login) the decision.
    from app.services import notification_service as ns

    target = await ns.user_id_for_label(db, ctx.workspace_id, row.user_label)
    if target:
        await ns.notify(
            ctx.workspace_id, "leave_decision",
            f"Your leave {row.start_date} → {row.end_date} was {row.status}",
            user_ids=[target], exclude_user_id=ctx.user.id, ref={"tab": "mywork"},
        )
    return LeaveOut(
        id=row.id, user_label=row.user_label, start_date=row.start_date,
        end_date=row.end_date, reason=row.reason, status=row.status,
    )


# ── Office hours (owner rule): the company's daily timing, shown on the Tasks
# desk and driving the automatic sheet sync (worker gate). Setting KV. ──


class OfficeHoursIn(BaseModel):
    start: str = Field(pattern=r"^\d{2}:\d{2}$")
    end: str = Field(pattern=r"^\d{2}:\d{2}$")
    tz: str = Field(min_length=1, max_length=60)
    auto_sync: bool = False
    sync_interval_min: int = Field(default=30, ge=10, le=240)


@router.get("/office-hours")
async def get_office_hours(ctx: AuthCtx, db: ReadSession) -> dict:
    """Current office-hours config + whether we are inside them RIGHT NOW
    (working-day calendar respected) — the Tasks desk shows this live."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from app.workers.tasks.sheets import _is_working_day, _office_cfg

    cfg = await _office_cfg(db, ctx.workspace_id)
    try:
        tz = ZoneInfo(str(cfg.get("tz") or "UTC"))
    except Exception:  # noqa: BLE001
        tz = ZoneInfo("UTC")
    now = datetime.now(tz)
    working = await _is_working_day(db, ctx.workspace_id, now.date())
    hhmm = now.strftime("%H:%M")
    return {
        **cfg,
        "now": hhmm,
        "working_day": working,
        "in_hours": working and str(cfg["start"]) <= hhmm < str(cfg["end"]),
    }


@router.put("/office-hours")
async def put_office_hours(
    payload: OfficeHoursIn, db: DbSession,
    ctx: AuthContext = Depends(require(Permission.MANAGE_WORKSPACE)),
) -> dict:
    """Save office hours + auto-sync knobs (admin, audited). The worker's
    5-minute tick reads this — no restart needed."""
    from zoneinfo import ZoneInfo

    from sqlalchemy import select as _select

    from app.core.errors import ValidationAppError
    from app.models.settings import Setting

    if payload.end <= payload.start:
        raise ValidationAppError("End time must be after start time.")
    try:
        ZoneInfo(payload.tz)
    except Exception as exc:  # noqa: BLE001
        raise ValidationAppError(f"Unknown timezone '{payload.tz}' — use e.g. Asia/Karachi.") from exc
    value = payload.model_dump()
    row = (
        await db.execute(
            _select(Setting).where(
                Setting.workspace_id == ctx.workspace_id, Setting.key == "office_hours"
            )
        )
    ).scalar_one_or_none()
    if row is None:
        db.add(Setting(workspace_id=ctx.workspace_id, key="office_hours", value=value))
    else:
        row.value = value
    await audit_service.record(
        db, action=AuditAction.UPDATE, actor_user_id=ctx.user.id, workspace_id=ctx.workspace_id,
        entity_type="office_hours", entity_id=ctx.workspace_id,
        summary=f"Office hours set to {payload.start}–{payload.end} {payload.tz}"
                f" · auto-sync {'ON every ' + str(payload.sync_interval_min) + 'm' if payload.auto_sync else 'off'}",
        after=value,
    )
    await db.commit()
    return value


# ── Weekly capacity: daily hours assigned vs each person's capacity ──────────
# Per-user daily working hours live in the Setting KV "user_daily_hours":
# {label: 8} for a uniform day, or {label: [8,8,8,8,6,0,0]} for a per-weekday
# schedule (Mon..Sun — supports part-time / personal days off). Anyone without
# an entry uses the 8h default.


def _cap_for(cfg_value, weekday: int) -> float:
    """Resolve one person's configured hours for a weekday (0=Mon..6=Sun)."""
    if isinstance(cfg_value, (list, tuple)) and len(cfg_value) == 7:
        try:
            return max(0.0, min(24.0, float(cfg_value[weekday] or 0)))
        except (TypeError, ValueError):
            return 8.0
    try:
        return max(0.0, min(24.0, float(cfg_value)))
    except (TypeError, ValueError):
        return 8.0


class DailyHoursIn(BaseModel):
    user_label: str = Field(min_length=1, max_length=200)
    # Uniform daily hours… (0 = remove the override → back to the 8h default)
    hours: float | None = Field(default=None, ge=0, le=24)
    # …or a per-weekday schedule [Mon..Sun], e.g. [8,8,8,8,6,0,0] (part-time).
    day_hours: list[float] | None = Field(default=None, min_length=7, max_length=7)


@router.get("/capacity")
async def weekly_capacity(
    ctx: AuthCtx, db: ReadSession, week_start: date,
) -> dict:
    """One row per ACTIVE person × the 7 days of the week: hours assigned,
    capacity (their personal daily hours, default 8; 0 on non-working days),
    and free hours. Drives the Tasks-desk capacity table."""
    from datetime import timedelta as _td

    from sqlalchemy import func, select as _select

    from app.models.settings import Setting
    from app.models.workforce import TaskAssignment, WorkingDay
    from app.services.workforce_service import _default_working, known_labels

    monday = week_start - _td(days=week_start.weekday())
    days = [monday + _td(days=i) for i in range(7)]
    labels = await known_labels(db, ctx)  # active people, TeamLead-scoped

    hours_cfg_row = (
        await db.execute(
            _select(Setting).where(
                Setting.workspace_id == ctx.workspace_id, Setting.key == "user_daily_hours"
            )
        )
    ).scalar_one_or_none()
    hours_cfg: dict = (
        hours_cfg_row.value if hours_cfg_row is not None and isinstance(hours_cfg_row.value, dict) else {}
    )

    # Assigned hours per (person, day) in one grouped query.
    rows = (
        await db.execute(
            _select(
                TaskAssignment.user_label, TaskAssignment.day,
                func.sum(TaskAssignment.hours),
            )
            .where(
                TaskAssignment.workspace_id == ctx.workspace_id,
                TaskAssignment.day >= days[0], TaskAssignment.day <= days[-1],
            )
            .group_by(TaskAssignment.user_label, TaskAssignment.day)
        )
    ).all()
    assigned: dict[tuple[str, str], float] = {
        (lbl, d.isoformat()): float(h or 0) for lbl, d, h in rows
    }

    # Working-day overrides for the week (default: Mon–Sat working).
    overrides = dict(
        (
            await db.execute(
                _select(WorkingDay.day, WorkingDay.is_working).where(
                    WorkingDay.workspace_id == ctx.workspace_id,
                    WorkingDay.day >= days[0], WorkingDay.day <= days[-1],
                )
            )
        ).all()
    )
    working = {
        d.isoformat(): bool(overrides.get(d, _default_working(d))) for d in days
    }

    people = []
    for lbl in labels:
        cfg_val = hours_cfg.get(lbl, 8)
        per_day = isinstance(cfg_val, (list, tuple)) and len(cfg_val) == 7
        day_cells = []
        for d in days:
            iso = d.isoformat()
            a = round(assigned.get((lbl, iso), 0.0), 1)
            # Company working-day calendar gates first; the person's own
            # schedule (uniform or per-weekday) sets the day's capacity.
            c = _cap_for(cfg_val, d.weekday()) if working[iso] else 0.0
            day_cells.append({
                "day": iso, "assigned": a, "capacity": c,
                "free": round(max(0.0, c - a), 1), "working": working[iso] and c > 0,
                "over": a > c and c > 0,
            })
        wk_a = round(sum(x["assigned"] for x in day_cells), 1)
        # Owner rule: hours planned on a company NON-WORKING day are excused —
        # they must not create phantom weekly overbooking, eat "free" hours or
        # inflate utilisation. week_assigned stays the full factual total.
        wk_a_workable = round(
            sum(x["assigned"] for x, d in zip(day_cells, days) if working[d.isoformat()]), 1
        )
        wk_c = round(sum(x["capacity"] for x in day_cells), 1)
        people.append({
            "user_label": lbl,
            "daily_hours": _cap_for(cfg_val, 0) if not per_day else None,
            "day_hours": [_cap_for(cfg_val, i) for i in range(7)] if per_day else None,
            "days": day_cells,
            "week_assigned": wk_a, "week_capacity": wk_c,
            "week_free": round(max(0.0, wk_c - wk_a_workable), 1),
            "week_over": round(max(0.0, wk_a_workable - wk_c), 1),
            "utilization_pct": round(100 * wk_a_workable / wk_c) if wk_c else None,
        })
    # Per-day totals across everyone (the "how many hours are free each day" row).
    day_totals = []
    for i, d in enumerate(days):
        a = round(sum(p["days"][i]["assigned"] for p in people), 1)
        c = round(sum(p["days"][i]["capacity"] for p in people), 1)
        day_totals.append({
            "day": d.isoformat(), "assigned": a, "capacity": c,
            "free": round(max(0.0, c - a), 1), "working": working[d.isoformat()],
        })
    return {
        "week_start": days[0].isoformat(), "week_end": days[-1].isoformat(),
        "people": people, "day_totals": day_totals, "default_daily_hours": 8,
    }


@router.put("/daily-hours", response_model=Message)
async def set_daily_hours(
    payload: DailyHoursIn, db: DbSession,
    ctx: AuthContext = Depends(require(Permission.ASSIGN_MEMBERS)),
) -> Message:
    """Set one person's daily working hours (their capacity). 0 = removes the
    override → back to the 8h default. Audited."""
    from sqlalchemy import select as _select

    from app.models.settings import Setting

    label = payload.user_label.strip().lower()[:200]
    row = (
        await db.execute(
            _select(Setting).where(
                Setting.workspace_id == ctx.workspace_id, Setting.key == "user_daily_hours"
            )
        )
    ).scalar_one_or_none()
    cfg = dict(row.value) if row is not None and isinstance(row.value, dict) else {}
    if payload.day_hours is not None:
        # Per-weekday schedule [Mon..Sun] — part-time / personal days off.
        clean = [max(0.0, min(24.0, float(h or 0))) for h in payload.day_hours]
        if any(clean):
            cfg[label] = clean
            desc = "/".join(f"{h:g}" for h in clean)
        else:
            cfg.pop(label, None)
            desc = "default (8)"
    elif payload.hours and payload.hours > 0:
        cfg[label] = float(payload.hours)
        desc = f"{payload.hours:g}"
    else:
        cfg.pop(label, None)
        desc = "default (8)"
    if row is None:
        db.add(Setting(workspace_id=ctx.workspace_id, key="user_daily_hours", value=cfg))
    else:
        row.value = cfg
    await audit_service.record(
        db, action=AuditAction.UPDATE, actor_user_id=ctx.user.id, workspace_id=ctx.workspace_id,
        entity_type="user_daily_hours", entity_id=ctx.workspace_id,
        summary=f"Daily working hours for {label}: {desc}h",
    )
    await db.commit()
    return Message(message=f"{label}: {desc}h/day saved")
