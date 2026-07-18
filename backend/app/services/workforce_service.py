"""Workforce logic (Phase 9 P2): assignments, productivity, calendar, leave.

Performance is snapshot-correct by construction: a day's report joins that day's
``task_assignments`` rows (frozen plan) with the links actually created that day
by that user/project. Approved leave or a non-working day EXCUSES the plan (the
day drops out of the denominator); an unexcused shortfall counts against it.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import AuthContext
from app.core.errors import NotFoundError, ValidationAppError
from app.models.workforce import (
    LeaveRequest,
    LinkTypeProductivity,
    TaskAssignment,
    TeamLeadAssignment,
    UserProductivityOverride,
    WorkingDay,
)

_DEFAULT_LPH = 5.0


async def own_labels(db: AsyncSession, ctx: AuthContext) -> set[str]:
    """The sheet 'User' names linked to the CALLER's account (employee catalog).

    Alias rows (merge memory — e.g. the retired "Usman" spelling pointing at
    "usman") stay linked to the account but are NOT identities: including them
    used to make labels[0] a capitalized ghost that owns zero rows, blanking
    the person's dashboard and This-week strip. Only canonical rows count, and
    everything folds to lowercase (one person, whatever the capitalization)."""
    from app.models.employee import UserEmployeeMapping

    return {
        lbl.strip().lower()
        for lbl in (
            await db.execute(
                select(UserEmployeeMapping.sheet_user_label).where(
                    UserEmployeeMapping.workspace_id == ctx.workspace_id,
                    UserEmployeeMapping.user_id == ctx.user.id,
                    UserEmployeeMapping.canonical_label.is_(None),
                )
            )
        ).scalars().all()
        if lbl and lbl.strip()
    }


async def visible_labels(db: AsyncSession, ctx: AuthContext) -> set[str] | None:
    """People-visibility scoping for every people-facing view:

    * Admin — unrestricted (``None``).
    * Manager (TeamLead) / QA WITH team assignments — only those labels (a QA
      assigned to teams sees ONLY those teams' people, projects and work);
      with no assignments yet — unrestricted (so accounts keep working until
      the admin scopes them on the Team desk).
    * Viewer (standard user) — ONLY their own linked label(s); an empty set
      means they see nobody but themselves once linked (never the whole team).
    """
    from app.core.rbac import Role

    if ctx.role == Role.VIEWER:
        return await own_labels(db, ctx)
    if ctx.role not in (Role.MANAGER, Role.QA):
        return None
    rows = (
        await db.execute(
            select(TeamLeadAssignment.member_label).where(
                TeamLeadAssignment.workspace_id == ctx.workspace_id,
                TeamLeadAssignment.manager_user_id == ctx.user.id,
            )
        )
    ).scalars().all()
    return set(rows) or None


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
    scope = await visible_labels(db, ctx)
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
            if scope is None or o.user_label in scope
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
                workspace_id=ctx.workspace_id,
                user_label=user_label.strip().lower()[:200],  # labels are stored lowercase (owner rule)
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


async def delete_productivity_override(
    db: AsyncSession, ctx: AuthContext, *, user_label: str, link_type_name: str
) -> None:
    """Remove a per-user override — that user falls back to the global rate."""
    await db.execute(
        delete(UserProductivityOverride).where(
            UserProductivityOverride.workspace_id == ctx.workspace_id,
            UserProductivityOverride.user_label == user_label.strip()[:200],
            UserProductivityOverride.link_type_name == link_type_name.strip()[:80],
        )
    )
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
    # Labels are case-insensitive people ("KEVIN" == "Kevin") — the override for
    # one spelling MUST apply to every spelling, so both sides key on .lower().
    o = {
        (r.user_label.lower(), r.link_type_name.lower()): float(r.links_per_hour)
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
        lph = o.get((user_label.lower(), key), g.get(key, _DEFAULT_LPH))
        total += per_type_hours * lph
    return int(round(total))


# ── Assignments ──────────────────────────────────────────────────────────────
# A normal working day; assignments beyond this trigger an over-allocation
# warning (never a hard block — owners decide).
WORKDAY_HOURS = 8.0

_PRIORITIES = ("high", "medium", "low")


async def upsert_assignment(
    db: AsyncSession, ctx: AuthContext, *, project_id: uuid.UUID, user_label: str,
    day: date, hours: float, link_type_names: list[str],
    expected_links: int | None = None, note: str | None = None,
    priority: str | None = None,
) -> tuple[TaskAssignment, list[str]]:
    """Create/update one plan row. Snapshots WHICH rate produced the target
    (manual | override | global) and returns plain-English warnings (leave,
    non-working day, over-allocation) the UI surfaces as toasts."""
    ctx.assert_project(project_id)
    if hours < 0 or hours > 24:
        raise ValidationAppError("Hours must be between 0 and 24.")
    label = user_label.strip().lower()[:200]  # labels are stored lowercase (owner rule)
    if not label:
        raise ValidationAppError("User is required.")
    if priority and priority not in _PRIORITIES:
        raise ValidationAppError("Priority must be high, medium or low.")
    types = [t.strip()[:80] for t in link_type_names if t.strip()][:12]

    g, o = await _lph_map(db, ctx.workspace_id)
    if expected_links is None:
        expected_links = _expected(hours, types, label, g, o)
        used_override = any((label.lower(), t.lower()) in o for t in types)
        rate_source = "override" if used_override else "global"
    else:
        rate_source = "manual"
    lph_used = round(expected_links / hours, 1) if hours > 0 else None

    stmt = (
        pg_insert(TaskAssignment)
        .values(
            workspace_id=ctx.workspace_id, project_id=project_id, user_label=label,
            day=day, hours=hours, link_type_names=types,
            expected_links=max(0, int(expected_links)),
            rate_source=rate_source, lph_used=lph_used,
            priority=priority or None,
            note=(note or "")[:300] or None,
            created_by=ctx.user.id,
        )
        .on_conflict_do_update(
            constraint="uq_task_ws_proj_user_day",
            set_={
                "hours": hours, "link_type_names": types,
                "expected_links": max(0, int(expected_links)),
                "rate_source": rate_source, "lph_used": lph_used,
                "priority": priority or None,
                "note": (note or "")[:300] or None, "created_by": ctx.user.id,
            },
        )
        .returning(TaskAssignment.id)
    )
    row_id = (await db.execute(stmt)).scalar_one()
    await db.flush()
    row = await db.get(TaskAssignment, row_id)

    # Smart warnings — informational, never blocking.
    warnings: list[str] = []
    override = (
        await db.execute(
            select(WorkingDay.is_working).where(
                WorkingDay.workspace_id == ctx.workspace_id, WorkingDay.day == day
            )
        )
    ).scalar_one_or_none()
    working = override if override is not None else _default_working(day)
    if not working:
        warnings.append(
            f"{day.isoformat()} is a non-working day — this plan won't count against "
            f"{label} unless the calendar changes."
        )
    on_leave = (
        await db.execute(
            select(LeaveRequest.id).where(
                LeaveRequest.workspace_id == ctx.workspace_id,
                LeaveRequest.user_label == label,
                LeaveRequest.status == "approved",
                LeaveRequest.start_date <= day,
                LeaveRequest.end_date >= day,
            ).limit(1)
        )
    ).scalar_one_or_none()
    if on_leave is not None:
        warnings.append(f"{label} has APPROVED LEAVE on {day.isoformat()} — the plan is excused.")
    total_hours = (
        await db.execute(
            select(func.coalesce(func.sum(TaskAssignment.hours), 0)).where(
                TaskAssignment.workspace_id == ctx.workspace_id,
                TaskAssignment.user_label == label,
                TaskAssignment.day == day,
            )
        )
    ).scalar_one()
    if float(total_hours) > WORKDAY_HOURS:
        warnings.append(
            f"{label} now has {float(total_hours):g}h assigned on {day.isoformat()} "
            f"(more than a {WORKDAY_HOURS:g}h workday) — check the plan."
        )
    return row, warnings


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
    elif ctx.allowed_project_ids is not None:
        # Project-scoped members only ever see plans for their own projects.
        stmt = stmt.where(
            TaskAssignment.project_id.in_(ctx.allowed_project_ids or {uuid.uuid4()})
        )
    if user_label:
        stmt = stmt.where(TaskAssignment.user_label == user_label)
    rows = (
        await db.execute(stmt.order_by(TaskAssignment.day.desc(), TaskAssignment.user_label))
    ).scalars().all()
    scope = await visible_labels(db, ctx)
    if scope is not None:
        rows = [r for r in rows if r.user_label in scope]
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

    # Actual links per (project, user, day) in one query. Range predicates (not
    # ::date casts) keep the (workspace_id, created_at) index usable at scale.
    actuals: dict[tuple, int] = {}
    result = await db.execute(
        text(
            """
            -- Attribute a link to its REAL creation/placement day (sheet-supplied),
            -- falling back to import time only when the sheet gave no date.
            SELECT project_id, coalesce(nullif(assigned_user_label, ''), '(unassigned)') AS u,
                   coalesce(placement_date, created_at::date) AS d, count(*) AS n
            FROM backlink_records
            WHERE workspace_id = :ws
              AND coalesce(placement_date, created_at) >= :f
              AND coalesce(placement_date, created_at) < CAST(:t AS date) + INTERVAL '1 day'
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
                "priority": a.priority,
                "rate_source": a.rate_source,
                "lph_used": float(a.lph_used) if a.lph_used is not None else None,
                "note": a.note,
            }
        )
    return out


