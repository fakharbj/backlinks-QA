"""Batch delete WITH rollback (Tranche G).

The plain ``DELETE /batches/{id}`` only removes a run from history — approved data
stays where it landed. This service adds a **reversible** delete: it removes the
rows a batch *created* and then deletes the run, without touching unrelated data.

What "created" means, exactly, is what makes this safe:

* **Link/sheet/import batches** own one or more ``imports`` (``imports.batch_id``).
  ``import_service`` sets ``backlink_records.import_id`` ONLY on INSERT — the
  update branch (a re-import that refreshes an existing link) never rewrites it.
  So ``backlink_records WHERE import_id IN (this batch's imports)`` is precisely
  the set of links this batch brought into being. Links the batch merely
  *refreshed* keep their original import_id (a different import) and are left
  alone — we have no pre-batch snapshot to restore them to, and deleting them
  would be data loss.

* **Domain-import batches** upsert into ``source_domains`` with
  ``origin='imported'`` (no per-batch key, and the upsert may have touched a row
  that already existed). We therefore revert only the catalog-only rows: an
  approved domain whose ``source_domains`` row is still ``origin='imported'`` AND
  has zero backlinks referencing it. Domains now in use by real links are kept.

Crawl history / ``backlink_history`` / ``assignment_history`` stay immutable
(audit). Every revert writes an ``audit_logs`` entry that outlives the batch.
"""

from __future__ import annotations

import uuid

from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import AuthContext
from app.core.errors import NotFoundError, ValidationAppError
from app.core.logging import get_logger
from app.models.backlink import BacklinkRecord
from app.models.batch import Batch, BatchItem, BatchLog
from app.models.conflict import BacklinkConflict, BacklinkConflictMember
from app.models.crawl import BacklinkIssue
from app.models.enums import AuditAction
from app.models.imports import Import
from app.models.source_domain import SourceDomain
from app.services import audit_service, duplicate_service, source_domain_service

log = get_logger("services.batch_rollback")

# Kinds whose approved rows can be reverted (they own imports / catalog rows).
_LINK_IMPORT_KINDS = {"link_review", "import", "sheet_sync"}
_DOMAIN_KINDS = {"domain_import"}


async def _import_ids(db: AsyncSession, ws: uuid.UUID, batch_id: uuid.UUID) -> list[uuid.UUID]:
    return list(
        (
            await db.execute(
                select(Import.id).where(
                    Import.workspace_id == ws, Import.batch_id == batch_id
                )
            )
        ).scalars().all()
    )


async def _created_link_ids(
    db: AsyncSession, ws: uuid.UUID, imp_ids: list[uuid.UUID]
) -> list[uuid.UUID]:
    """Backlinks this batch INSERTED (import_id is set on create only)."""
    if not imp_ids:
        return []
    return list(
        (
            await db.execute(
                select(BacklinkRecord.id).where(
                    BacklinkRecord.workspace_id == ws,
                    BacklinkRecord.import_id.in_(imp_ids),
                )
            )
        ).scalars().all()
    )


async def _revertable_domains(
    db: AsyncSession, ws: uuid.UUID, batch_id: uuid.UUID
) -> tuple[list[str], int]:
    """Approved domain keys that are still catalog-only imports with no links
    → safe to remove. Returns (removable_keys, kept_in_use_count)."""
    labels = list(
        (
            await db.execute(
                select(BatchItem.label).where(
                    BatchItem.batch_id == batch_id,
                    BatchItem.kind == "domain",
                    BatchItem.state == "approved",
                )
            )
        ).scalars().all()
    )
    labels = [x for x in labels if x]
    if not labels:
        return [], 0
    removable: list[str] = []
    kept = 0
    for key in labels:
        sd = (
            await db.execute(
                select(SourceDomain).where(
                    SourceDomain.workspace_id == ws, SourceDomain.domain_key == key
                )
            )
        ).scalar_one_or_none()
        if sd is None:
            continue
        in_use = (
            await db.execute(
                select(func.count())
                .select_from(BacklinkRecord)
                .where(
                    BacklinkRecord.workspace_id == ws,
                    BacklinkRecord.source_domain == key,
                )
            )
        ).scalar_one()
        if sd.origin == "imported" and not in_use:
            removable.append(key)
        else:
            kept += 1
    return removable, kept


