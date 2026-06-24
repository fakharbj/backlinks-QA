"""Link identity resolution + duplicate classification (Phase 3).

Identity = ``(workspace_id, source_url_normalized, target_domain)`` keyed by a
sha256 hash. ``resolve_identity`` get-or-creates the identity for a backlink;
``recompute`` re-rolls the per-identity counts and stamps every mapped backlink
with ``duplicate_status`` + ``is_duplicate``. Only the identities touched by a
sync are recomputed, so this scales to millions of rows.

``classify_duplicate`` is a pure function (unit-tested) so the rule is verifiable
in isolation.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.backlink import BacklinkRecord
from app.models.link_identity import LinkIdentity

# duplicate_status values (kept as plain strings so the set stays dynamic).
UNIQUE = "unique"
DUP_CROSS_PROJECT = "dup_cross_project"
DUP_CROSS_USER = "dup_cross_user"
DUP_SAME_PROJECT = "dup_same_project"


def identity_key(workspace_id: uuid.UUID, source_url_normalized: str, target_domain: str) -> str:
    raw = f"{workspace_id}|{source_url_normalized}|{target_domain or ''}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def classify_duplicate(occurrence_count: int, project_count: int, user_count: int) -> str:
    """Pure duplicate rule (unit-tested).

    occurrence 1 → unique. Otherwise the most significant conflict wins:
    spanning projects > spanning users > same project/user.
    """
    if occurrence_count <= 1:
        return UNIQUE
    if project_count > 1:
        return DUP_CROSS_PROJECT
    if user_count > 1:
        return DUP_CROSS_USER
    return DUP_SAME_PROJECT


async def resolve_identity(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    source_url_normalized: str,
    target_domain: str,
    cache: dict[str, uuid.UUID] | None = None,
) -> uuid.UUID:
    """Get-or-create the LinkIdentity id for a backlink (idempotent, concurrency-safe)."""
    key = identity_key(workspace_id, source_url_normalized, target_domain)
    if cache is not None and key in cache:
        return cache[key]

    now = datetime.now(timezone.utc)
    # Insert-if-absent; on conflict do nothing, then read back the row's id.
    stmt = (
        pg_insert(LinkIdentity)
        .values(
            workspace_id=workspace_id,
            identity_key=key,
            source_url_normalized=source_url_normalized,
            target_domain=target_domain or "",
            first_seen_at=now,
            last_seen_at=now,
        )
        .on_conflict_do_nothing(index_elements=["identity_key"])
        .returning(LinkIdentity.id)
    )
    identity_id = (await db.execute(stmt)).scalar_one_or_none()
    if identity_id is None:  # already existed
        identity_id = (
            await db.execute(
                select(LinkIdentity.id).where(LinkIdentity.identity_key == key)
            )
        ).scalar_one()
    if cache is not None:
        cache[key] = identity_id
    return identity_id


async def recompute(db: AsyncSession, identity_ids: set[uuid.UUID]) -> int:
    """Recompute counts + duplicate_status for the given identities and their links."""
    ids = [i for i in identity_ids if i is not None]
    if not ids:
        return 0

    rows = (
        await db.execute(
            select(
                BacklinkRecord.link_identity_id,
                func.count().label("occ"),
                func.count(func.distinct(BacklinkRecord.project_id)).label("projects"),
                func.count(
                    func.distinct(func.nullif(BacklinkRecord.assigned_user_label, ""))
                ).label("users"),
                func.count(func.distinct(BacklinkRecord.target_url_normalized)).label("targets"),
            )
            .where(BacklinkRecord.link_identity_id.in_(ids))
            .group_by(BacklinkRecord.link_identity_id)
        )
    ).all()

    counts = {r.link_identity_id: r for r in rows}
    for identity_id in ids:
        r = counts.get(identity_id)
        occ = r.occ if r else 0
        projects = r.projects if r else 0
        users = r.users if r else 0
        targets = r.targets if r else 0
        status = classify_duplicate(occ, projects, users)

        await db.execute(
            text(
                "UPDATE link_identity SET occurrence_count=:occ, project_count=:projects, "
                "user_count=:users, target_url_count=:targets, last_seen_at=now() WHERE id=:id"
            ),
            {"occ": occ, "projects": projects, "users": users, "targets": targets, "id": identity_id},
        )
        await db.execute(
            text(
                "UPDATE backlink_records SET is_duplicate=:is_dup, duplicate_status=:status "
                "WHERE link_identity_id=:id"
            ),
            {"is_dup": occ > 1, "status": status, "id": identity_id},
        )
    return len(ids)