async def my_work(
    db: AsyncSession, ctx: AuthContext, *, date_from: date, date_to: date
) -> dict:
    """The caller's OWN work only — powers the standard-user dashboard. Safe for
    every role: rows are filtered to the labels linked to this account."""
    labels = sorted(await own_labels(db, ctx))
    if not labels:
        return {"labels": [], "rows": [], "leaves": []}
    label_set = set(labels)
    rows = [
        r
        for r in await day_report(db, ctx, date_from=date_from, date_to=date_to)
        if r["user_label"] in label_set
    ]
    leaves = (
        await db.execute(
            select(LeaveRequest)
            .where(
                LeaveRequest.workspace_id == ctx.workspace_id,
                LeaveRequest.user_label.in_(labels),
            )
            .order_by(LeaveRequest.created_at.desc())
            .limit(50)
        )
    ).scalars().all()
    return {
        "labels": labels,
        "rows": rows,
        "leaves": [
            {
                "id": str(l.id), "user_label": l.user_label,
                "start_date": l.start_date.isoformat(), "end_date": l.end_date.isoformat(),
                "reason": l.reason, "status": l.status,
            }
            for l in leaves
        ],
    }


async def known_labels(db: AsyncSession, ctx: AuthContext) -> list[str]:
    """Every person the caller may plan for: ACTIVE employee catalog labels plus
    anyone already appearing in assignments — laid-off people are excluded
    (their history stays; they just leave the pickers). TeamLead scoping applied."""
    from app.models.employee import UserEmployeeMapping

    # Case-insensitive by construction: every label is folded to lowercase so
    # "Usman" and "usman" are ONE person everywhere (sheets store lowercase;
    # this guards any legacy row that slipped through).
    labels = {
        lbl.strip().lower()
        for lbl in (
            await db.execute(
                select(UserEmployeeMapping.sheet_user_label).where(
                    UserEmployeeMapping.workspace_id == ctx.workspace_id,
                    UserEmployeeMapping.is_active.is_(True),
                    # Alias rows (merge memory, canonical_label set) aren't people.
                    UserEmployeeMapping.canonical_label.is_(None),
                )
            )
        ).scalars().all()
        if lbl and lbl.strip()
    }
    labels |= {
        lbl.strip().lower()
        for lbl in (
            await db.execute(
                select(TaskAssignment.user_label)
                .where(TaskAssignment.workspace_id == ctx.workspace_id)
                .distinct()
            )
        ).scalars().all()
        if lbl and lbl.strip()
    }
    # Anyone who has ever been credited a backlink is a real person to show/plan
    # for — even without an employee-catalog row (e.g. a sheet-only name).
    from app.models.backlink import BacklinkRecord

    labels |= {
        lbl.strip().lower()
        for lbl in (
            await db.execute(
                select(BacklinkRecord.assigned_user_label)
                .where(BacklinkRecord.workspace_id == ctx.workspace_id)
                .distinct()
            )
        ).scalars().all()
        if lbl and lbl.strip()
    }
    # Laid-off labels leave the pickers even if they have past assignments.
    # Only CATALOG rows count — a deactivated alias spelling must never hide
    # the real (lowercase) person it was merged into.
    inactive = {
        lbl.strip().lower()
        for lbl in (
            await db.execute(
                select(UserEmployeeMapping.sheet_user_label).where(
                    UserEmployeeMapping.workspace_id == ctx.workspace_id,
                    UserEmployeeMapping.is_active.is_(False),
                    UserEmployeeMapping.canonical_label.is_(None),
                )
            )
        ).scalars().all()
        if lbl and lbl.strip()
    }
    labels -= inactive
    scope = await visible_labels(db, ctx)
    if scope is not None:
        labels &= {s.strip().lower() for s in scope}
    return sorted(labels, key=str.lower)


