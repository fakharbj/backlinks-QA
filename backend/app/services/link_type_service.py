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
    # Merged-away spellings pointing at each master — shown as the master's
    # aliases so admins can SEE that a merge took (and what folds into what).
    alias_rows = (
        await db.execute(
            select(LinkType.merged_into_id, LinkType.name)
            .where(
                LinkType.workspace_id == ctx.workspace_id,
                LinkType.merged_into_id.is_not(None),
            )
            .order_by(LinkType.name.asc())
        )
    ).all()
    aliases: dict[uuid.UUID, list[str]] = {}
    for master_id, alias_name in alias_rows:
        aliases.setdefault(master_id, []).append(alias_name)
    return [
        {
            "id": t.id, "name": t.name, "slug": t.slug, "color": t.color,
            "description": t.description, "is_active": t.is_active,
            "backlink_count": int(counts.get(t.id, 0)),
            "aliases": aliases.get(t.id, []),
        }
        for t in types
    ]


async def create_type(db: AsyncSession, ctx: AuthContext, name: str, color=None, description=None) -> LinkType:
    """Get-or-create THROUGH the alias layer. Re-adding a merged-away spelling
    must return the surviving master (never re-split a merge), and re-adding a
    plainly deleted type restores it — the slug is unique per workspace, so a
    blind INSERT here would violate uq_link_types_ws_slug and 500."""
    lt = await resolve_canonical(db, ctx.workspace_id, name)
    if lt is None:
        raise ConflictError("Link type name cannot be empty")
    if color is not None and not lt.color:
        lt.color = color
    if description is not None and not lt.description:
        lt.description = description
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
    lt = await resolve_canonical(db, workspace_id, name, cache=None)
    if lt is None:
        return None
    if cache is not None:
        cache[f"{workspace_id}:{slugify(name)}"] = lt.id
    return lt.id


async def resolve_canonical(
    db: AsyncSession, workspace_id: uuid.UUID, name: str,
    cache: dict[str, "LinkType"] | None = None,
) -> LinkType | None:
    """Free-text link type → the CANONICAL catalog row (get-or-create).

    Follows ``merged_into_id`` redirects so a sheet still carrying a merged-away
    tab name resolves to the surviving master (and its corrected NAME — callers
    store ``.name`` as the denormalized string, which is how misspellings stop
    re-entering the system). A plainly soft-deleted type (no merge target) is
    restored rather than duplicated — the slug is unique, and "the sheet still
    uses it" outranks a stale deletion."""
    name = (name or "").strip()
    if not name:
        return None
    slug = slugify(name)
    key = f"{workspace_id}:{slug}"
    if cache is not None and key in cache:
        return cache[key]
    lt = (
        await db.execute(
            select(LinkType)
            .where(LinkType.workspace_id == workspace_id, LinkType.slug == slug)
            .order_by(LinkType.deleted_at.is_(None).desc(), LinkType.created_at.asc())
            .limit(1)
        )
    ).scalars().first()
    if lt is None:
        lt = LinkType(workspace_id=workspace_id, name=name, slug=slug)
        db.add(lt)
        await db.flush()
    else:
        # Follow merge redirects (bounded — cycles are prevented at merge time).
        hops = 0
        while lt.merged_into_id is not None and hops < 10:
            target = await db.get(LinkType, lt.merged_into_id)
            if target is None or target.workspace_id != workspace_id:
                break
            lt = target
            hops += 1
        if lt.deleted_at is not None and lt.merged_into_id is None:
            lt.deleted_at = None
            lt.deleted_by = None
            lt.is_active = True
            await db.flush()
    if cache is not None:
        cache[key] = lt
    return lt
