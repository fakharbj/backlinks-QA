"""One-time backfill: re-normalize backlinks whose SOURCE URL carries a fragment.

The URL normalizer now KEEPS a significant/stateful fragment (SPA route ``#!/x`` /
``#/x`` or key=value like smallpdf's ``#s=<uuid>``) instead of dropping it, so
distinct client-routed pages no longer collapse to one and get wrongly deduped.
Existing rows still carry the OLD fragment-stripped ``source_url_normalized`` /
``canonical_url_id`` / ``link_identity_id``, so they stay grouped until re-normalized.

Per workspace, for every backlink whose ``source_page_url`` contains ``#``:
  * re-run normalize_url on the RAW url; if the normalized form changed (i.e. it had
    a significant fragment), update ``source_url_normalized`` + ``source_domain``,
    re-resolve ``canonical_url_id`` (distinct now) and ``link_identity_id`` (distinct;
    NULL for GBP, which is exempt), and mark the OLD identity dirty so its remaining
    peers re-evaluate.
  * duplicate_service.recompute(dirty) → the shrunken old identities re-roll (a group
    that split apart drops to unique).
  * conflict_service.rebuild_workspace → rebuild the Duplicates desk from the new
    canonicals (preserves prior human resolutions).

IDEMPOTENT: a row already at the new normalized form is skipped, so a re-run is a
no-op. Bare-anchor fragments (``#section``) still normalize away and are skipped.

Run (single-workspace prod), from backend/ in the venv, AFTER the normalizer change
is deployed:
    cd /home/ls_user/htdocs/72.62.81.34.nip.io/backend
    venv/bin/python scripts/backfill_fragment_normalization.py            # --dry-run to preview
"""

from __future__ import annotations

import argparse
import asyncio
import uuid

from sqlalchemy import select, text

from app.crawler.normalize import normalize_url
from app.db.session import dispose_engines, session_scope
from app.models.backlink import BacklinkRecord
from app.services import canonical_service, conflict_service, duplicate_service


def _is_gbp(link_type: str | None) -> bool:
    return "gbp" in (link_type or "").lower()


async def run(dry_run: bool) -> None:
    async with session_scope() as db:
        ws_ids = (
            await db.execute(text("SELECT DISTINCT workspace_id FROM backlink_records"))
        ).scalars().all()

        for ws in ws_ids:
            rows = (
                await db.execute(
                    select(BacklinkRecord).where(
                        BacklinkRecord.workspace_id == ws,
                        BacklinkRecord.source_page_url.like("%#%"),
                    )
                )
            ).scalars().all()

            ccache: dict[str, uuid.UUID] = {}
            icache: dict[str, uuid.UUID] = {}
            dirty: set[uuid.UUID] = set()
            changed = 0

            for bl in rows:
                parsed = normalize_url(bl.source_page_url or "")
                if not parsed.valid or parsed.normalized == bl.source_url_normalized:
                    continue  # invalid, or bare-anchor fragment that normalizes unchanged
                changed += 1
                if dry_run:
                    continue
                if bl.link_identity_id is not None:
                    dirty.add(bl.link_identity_id)  # old (shared) identity re-rolls
                bl.source_url_normalized = parsed.normalized
                if parsed.registrable_domain:
                    bl.source_domain = parsed.registrable_domain
                canon = await canonical_service.resolve_canonical(db, bl.source_page_url, cache=ccache)
                if canon is not None:
                    bl.canonical_url_id = canon.id
                if _is_gbp(bl.link_type):
                    bl.link_identity_id = None
                    bl.duplicate_status = duplicate_service.UNIQUE
                    bl.is_duplicate = False
                else:
                    new_id = await duplicate_service.resolve_identity(
                        db, ws, parsed.normalized, bl.target_domain or "", icache
                    )
                    bl.link_identity_id = new_id
                    dirty.add(new_id)

            if dry_run:
                print(f"[dry-run] workspace {ws}: {changed} fragment row(s) would be re-normalized")
                continue

            await db.flush()
            if dirty:
                await duplicate_service.recompute(db, dirty)
            await db.commit()
            groups = await conflict_service.rebuild_workspace(db, ws)
            await db.commit()
            print(f"workspace {ws}: re-normalized {changed} fragment row(s); "
                  f"recomputed {len(dirty)} identities; rebuilt {groups} conflict group(s)")

    await dispose_engines()


def main() -> None:
    ap = argparse.ArgumentParser(description="Backfill fragment-aware source normalization.")
    ap.add_argument("--dry-run", action="store_true", help="report counts, write nothing")
    args = ap.parse_args()
    asyncio.run(run(args.dry_run))


if __name__ == "__main__":
    main()