async def all_people(
    db: AsyncSession, ctx: AuthContext, *, project_id: uuid.UUID | None = None
) -> list[dict]:
    """Everyone to show in the User Dashboards grid (a VIEW, not a planning picker),
    so laid-off people with real work still appear. Each flagged ``active``
    (False = laid off). TeamLead-scoped.

    * Workspace scope (``project_id=None``): employee-catalog labels (active OR
      inactive) ∪ task assignments ∪ any backlink assignee.
    * Project scope: people who WORKED on the project (its backlink assignees +
      task assignments) ∪ people ASSIGNED to it (project_members → their sheet
      label) even if they never logged a link there."""
    from app.models.backlink import BacklinkRecord
    from app.models.employee import UserEmployeeMapping
    from app.models.project import ProjectMember

    # Laid-off = inactive CATALOG rows only. Alias rows (canonical_label set —
    # the merge memory for old spellings like "Tony"→tony) are NOT people and
    # must never appear as ghost "laid off" duplicates. Case-insensitive: one
    # person, whatever the capitalization anywhere in the data.
    inactive = {
        (lbl or "").strip().lower()
        for lbl in (
            await db.execute(
                select(UserEmployeeMapping.sheet_user_label).where(
                    UserEmployeeMapping.workspace_id == ctx.workspace_id,
                    UserEmployeeMapping.is_active.is_(False),
                    UserEmployeeMapping.canonical_label.is_(None),
                )
            )
        ).scalars().all()
        if lbl and lbl.strip()
    }

    labels: set[str] = set()
    if project_id is not None:
        ctx.assert_project(project_id)
        stmts = [
            select(BacklinkRecord.assigned_user_label).where(
                BacklinkRecord.workspace_id == ctx.workspace_id,
                BacklinkRecord.project_id == project_id,
            ).distinct(),
            select(TaskAssignment.user_label).where(
                TaskAssignment.workspace_id == ctx.workspace_id,
                TaskAssignment.project_id == project_id,
            ).distinct(),
            # Assigned to the project (member) but maybe never logged a link there.
            select(UserEmployeeMapping.sheet_user_label)
            .join(ProjectMember, ProjectMember.user_id == UserEmployeeMapping.user_id)
            .where(
                UserEmployeeMapping.workspace_id == ctx.workspace_id,
                UserEmployeeMapping.canonical_label.is_(None),
                ProjectMember.project_id == project_id,
            ),
        ]
    else:
        stmts = [
            select(UserEmployeeMapping.sheet_user_label).where(
                UserEmployeeMapping.workspace_id == ctx.workspace_id,
                UserEmployeeMapping.canonical_label.is_(None),
            ),
            select(TaskAssignment.user_label).where(
                TaskAssignment.workspace_id == ctx.workspace_id
            ).distinct(),
            select(BacklinkRecord.assigned_user_label).where(
                BacklinkRecord.workspace_id == ctx.workspace_id
            ).distinct(),
        ]
    for stmt in stmts:
        labels |= {lbl.strip().lower() for lbl in (await db.execute(stmt)).scalars().all() if lbl and lbl.strip()}

    scope = await visible_labels(db, ctx)
    if scope is not None:
        labels &= {s.strip().lower() for s in scope}
    return [
        {"user_label": lbl, "active": lbl not in inactive}
        for lbl in sorted(labels, key=str.lower)
    ]