async def preview(db: AsyncSession, ctx: AuthContext, batch_id: uuid.UUID) -> dict:
    """What a *revert* delete would remove (drives the confirm dialog)."""
    b = await db.get(Batch, batch_id)
    if b is None or b.workspace_id != ctx.workspace_id:
        raise NotFoundError("Batch not found")

    revertable = b.kind in _LINK_IMPORT_KINDS or b.kind in _DOMAIN_KINDS
    created_links = 0
    refreshed_kept = 0
    domains_removable = 0
    domains_kept = 0

    if b.kind in _LINK_IMPORT_KINDS:
        imp_ids = await _import_ids(db, ctx.workspace_id, batch_id)
        created_links = len(await _created_link_ids(db, ctx.workspace_id, imp_ids))
        # Links this batch only refreshed (kept) — sum of imports' updated_rows.
        if imp_ids:
            refreshed_kept = int(
                (
                    await db.execute(
                        select(func.coalesce(func.sum(Import.updated_rows), 0)).where(
                            Import.id.in_(imp_ids)
                        )
                    )
                ).scalar_one()
                or 0
            )
    if b.kind in _DOMAIN_KINDS:
        rem, kept = await _revertable_domains(db, ctx.workspace_id, batch_id)
        domains_removable, domains_kept = len(rem), kept

    return {
        "batch_id": str(batch_id),
        "seq": b.seq,
        "kind": b.kind,
        "status": b.status,
        "revertable": revertable,
        "created_links": created_links,
        "refreshed_kept": refreshed_kept,
        "domains_removable": domains_removable,
        "domains_kept": domains_kept,
    }


async def _delete_created_links(
    db: AsyncSession, ws: uuid.UUID, ids: list[uuid.UUID]
) -> tuple[set[uuid.UUID], set[uuid.UUID]]:
    """Bulk-delete the given backlinks + their live issues + duplicate-group
    membership (collapsing groups left with <2). Returns (touched identity ids,
    touched canonical ids) so the caller can recompute duplicate status AND the
    surviving conflict groups' aggregates. Crawl history stays."""
    if not ids:
        return set(), set()
    identities = set(
        (
            await db.execute(
                select(BacklinkRecord.link_identity_id).where(
                    BacklinkRecord.id.in_(ids),
                    BacklinkRecord.link_identity_id.isnot(None),
                )
            )
        ).scalars().all()
    )
    # Canonical URLs of the deleted links — so surviving conflict groups get
    # re-detected (member_count / first_member_id / facts stay accurate).
    canonicals = set(
        (
            await db.execute(
                select(BacklinkRecord.canonical_url_id).where(
                    BacklinkRecord.id.in_(ids),
                    BacklinkRecord.canonical_url_id.isnot(None),
                )
            )
        ).scalars().all()
    )
    # Conflict groups these links belong to (collapse to <2 members afterwards).
    conflict_ids = set(
        (
            await db.execute(
                select(BacklinkConflictMember.conflict_id).where(
                    BacklinkConflictMember.backlink_id.in_(ids)
                )
            )
        ).scalars().all()
    )
    await db.execute(sa_delete(BacklinkIssue).where(BacklinkIssue.backlink_id.in_(ids)))
    await db.execute(
        sa_delete(BacklinkConflictMember).where(BacklinkConflictMember.backlink_id.in_(ids))
    )
    for cid in conflict_ids:
        remaining = (
            await db.execute(
                select(func.count())
                .select_from(BacklinkConflictMember)
                .where(BacklinkConflictMember.conflict_id == cid)
            )
        ).scalar_one()
        if remaining < 2:
            await db.execute(
                sa_delete(BacklinkConflictMember).where(BacklinkConflictMember.conflict_id == cid)
            )
            await db.execute(sa_delete(BacklinkConflict).where(BacklinkConflict.id == cid))
    await db.execute(sa_delete(BacklinkRecord).where(BacklinkRecord.id.in_(ids)))
    await db.flush()
    return identities, canonicals


