"""Project / vendor / campaign business logic with tenant + project scoping."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import AuthContext
from app.core.errors import ConflictError, NotFoundError
from app.core.utils import slugify
from app.models.project import Campaign, Project, ProjectMember, Vendor
from app.schemas.project import (
    CampaignCreate,
    ProjectCreate,
    ProjectUpdate,
    VendorCreate,
)


async def list_projects(db: AsyncSession, ctx: AuthContext) -> list[Project]:
    stmt = select(Project).where(Project.workspace_id == ctx.workspace_id)
    if ctx.allowed_project_ids is not None:
        stmt = stmt.where(Project.id.in_(ctx.allowed_project_ids or {uuid.uuid4()}))
    stmt = stmt.order_by(Project.created_at.desc())
    return list((await db.execute(stmt)).scalars().all())


async def get_project(db: AsyncSession, ctx: AuthContext, project_id: uuid.UUID) -> Project:
    project = await db.get(Project, project_id)
    if project is None or project.workspace_id != ctx.workspace_id:
        raise NotFoundError("Project not found")
    ctx.assert_project(project_id)
    return project


async def create_project(db: AsyncSession, ctx: AuthContext, payload: ProjectCreate) -> Project:
    slug = slugify(payload.name)
    clash = (
        await db.execute(
            select(Project.id).where(
                Project.workspace_id == ctx.workspace_id, Project.slug == slug
            )
        )
    ).scalar_one_or_none()
    if clash is not None:
        slug = f"{slug}-{uuid.uuid4().hex[:4]}"

    project = Project(
        workspace_id=ctx.workspace_id,
        name=payload.name,
        slug=slug,
        client_name=payload.client_name,
        target_domain=payload.target_domain,
        target_urls=payload.target_urls,
        campaign=payload.campaign,
        notes=payload.notes,
        tags=payload.tags,
        schedule_interval=payload.schedule_interval,
        treat_sponsored_as_follow=payload.treat_sponsored_as_follow,
    )
    db.add(project)
    await db.flush()
    # The target domain doubles as the project's primary Main domain (what QA,
    # reports and analytics use) — keep the two in sync from creation.
    if project.target_domain:
        from app.services import project_settings_service

        await project_settings_service.ensure_primary_from_target(
            db, ctx.workspace_id, project.id, project.target_domain
        )
    return project


async def update_project(
    db: AsyncSession, ctx: AuthContext, project_id: uuid.UUID, payload: ProjectUpdate
) -> Project:
    project = await get_project(db, ctx, project_id)
    was_active = getattr(project.status, "value", str(project.status)) == "active"
    fields = payload.model_dump(exclude_unset=True)
    for field, value in fields.items():
        setattr(project, field, value)
    now_active = getattr(project.status, "value", str(project.status)) == "active"
    if was_active and not now_active:
        await deactivation_cleanup(db, ctx.workspace_id, project.id)
    await db.flush()
    # Setting/changing the target domain (e.g. via Quick Edit) reflects into the
    # project's Main domains automatically — never overriding an existing primary.
    if "target_domain" in fields and project.target_domain:
        from app.services import project_settings_service

        await project_settings_service.ensure_primary_from_target(
            db, ctx.workspace_id, project.id, project.target_domain
        )
    await db.flush()
    return project


async def deactivation_cleanup(
    db: AsyncSession, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> None:
    """Deactivation side effects (owner rule): a paused/archived project's
    FUTURE planned tasks (today onward) leave task management immediately —
    past days stay untouched in every user's history. Its standing weekly
    template rows go too, so the automation never re-creates plans for it.
    Shared by the manual PATCH and the main-sheet Status column, so both
    paths deactivate identically."""
    from datetime import date as _date

    from sqlalchemy import delete as _delete

    from app.models.workforce import TaskAssignment, TaskWeekTemplate

    await db.execute(
        _delete(TaskAssignment).where(
            TaskAssignment.workspace_id == workspace_id,
            TaskAssignment.project_id == project_id,
            TaskAssignment.day >= _date.today(),
        )
    )
    await db.execute(
        _delete(TaskWeekTemplate).where(
            TaskWeekTemplate.workspace_id == workspace_id,
            TaskWeekTemplate.project_id == project_id,
        )
    )


async def delete_project(db: AsyncSession, ctx: AuthContext, project_id: uuid.UUID) -> None:
    """Delete a project and everything that belongs to it. Backlinks, imports,
    sheets and competitor sheets cascade via FKs; the tables below reference the
    project without an FK, so they're cleaned explicitly. Batches are KEPT as
    historical audit (their project shows as '—' afterwards)."""
    from sqlalchemy import text as _text

    project = await get_project(db, ctx, project_id)
    for table in (
        "task_assignments",
        "competitor_source_domains",
        "competitor_domain_decisions",
    ):
        await db.execute(
            _text(f"DELETE FROM {table} WHERE workspace_id = :ws AND project_id = :pid"),  # noqa: S608 — fixed table list
            {"ws": ctx.workspace_id, "pid": project_id},
        )
    await db.delete(project)


# ── Vendors ─────────────────────────────────────────────────────────────────────
async def list_vendors(db: AsyncSession, ctx: AuthContext) -> list[Vendor]:
    return list(
        (
            await db.execute(
                select(Vendor).where(Vendor.workspace_id == ctx.workspace_id).order_by(Vendor.name)
            )
        ).scalars().all()
    )


async def create_vendor(db: AsyncSession, ctx: AuthContext, payload: VendorCreate) -> Vendor:
    exists = (
        await db.execute(
            select(Vendor.id).where(
                Vendor.workspace_id == ctx.workspace_id, Vendor.name == payload.name
            )
        )
    ).scalar_one_or_none()
    if exists is not None:
        raise ConflictError("Vendor already exists")
    vendor = Vendor(workspace_id=ctx.workspace_id, **payload.model_dump())
    db.add(vendor)
    await db.flush()
    return vendor


async def get_or_create_vendor(
    db: AsyncSession, ctx: AuthContext, name: str
) -> Vendor:
    vendor = (
        await db.execute(
            select(Vendor).where(
                Vendor.workspace_id == ctx.workspace_id, Vendor.name == name
            )
        )
    ).scalar_one_or_none()
    if vendor is None:
        vendor = Vendor(workspace_id=ctx.workspace_id, name=name)
        db.add(vendor)
        await db.flush()
    return vendor


# ── Campaigns ────────────────────────────────────────────────────────────────────
async def list_campaigns(
    db: AsyncSession, ctx: AuthContext, project_id: uuid.UUID | None = None
) -> list[Campaign]:
    stmt = select(Campaign).where(Campaign.workspace_id == ctx.workspace_id)
    if project_id is not None:
        ctx.assert_project(project_id)
        stmt = stmt.where(Campaign.project_id == project_id)
    elif ctx.allowed_project_ids is not None:
        stmt = stmt.where(Campaign.project_id.in_(ctx.allowed_project_ids or {uuid.uuid4()}))
    return list((await db.execute(stmt.order_by(Campaign.name))).scalars().all())


async def create_campaign(db: AsyncSession, ctx: AuthContext, payload: CampaignCreate) -> Campaign:
    await get_project(db, ctx, payload.project_id)  # scope check
    campaign = Campaign(workspace_id=ctx.workspace_id, **payload.model_dump())
    db.add(campaign)
    await db.flush()
    return campaign


async def get_or_create_campaign(
    db: AsyncSession, ctx: AuthContext, project_id: uuid.UUID, name: str
) -> Campaign:
    campaign = (
        await db.execute(
            select(Campaign).where(
                Campaign.project_id == project_id, Campaign.name == name
            )
        )
    ).scalar_one_or_none()
    if campaign is None:
        campaign = Campaign(workspace_id=ctx.workspace_id, project_id=project_id, name=name)
        db.add(campaign)
        await db.flush()
    return campaign


async def add_member(
    db: AsyncSession, ctx: AuthContext, project_id: uuid.UUID, user_id: uuid.UUID, role: str | None
) -> ProjectMember:
    await get_project(db, ctx, project_id)
    from app.core.rbac import Role

    member = ProjectMember(
        project_id=project_id, user_id=user_id, role=Role(role) if role else None
    )
    db.add(member)
    await db.flush()
    return member