# ── Weekly templates (set the week up ONCE) ──────────────────────────────────
def _monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


async def save_week_as_template(
    db: AsyncSession, ctx: AuthContext, *, week_start: date
) -> int:
    """Capture the given week's assignments as the standing weekly template
    (replaces the previous template). Laid-off people are skipped."""
    from sqlalchemy import delete as sa_delete

    from app.models.workforce import TaskWeekTemplate

    monday = _monday_of(week_start)
    rows = (
        await db.execute(
            select(TaskAssignment).where(
                TaskAssignment.workspace_id == ctx.workspace_id,
                TaskAssignment.day >= monday,
                TaskAssignment.day <= monday + timedelta(days=6),
            )
        )
    ).scalars().all()
    if not rows:
        raise ValidationAppError("That week has no assignments to save as a template.")
    await db.execute(
        sa_delete(TaskWeekTemplate).where(TaskWeekTemplate.workspace_id == ctx.workspace_id)
    )
    active = set(await known_labels(db, ctx))
    saved = 0
    for a in rows:
        if a.user_label not in active:
            continue
        db.add(
            TaskWeekTemplate(
                workspace_id=ctx.workspace_id, user_label=a.user_label,
                weekday=a.day.weekday(), project_id=a.project_id,
                hours=float(a.hours), link_type_names=a.link_type_names or [],
                priority=a.priority, note=a.note, created_by=ctx.user.id,
            )
        )
        saved += 1
    await db.flush()
    return saved


