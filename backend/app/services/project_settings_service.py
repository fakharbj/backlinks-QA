"""Project settings + main domain logic (Phase 8, feature 2).

``normalize_domain_input`` is a pure helper (unit-tested) that accepts a bare
domain or a full URL and returns its registrable domain (or None). The rest is
tenant/project-scoped CRUD that keeps exactly one primary domain per project.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import AuthContext
from app.core.errors import ConflictError, NotFoundError, ValidationAppError
from app.crawler.normalize import normalize_url, registrable_domain
from app.models.project import Project
from app.models.project_settings import ProjectDomain, ProjectSettings
from app.schemas.project_settings import ProjectDomainCreate, ProjectSettingsUpdate


def normalize_domain_input(raw: str) -> str | None:
    """Accept a domain or URL → registrable domain (lowercased), or None if invalid."""
    value = (raw or "").strip().lower()
    if not value:
        return None
    if "://" in value:
        parsed = normalize_url(value)
        return parsed.registrable_domain or None if parsed.valid else None
    host = value.split("/", 1)[0].strip()
    if "." not in host or " " in host:
        return None
    return registrable_domain(host) or None


async def ensure_primary_from_target(
    db: AsyncSession, workspace_id: uuid.UUID, project_id: uuid.UUID, target_domain: str | None
) -> bool:
    """Reflect a project's ``target_domain`` (the Quick-Edit field) into its
    Main domains (the ``ProjectDomain`` list that QA/reports/analytics use):
    add the refined domain if it isn't there yet, and make it primary when the
    project has no primary. Never overrides an existing primary. No-op for a
    blank/invalid target. Returns True if it changed anything."""
    domain = normalize_domain_input(target_domain or "")
    if not domain:
        return False
    existing = (
        await db.execute(
            select(ProjectDomain).where(
                ProjectDomain.project_id == project_id, ProjectDomain.domain == domain
            )
        )
    ).scalar_one_or_none()
    has_primary = (
        await db.execute(
            select(ProjectDomain.id).where(
                ProjectDomain.project_id == project_id, ProjectDomain.is_primary.is_(True)
            ).limit(1)
        )
    ).scalar_one_or_none()
    if existing is None:
        db.add(ProjectDomain(
            workspace_id=workspace_id, project_id=project_id,
            domain=domain, is_primary=(has_primary is None),
        ))
        await db.flush()
        return True
    if has_primary is None:
        existing.is_primary = True
        await db.flush()
        return True
    return False


async def _ensure_project(db: AsyncSession, ctx: AuthContext, project_id: uuid.UUID) -> Project:
    project = await db.get(Project, project_id)
    if project is None or project.workspace_id != ctx.workspace_id:
        raise NotFoundError("Project not found")
    ctx.assert_project(project_id)
    return project


async def get_or_create_settings(
    db: AsyncSession, ctx: AuthContext, project_id: uuid.UUID
) -> ProjectSettings:
    await _ensure_project(db, ctx, project_id)
    settings = (
        await db.execute(select(ProjectSettings).where(ProjectSettings.project_id == project_id))
    ).scalar_one_or_none()
    if settings is None:
        settings = ProjectSettings(workspace_id=ctx.workspace_id, project_id=project_id)
        db.add(settings)
        await db.flush()
    return settings


async def list_domains(
    db: AsyncSession, ctx: AuthContext, project_id: uuid.UUID
) -> list[ProjectDomain]:
    await _ensure_project(db, ctx, project_id)
    return list(
        (
            await db.execute(
                select(ProjectDomain)
                .where(ProjectDomain.project_id == project_id)
                .order_by(ProjectDomain.is_primary.desc(), ProjectDomain.domain.asc())
            )
        ).scalars().all()
    )


async def update_settings(
    db: AsyncSession, ctx: AuthContext, project_id: uuid.UUID, payload: ProjectSettingsUpdate
) -> ProjectSettings:
    settings = await get_or_create_settings(db, ctx, project_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(settings, field, value)
    await db.flush()
    return settings


async def add_domain(
    db: AsyncSession, ctx: AuthContext, project_id: uuid.UUID, payload: ProjectDomainCreate
) -> ProjectDomain:
    await _ensure_project(db, ctx, project_id)
    domain = normalize_domain_input(payload.domain)
    if domain is None:
        raise ValidationAppError("Enter a valid domain, e.g. example.com")
    exists = (
        await db.execute(
            select(ProjectDomain).where(
                ProjectDomain.project_id == project_id, ProjectDomain.domain == domain
            )
        )
    ).scalar_one_or_none()
    if exists is not None:
        raise ConflictError("That domain is already on this project")
    # The first domain added becomes the primary automatically.
    has_any = (
        await db.execute(
            select(ProjectDomain.id).where(ProjectDomain.project_id == project_id).limit(1)
        )
    ).scalar_one_or_none()
    pd = ProjectDomain(
        workspace_id=ctx.workspace_id, project_id=project_id,
        domain=domain, is_primary=(has_any is None),
    )
    db.add(pd)
    await db.flush()
    return pd


async def remove_domain(
    db: AsyncSession, ctx: AuthContext, project_id: uuid.UUID, domain_id: uuid.UUID
) -> None:
    await _ensure_project(db, ctx, project_id)
    pd = await db.get(ProjectDomain, domain_id)
    if pd is None or pd.project_id != project_id:
        raise NotFoundError("Domain not found")
    was_primary = pd.is_primary
    await db.delete(pd)
    await db.flush()
    if was_primary:
        # Promote the next domain (alphabetical) so a project keeps a primary.
        nxt = (
            await db.execute(
                select(ProjectDomain)
                .where(ProjectDomain.project_id == project_id)
                .order_by(ProjectDomain.domain.asc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if nxt is not None:
            nxt.is_primary = True
            await db.flush()


async def set_primary(
    db: AsyncSession, ctx: AuthContext, project_id: uuid.UUID, domain_id: uuid.UUID
) -> ProjectDomain:
    await _ensure_project(db, ctx, project_id)
    pd = await db.get(ProjectDomain, domain_id)
    if pd is None or pd.project_id != project_id:
        raise NotFoundError("Domain not found")
    # Clear the current primary first so the partial unique index never sees two.
    await db.execute(
        update(ProjectDomain)
        .where(ProjectDomain.project_id == project_id, ProjectDomain.is_primary.is_(True))
        .values(is_primary=False)
    )
    pd.is_primary = True
    await db.flush()
    return pd
