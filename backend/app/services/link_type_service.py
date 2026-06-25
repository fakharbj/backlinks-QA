"""Link-type catalog logic (Phase 8).

CRUD + a ``resolve_or_create`` used by the import pipeline to turn the sheet's
free-text link type into a catalog ``link_type_id`` (cached per import run).
"""

from __future__ import annotations

import re
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import AuthContext
from app.core.errors import ConflictError, NotFoundError
from app.models.backlink import BacklinkRecord
from app.models.link_type import LinkType


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "").strip().lower()).strip("-")
    return (slug or "type")[:80]


async def list_types(db: AsyncSession, ctx: AuthContext) -> list[dict]:
    types = list(
        (
            await db.execute(
                select(LinkType)
                .where(LinkType.workspace_id == ctx.workspace_id, LinkType.deleted_at.is_(None))
                .order_by(LinkType.name.asc())
            )
        ).scalars().all()
    )
    counts = dict(
        (
            await db.execute(
                select(BacklinkRecord.link_type_id, func.count())
                .where(
                    BacklinkRecord.workspace_id == ctx.workspace_id,
                    BacklinkRecord.link_type_id.is_not(None),
                )
                .group_by(BacklinkRecord.link_type_id)
            )
        ).all()
    )
    return [
        {
            "id": t.id, "name": t.name, "slug": t.slug, "color": t.color,
            "description": t.description, "is_active": t.is_active,
            "backlink_count": int(counts.get(t.id, 0)),
        }
        for t in types
    ]


async def create_type(db: AsyncSession, ctx: AuthContext, name: str, color=None, description=None) -> LinkType:
    slug = slugify(name)
    exists = (
        await db.execute(
            select(LinkType).where(
                LinkType.workspace_id == ctx.workspace_id,
                LinkType.slug == slug,
                LinkType.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if exists is not None:
        raise ConflictError("A link type with that name already exists")
    lt = LinkType(
        workspace_id=ctx.workspace_id, name=name.strip(), slug=slug,
        color=color, description=description,
    )
    db.add(lt)
    await db.flush()
    return lt


async def _get(db: AsyncSession, ctx: AuthContext, type_id: uuid.UUID) -> LinkType:
    lt = await db.get(LinkType, type_id)
    if lt is None or lt.workspace_id != ctx.workspace_id or lt.deleted_at is not None:
        raise NotFoundError("Link type not found")
    return lt


async def update_type(db: AsyncSession, ctx: AuthContext, type_id: uuid.UUID, payload) -> LinkType:
    lt = await _get(db, ctx, type_id)
    data = payload.model_dump(exclude_unset=True)
    if "name" in data and data["name"]:
        lt.name = data["name"].strip()
        lt.slug = slugify(lt.name)
    for field in ("color", "description", "is_active"):
        if field in data:
            setattr(lt, field, data[field])
    await db.flush()
    return lt


async def delete_type(db: AsyncSession, ctx: AuthContext, type_id: uuid.UUID) -> None:
    from datetime import datetime, timezone

    lt = await _get(db, ctx, type_id)
    lt.deleted_at = datetime.now(timezone.utc)
    lt.deleted_by = ctx.user.id
    lt.is_active = False
    await db.flush()


async def resolve_or_create(
    db: AsyncSession, workspace_id: uuid.UUID, name: str, cache: dict[str, uuid.UUID] | None = None
) -> uuid.UUID | None:
    """Import helper: free-text link type → catalog id (get-or-create, cached)."""
    name = (name or "").strip()
    if not name:
        return None
    slug = slugify(name)
    key = f"{workspace_id}:{slug}"
    if cache is not None and key in cache:
        return cache[key]
    lt = (
        await db.execute(
            select(LinkType).where(LinkType.workspace_id == workspace_id, LinkType.slug == slug)
        )
    ).scalar_one_or_none()
    if lt is None:
        lt = LinkType(workspace_id=workspace_id, name=name, slug=slug)
        db.add(lt)
        await db.flush()
    if cache is not None:
        cache[key] = lt.id
    return lt.id