async def apply_template_to_week(
    db: AsyncSession, ctx: AuthContext, *, week_start: date,
    mode: str = "week", clear: bool = True,
    range_from: date | None = None, range_to: date | None = None,
    preview: bool = False,
) -> dict:
    """Materialize the standing weekly template into real assignments and OVERRIDE
    whatever was there.

    ``mode="week"`` targets the given week; ``mode="month"`` targets the entire
    NEXT calendar month (relative to ``week_start``). When ``clear`` (default), all
    existing assignments for the target days (today onward — history is immutable)
    are deleted first, so the template becomes the single source of truth for that
    range. Targets recompute from CURRENT productivity rates."""
    import calendar as _cal
    from sqlalchemy import delete as sa_delete

    from app.models.workforce import TaskAssignment, TaskWeekTemplate

    monday = _monday_of(week_start)
    tpl = (
        await db.execute(
            select(TaskWeekTemplate).where(
                TaskWeekTemplate.workspace_id == ctx.workspace_id
            )
        )
    ).scalars().all()
    if not tpl:
        raise ValidationAppError(
            "No weekly template yet — set one week up, then use “Save week as template”."
        )

    today = date.today()
    if mode == "range" and range_from and range_to:
        if range_to < range_from:
            raise ValidationAppError("The end date must be after the start date.")
        span = (range_to - range_from).days + 1
        if span > 120:
            raise ValidationAppError("Custom ranges are capped at 120 days — apply in chunks.")
        days = [range_from + timedelta(days=i) for i in range(span)]
        range_label = f"{range_from.isoformat()} → {range_to.isoformat()}"
    elif mode == "month":
        y = monday.year + (1 if monday.month == 12 else 0)
        m = 1 if monday.month == 12 else monday.month + 1
        ndays = _cal.monthrange(y, m)[1]
        days = [date(y, m, d) for d in range(1, ndays + 1)]
        range_label = f"{y}-{m:02d}"
    else:
        days = [monday + timedelta(days=i) for i in range(7)]
        range_label = f"week of {monday.isoformat()}"
    future_days = [d for d in days if d >= today]  # never rewrite the past

    tpl_by_weekday: dict[int, list] = {}
    for t in tpl:
        tpl_by_weekday.setdefault(t.weekday, []).append(t)
    active = set(await known_labels(db, ctx))

    if preview:
        # Dry run — the exact numbers the confirm dialog shows, nothing written.
        would_create = 0
        people: set[str] = set()
        for d in future_days:
            for t in tpl_by_weekday.get(d.weekday(), []):
                if t.user_label in active:
                    would_create += 1
                    people.add(t.user_label)
        existing = (
            await db.execute(
                select(func.count()).select_from(TaskAssignment).where(
                    TaskAssignment.workspace_id == ctx.workspace_id,
                    TaskAssignment.day.in_(future_days or [today]),
                )
            )
        ).scalar_one() if future_days else 0
        return {
            "preview": True, "range": range_label,
            "days": len(future_days), "people": len(people),
            "would_create": would_create,
            "would_replace": int(existing) if clear else 0,
        }

    cleared = 0
    if clear and future_days:
        res = await db.execute(
            sa_delete(TaskAssignment).where(
                TaskAssignment.workspace_id == ctx.workspace_id,
                TaskAssignment.day.in_(future_days),
            )
        )
        cleared = res.rowcount or 0

    applied = skipped = 0
    all_warnings: list[str] = []
    for d in future_days:
        for t in tpl_by_weekday.get(d.weekday(), []):
            if t.user_label not in active:
                skipped += 1
                continue
            _, warnings = await upsert_assignment(
                db, ctx, project_id=t.project_id, user_label=t.user_label, day=d,
                hours=float(t.hours), link_type_names=t.link_type_names or [],
                priority=t.priority, note=t.note,
            )
            all_warnings.extend(warnings)
            applied += 1
    return {
        "applied": applied, "cleared": cleared, "skipped_inactive": skipped,
        "range": range_label, "warnings": all_warnings[:6],
    }