async def delete_batch(
    db: AsyncSession, ctx: AuthContext, batch_id: uuid.UUID, *, revert: bool
) -> dict:
    """Delete a batch. ``revert=False`` = housekeeping (data stays).
    ``revert=True`` = also remove the rows the batch created."""
    b = await db.get(Batch, batch_id)
    if b is None or b.workspace_id != ctx.workspace_id:
        raise NotFoundError("Batch not found")
    # Serialize approve vs revert on the SAME batch (both take this lock) so a
    # revert can never race a concurrent approval and orphan freshly-imported rows.
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"batch:{batch_id}"}
    )
    # A running check (staged QA in flight on the worker) must finish first —
    # reverting mid-QA would race the worker's writes and leak orphan log rows.
    if b.status == "running":
        raise ValidationAppError(
            "This batch is still running a check — wait for it to finish before deleting."
        )
    seq = b.seq
    kind = b.kind

    reverted_links = 0
    reverted_domains = 0
    kept_domains = 0

    if revert:
        if kind in _LINK_IMPORT_KINDS:
            imp_ids = await _import_ids(db, ctx.workspace_id, batch_id)
            ids = await _created_link_ids(db, ctx.workspace_id, imp_ids)
            reverted_links = len(ids)
            identities, canonicals = await _delete_created_links(db, ctx.workspace_id, ids)
            # Drop the batch's imports; import_rows CASCADE, and any stray
            # backlink.import_id → SET NULL (only the deleted rows referenced them).
            if imp_ids:
                await db.execute(sa_delete(Import).where(Import.id.in_(imp_ids)))
            await db.flush()
            if identities:
                await duplicate_service.recompute(db, identities)
            # Re-detect conflict groups for the affected pages so surviving groups'
            # member_count / first_member_id / facts don't go stale (mirrors keep_one).
            if canonicals:
                from app.services import conflict_service

                await conflict_service.detect_for_canonicals(db, ctx.workspace_id, canonicals)
            # Rebuild source-domain aggregates + sweep now-orphaned derived rows.
            await source_domain_service.recompute(db, ctx.workspace_id)
        elif kind in _DOMAIN_KINDS:
            removable, kept_domains = await _revertable_domains(db, ctx.workspace_id, batch_id)
            reverted_domains = len(removable)
            if removable:
                await db.execute(
                    sa_delete(SourceDomain).where(
                        SourceDomain.workspace_id == ctx.workspace_id,
                        SourceDomain.domain_key.in_(removable),
                    )
                )
            await db.flush()

    # Durable audit BEFORE the batch (and its logs) are gone.
    if revert:
        summary = (
            f"Reverted & deleted batch #B-{seq}: removed {reverted_links} created link(s)"
            + (f", {reverted_domains} catalog domain(s)" if kind in _DOMAIN_KINDS else "")
        )
    else:
        summary = f"Deleted batch #B-{seq} from history (data kept)"
    await audit_service.record(
        db, action=AuditAction.DELETE, actor_user_id=ctx.user.id,
        workspace_id=ctx.workspace_id, entity_type="batch", entity_id=batch_id,
        summary=summary,
    )

    # Housekeeping: staged items (FK cascade handles them, explicit is clearer) +
    # logs + the batch row itself.
    await db.execute(sa_delete(BatchItem).where(BatchItem.batch_id == batch_id))
    await db.execute(sa_delete(BatchLog).where(BatchLog.batch_id == batch_id))
    await db.delete(b)
    await db.commit()

    return {
        "message": summary,
        "seq": seq,
        "reverted": revert,
        "reverted_links": reverted_links,
        "reverted_domains": reverted_domains,
        "kept_domains": kept_domains,
    }
