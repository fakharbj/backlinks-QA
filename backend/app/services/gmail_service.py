"""Company Gmail accounts + assignments (Tranche H) — logic layer.

Workspace-scoped catalog of shared Gmail addresses and an append-only assignment
history (who/what an address is handed to). Reassigning an address to a new
owner closes the prior active assignment and opens a new one, so the history is
never lost. No live Gmail feed — ``last_used_at`` is a manual signal.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import AuthContext
from app.core.errors import NotFoundError, ValidationAppError
from app.models.gmail_account import (
    GMAIL_ACCOUNT_STATUSES,
    GMAIL_SCOPES,
    GmailAccount,
    GmailAssignment,
)
from app.models.project import Project
from app.models.user import User


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _account_dict(a: GmailAccount) -> dict:
    return {
        "id": str(a.id),
        "email": a.email,
        "display_name": a.display_name,
        "status": a.status,
        "is_active": a.is_active,
        "notes": a.notes,
        "last_used_at": a.last_used_at.isoformat() if a.last_used_at else None,
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }


async def _active_assignments(
    db: AsyncSession, ws: uuid.UUID, account_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[dict]]:
    """Active assignments per account, enriched with user/project display names."""
    if not account_ids:
        return {}
    rows = (
        await db.execute(
            select(
                GmailAssignment,
                User.full_name, User.email, Project.name,
            )
            .join(User, User.id == GmailAssignment.user_id, isouter=True)
            .join(Project, Project.id == GmailAssignment.project_id, isouter=True)
            .where(
                GmailAssignment.workspace_id == ws,
                GmailAssignment.gmail_account_id.in_(account_ids),
                GmailAssignment.status == "active",
            )
            .order_by(GmailAssignment.assigned_at.desc())
        )
    ).all()
    out: dict[uuid.UUID, list[dict]] = {}
    for asg, full_name, email, proj_name in rows:
        out.setdefault(asg.gmail_account_id, []).append(
            {
                "id": str(asg.id),
                "scope": asg.scope,
                "user_id": str(asg.user_id) if asg.user_id else None,
                "project_id": str(asg.project_id) if asg.project_id else None,
                "target_label": (
                    (full_name or email) if asg.scope == "user" else (proj_name or "—")
                ),
                "assigned_at": asg.assigned_at.isoformat() if asg.assigned_at else None,
                "notes": asg.notes,
            }
        )
    return out


async def list_accounts(db: AsyncSession, ctx: AuthContext, *, include_retired: bool = False) -> list[dict]:
    stmt = select(GmailAccount).where(GmailAccount.workspace_id == ctx.workspace_id)
    if not include_retired:
        stmt = stmt.where(GmailAccount.is_active.is_(True))
    accounts = list((await db.execute(stmt.order_by(GmailAccount.email.asc()))).scalars().all())
    assigns = await _active_assignments(db, ctx.workspace_id, [a.id for a in accounts])
    out = []
    for a in accounts:
        rows = assigns.get(a.id, [])
        d = _account_dict(a)
        d["assignments"] = rows
        d["user_count"] = sum(1 for r in rows if r["scope"] == "user")
        d["project_count"] = sum(1 for r in rows if r["scope"] == "project")
        out.append(d)
    return out


async def create_account(
    db: AsyncSession, ctx: AuthContext, *, email: str, display_name: str | None, notes: str | None
) -> dict:
    addr = (email or "").strip().lower()
    if "@" not in addr or len(addr) < 3:
        raise ValidationAppError("Enter a valid email address.")
    existing = (
        await db.execute(
            select(GmailAccount).where(
                GmailAccount.workspace_id == ctx.workspace_id, GmailAccount.email == addr
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        # Reuse (reactivate) instead of duplicating — mirrors branding/email reuse.
        existing.is_active = True
        if existing.status == "retired":
            existing.status = "active"
        if display_name is not None:
            existing.display_name = display_name.strip() or None
        if notes is not None:
            existing.notes = notes.strip() or None
        await db.flush()
        return _account_dict(existing)
    acc = GmailAccount(
        workspace_id=ctx.workspace_id, email=addr,
        display_name=(display_name or "").strip() or None,
        notes=(notes or "").strip() or None, status="active", is_active=True,
    )
    db.add(acc)
    await db.flush()
    return _account_dict(acc)


async def _load_account(db: AsyncSession, ctx: AuthContext, account_id: uuid.UUID) -> GmailAccount:
    a = await db.get(GmailAccount, account_id)
    if a is None or a.workspace_id != ctx.workspace_id:
        raise NotFoundError("Gmail account not found")
    return a


async def update_account(
    db: AsyncSession, ctx: AuthContext, account_id: uuid.UUID, *, patch: dict
) -> dict:
    a = await _load_account(db, ctx, account_id)
    if "display_name" in patch:
        a.display_name = (patch["display_name"] or "").strip() or None
    if "notes" in patch:
        a.notes = (patch["notes"] or "").strip() or None
    if "status" in patch and patch["status"] in GMAIL_ACCOUNT_STATUSES:
        a.status = patch["status"]
    if "is_active" in patch:
        a.is_active = bool(patch["is_active"])
    await db.flush()
    return _account_dict(a)


async def retire_account(db: AsyncSession, ctx: AuthContext, account_id: uuid.UUID) -> dict:
    """Soft-retire: keep the row + history, mark inactive, revoke live assignments."""
    a = await _load_account(db, ctx, account_id)
    a.is_active = False
    a.status = "retired"
    now = _now()
    live = (
        await db.execute(
            select(GmailAssignment).where(
                GmailAssignment.gmail_account_id == a.id, GmailAssignment.status == "active"
            )
        )
    ).scalars().all()
    for asg in live:
        asg.status = "revoked"
        asg.unassigned_at = now
    await db.flush()
    return {"message": f"Retired {a.email}", "revoked": len(live)}


async def mark_used(db: AsyncSession, ctx: AuthContext, account_id: uuid.UUID) -> dict:
    a = await _load_account(db, ctx, account_id)
    a.last_used_at = _now()
    await db.flush()
    return _account_dict(a)


async def assign(
    db: AsyncSession,
    ctx: AuthContext,
    *,
    account_id: uuid.UUID,
    scope: str,
    user_id: uuid.UUID | None,
    project_id: uuid.UUID | None,
    notes: str | None,
    actor_id: uuid.UUID | None,
) -> dict:
    """Hand an address to a user or a project. Closes any prior ACTIVE assignment
    for that same (account, target) pair, then opens a fresh one (history kept)."""
    a = await _load_account(db, ctx, account_id)
    if scope not in GMAIL_SCOPES:
        raise ValidationAppError("scope must be 'user' or 'project'.")
    if scope == "user":
        if not user_id:
            raise ValidationAppError("A user is required for a user assignment.")
        project_id = None
        target = (
            await db.execute(select(User).where(User.id == user_id))
        ).scalar_one_or_none()
        if target is None:
            raise ValidationAppError("User not found.")
    else:  # project
        if not project_id:
            raise ValidationAppError("A project is required for a project assignment.")
        ctx.assert_project(project_id)
        user_id = None

    # Close the prior active assignment for this exact pair (idempotent re-assign).
    now = _now()
    prior = (
        await db.execute(
            select(GmailAssignment).where(
                GmailAssignment.gmail_account_id == a.id,
                GmailAssignment.status == "active",
                (GmailAssignment.user_id == user_id) if scope == "user"
                else (GmailAssignment.project_id == project_id),
            )
        )
    ).scalars().all()
    for p in prior:
        p.status = "revoked"
        p.unassigned_at = now

    asg = GmailAssignment(
        workspace_id=ctx.workspace_id, gmail_account_id=a.id, scope=scope,
        user_id=user_id, project_id=project_id, assigned_by=actor_id,
        assigned_at=now, status="active", notes=(notes or "").strip() or None,
    )
    db.add(asg)
    await db.flush()
    return {"id": str(asg.id), "message": f"Assigned {a.email}"}


async def revoke(db: AsyncSession, ctx: AuthContext, assignment_id: uuid.UUID) -> dict:
    asg = await db.get(GmailAssignment, assignment_id)
    if asg is None or asg.workspace_id != ctx.workspace_id:
        raise NotFoundError("Assignment not found")
    if asg.status == "active":
        asg.status = "revoked"
        asg.unassigned_at = _now()
    await db.flush()
    return {"message": "Assignment revoked"}


async def _for(
    db: AsyncSession, ctx: AuthContext, *, user_id: uuid.UUID | None, project_id: uuid.UUID | None
) -> list[dict]:
    stmt = (
        select(GmailAssignment, GmailAccount)
        .join(GmailAccount, GmailAccount.id == GmailAssignment.gmail_account_id)
        .where(
            GmailAssignment.workspace_id == ctx.workspace_id,
            GmailAssignment.status == "active",
        )
    )
    if user_id is not None:
        stmt = stmt.where(GmailAssignment.user_id == user_id)
    if project_id is not None:
        stmt = stmt.where(GmailAssignment.project_id == project_id)
    rows = (await db.execute(stmt.order_by(GmailAssignment.assigned_at.desc()))).all()
    return [
        {
            "assignment_id": str(asg.id),
            "account_id": str(acc.id),
            "email": acc.email,
            "display_name": acc.display_name,
            "status": acc.status,
            "assigned_at": asg.assigned_at.isoformat() if asg.assigned_at else None,
            "last_used_at": acc.last_used_at.isoformat() if acc.last_used_at else None,
            "notes": asg.notes,
        }
        for asg, acc in rows
    ]


async def list_all_assignments(
    db: AsyncSession, ctx: AuthContext, *, status: str | None = None
) -> dict:
    """Flat, filterable list of EVERY assignment (for the detail table) — account,
    user, project, who assigned it, when, status, last used — plus summary stats."""
    stmt = (
        select(
            GmailAssignment, GmailAccount.email, GmailAccount.last_used_at,
            User.full_name, User.email, Project.name,
        )
        .join(GmailAccount, GmailAccount.id == GmailAssignment.gmail_account_id)
        .join(User, User.id == GmailAssignment.user_id, isouter=True)
        .join(Project, Project.id == GmailAssignment.project_id, isouter=True)
        .where(GmailAssignment.workspace_id == ctx.workspace_id)
    )
    if status in ("active", "revoked"):
        stmt = stmt.where(GmailAssignment.status == status)
    rows = (await db.execute(stmt.order_by(GmailAssignment.assigned_at.desc()))).all()
    # Resolve "assigned by" names in one lookup.
    actor_ids = {asg.assigned_by for asg, *_ in rows if asg.assigned_by}
    actors: dict[uuid.UUID, str] = {}
    if actor_ids:
        for uid, name, email in (
            await db.execute(
                select(User.id, User.full_name, User.email).where(User.id.in_(actor_ids))
            )
        ).all():
            actors[uid] = name or email
    items = []
    active_users: set[str] = set()
    active_projects: set[str] = set()
    for asg, acc_email, last_used, full_name, user_email, proj_name in rows:
        if asg.status == "active" and asg.scope == "user" and asg.user_id:
            active_users.add(str(asg.user_id))
        if asg.status == "active" and asg.scope == "project" and asg.project_id:
            active_projects.add(str(asg.project_id))
        items.append({
            "id": str(asg.id),
            "account_id": str(asg.gmail_account_id),
            "email": acc_email,
            "scope": asg.scope,
            "user_name": (full_name or user_email) if asg.scope == "user" else None,
            "project_name": proj_name if asg.scope == "project" else None,
            "assigned_by": actors.get(asg.assigned_by) if asg.assigned_by else None,
            "assigned_at": asg.assigned_at.isoformat() if asg.assigned_at else None,
            "unassigned_at": asg.unassigned_at.isoformat() if asg.unassigned_at else None,
            "status": asg.status,
            "last_used_at": last_used.isoformat() if last_used else None,
            "notes": asg.notes,
        })
    return {
        "items": items,
        "stats": {
            "total": len(items),
            "active": sum(1 for i in items if i["status"] == "active"),
            "revoked": sum(1 for i in items if i["status"] == "revoked"),
            "active_users": len(active_users),
            "active_projects": len(active_projects),
        },
    }


async def for_user(db: AsyncSession, ctx: AuthContext, user_id: uuid.UUID) -> list[dict]:
    return await _for(db, ctx, user_id=user_id, project_id=None)


async def for_project(db: AsyncSession, ctx: AuthContext, project_id: uuid.UUID) -> list[dict]:
    ctx.assert_project(project_id)
    return await _for(db, ctx, user_id=None, project_id=project_id)