async def upsert_template_entry(
    db: AsyncSession, ctx: AuthContext, *, user_label: str, weekday: int,
    project_id: uuid.UUID, hours: float, link_type_names: list[str],
    priority: str | None = None, note: str | None = None,
    expected_links: int | None = None,
) -> dict:
    """Upsert ONE standing-plan cell (person × weekday × project), then
    materialize it into the current week AND the next 3 weeks immediately (4 weeks
    total) — so a standing plan is visible a month ahead without waiting for the
    beat job. Past days of the current week are never rewritten (history stays)."""
    from app.models.workforce import TaskWeekTemplate

    ctx.assert_project(project_id)
    if weekday < 0 or weekday > 6:
        raise ValidationAppError("Weekday must be between 0 (Monday) and 6 (Sunday).")
    if hours < 0 or hours > 24:
        raise ValidationAppError("Hours must be between 0 and 24.")
    label = user_label.strip().lower()[:200]  # labels are stored lowercase (owner rule)
    if not label:
        raise ValidationAppError("User is required.")
    if priority and priority not in _PRIORITIES:
        raise ValidationAppError("Priority must be high, medium or low.")
    types = [t.strip()[:80] for t in link_type_names if t.strip()][:12]

    stmt = (
        pg_insert(TaskWeekTemplate)
        .values(
            workspace_id=ctx.workspace_id, user_label=label, weekday=weekday,
            project_id=project_id, hours=hours, link_type_names=types,
            priority=priority or None, note=(note or "")[:300] or None,
            created_by=ctx.user.id,
        )
        .on_conflict_do_update(
            constraint="uq_task_template_ws_user_day_proj",
            set_={
                "hours": hours, "link_type_names": types,
                "priority": priority or None,
                "note": (note or "")[:300] or None, "created_by": ctx.user.id,
            },
        )
    )
    await db.execute(stmt)

    today = date.today()
    this_monday = _monday_of(today)
    materialized: list[str] = []
    all_warnings: list[str] = []
    for wk in range(4):  # this week + next 3 (a month ahead)
        monday = this_monday + timedelta(days=7 * wk)
        day = monday + timedelta(days=weekday)
        if day < today:
            continue  # already-passed day of the current week — leave it alone
        _, warnings = await upsert_assignment(
            db, ctx, project_id=project_id, user_label=label, day=day,
            hours=hours, link_type_names=types, expected_links=expected_links,
            priority=priority, note=note,
        )
        all_warnings.extend(warnings)
        materialized.append(day.isoformat())
    return {"materialized_days": materialized, "warnings": all_warnings[:6]}


async def delete_template_entry(
    db: AsyncSession, ctx: AuthContext, *, user_label: str, weekday: int,
    project_id: uuid.UUID, remove_assignments: bool = True,
) -> dict:
    """Remove ONE standing-plan cell and (optionally) the assignments it
    materialized for the current and next week — future days only, past days
    are immutable history."""
    from sqlalchemy import delete as sa_delete

    from app.models.workforce import TaskWeekTemplate

    ctx.assert_project(project_id)
    if weekday < 0 or weekday > 6:
        raise ValidationAppError("Weekday must be between 0 (Monday) and 6 (Sunday).")
    label = user_label.strip().lower()[:200]  # labels are stored lowercase (owner rule)
    result = await db.execute(
        sa_delete(TaskWeekTemplate).where(
            TaskWeekTemplate.workspace_id == ctx.workspace_id,
            TaskWeekTemplate.user_label == label,
            TaskWeekTemplate.weekday == weekday,
            TaskWeekTemplate.project_id == project_id,
        )
    )
    removed = 0
    if remove_assignments:
        today = date.today()
        this_monday = _monday_of(today)
        days = [
            m + timedelta(days=weekday)
            for m in (this_monday, this_monday + timedelta(days=7))
        ]
        days = [d for d in days if d >= today]  # never touch past days
        if days:
            res = await db.execute(
                sa_delete(TaskAssignment).where(
                    TaskAssignment.workspace_id == ctx.workspace_id,
                    TaskAssignment.project_id == project_id,
                    TaskAssignment.user_label == label,
                    TaskAssignment.day.in_(days),
                )
            )
            removed = res.rowcount or 0
    await db.flush()
    return {"deleted": result.rowcount or 0, "assignments_removed": removed}


async def auto_apply_templates(db: AsyncSession) -> dict:
    """Beat job: keep the next 4 weeks' plans materialized from every workspace's
    weekly template so a standing plan always shows a month ahead. Fill-gaps only
    (ON CONFLICT DO NOTHING) — a manually adjusted future plan is never overwritten."""
    from app.models.employee import UserEmployeeMapping
    from app.models.workforce import TaskWeekTemplate

    this_monday = _monday_of(date.today())
    horizon = [this_monday + timedelta(days=7 * wk) for wk in range(1, 5)]  # next 4 weeks
    ws_ids = (
        await db.execute(select(TaskWeekTemplate.workspace_id).distinct())
    ).scalars().all()
    created = 0
    for ws in ws_ids:
        tpl = (
            await db.execute(
                select(TaskWeekTemplate).where(TaskWeekTemplate.workspace_id == ws)
            )
        ).scalars().all()
        inactive = set(
            (
                await db.execute(
                    select(UserEmployeeMapping.sheet_user_label).where(
                        UserEmployeeMapping.workspace_id == ws,
                        UserEmployeeMapping.is_active.is_(False),
                    )
                )
            ).scalars().all()
        )
        g, o = await _lph_map(db, ws)
        for monday in horizon:
            for t in tpl:
                if t.user_label in inactive:
                    continue
                types = list(t.link_type_names or [])
                hours = float(t.hours)
                expected = _expected(hours, types, t.user_label, g, o)
                used_override = any((t.user_label.lower(), x.lower()) in o for x in types)
                stmt = (
                    pg_insert(TaskAssignment)
                    .values(
                        workspace_id=ws, project_id=t.project_id, user_label=t.user_label,
                        day=monday + timedelta(days=t.weekday), hours=hours,
                        link_type_names=types, expected_links=max(0, expected),
                        rate_source="override" if used_override else "global",
                        lph_used=round(expected / hours, 1) if hours > 0 else None,
                        priority=t.priority, note=t.note, created_by=t.created_by,
                    )
                    .on_conflict_do_nothing(constraint="uq_task_ws_proj_user_day")
                )
                result = await db.execute(stmt)
                created += result.rowcount or 0
    await db.commit()
    return {"weeks": [m.isoformat() for m in horizon], "assignments_created": created}


async def template_summary(db: AsyncSession, ctx: AuthContext) -> dict:
    from app.models.workforce import TaskWeekTemplate

    rows = (
        await db.execute(
            select(
                TaskWeekTemplate.user_label,
                func.count(TaskWeekTemplate.id),
                func.coalesce(func.sum(TaskWeekTemplate.hours), 0),
            )
            .where(TaskWeekTemplate.workspace_id == ctx.workspace_id)
            .group_by(TaskWeekTemplate.user_label)
            .order_by(TaskWeekTemplate.user_label)
        )
    ).all()
    return {
        "users": [
            {"user_label": u, "entries": int(n), "week_hours": float(h)} for u, n, h in rows
        ],
        "total_entries": sum(int(n) for _, n, _ in rows),
    }


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
    label = user_label.strip().lower()[:200]  # labels are stored lowercase (owner rule)
    # Standard users can only request leave for THEMSELVES — no filing under
    # someone else's name. Admins/TeamLeads may file for anyone they manage.
    from app.core.rbac import Permission, has_permission

    if not has_permission(ctx.role, Permission.ASSIGN_MEMBERS):
        mine = await own_labels(db, ctx)
        if not mine:
            raise ValidationAppError(
                "Your account isn't linked to a team member name yet — "
                "ask your admin to link you on the Employees desk."
            )
        matched = next((m for m in mine if m.lower() == label.lower()), None)
        label = matched or sorted(mine)[0]
    row = LeaveRequest(
        workspace_id=ctx.workspace_id, user_label=label,
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
    rows = list((await db.execute(stmt)).scalars().all())
    scope = await visible_labels(db, ctx)
    if scope is not None:
        rows = [r for r in rows if r.user_label in scope]
    return rows


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
