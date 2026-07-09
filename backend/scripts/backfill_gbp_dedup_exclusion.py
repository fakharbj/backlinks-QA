"""One-time backfill: exclude every "GBP" link type from the duplicate system.

NEW RULE (owner-confirmed): any backlink whose link-type NAME contains "GBP"
(case-insensitive substring — "GBP", "GBP Web 2.0", …) is FULLY EXEMPT from
duplicate detection. It must never be flagged as a duplicate, never be a member
of a Duplicates-desk conflict group, and never cause a *non-GBP* link to be
flagged. Only GBP is exempt; every other link type keeps deduping normally.

This script reconciles EXISTING prod data with that rule. Go-forward enforcement
lives in the services (import/identity path skips GBP; conflict grouping filters
GBP). This backfill assumes that code is already deployed — see the PREREQUISITE
note below.

What it does, per workspace that has backlinks:
  1. Detach GBP links from the identity layer and mark them unique, capturing the
     identities they *were* in (chunked UPDATE … RETURNING the old identity id):
         link_identity_id = NULL, duplicate_status = 'unique', is_duplicate = false
  2. duplicate_service.recompute(db, <those identities>) — the remaining NON-GBP
     members of each touched identity re-evaluate. A formerly-2-member identity
     (1 GBP + 1 non-GBP) is now 1 → its surviving link flips to 'unique'.
  3. conflict_service.rebuild_workspace(db, workspace_id) — rebuilds the Duplicates
     desk groups under the GBP-excluding grouping logic. rebuild_workspace preserves
     prior human resolutions (acknowledged/resolved/ignored) for groups that survive.

Safety properties:
  * IDEMPOTENT — step 1 only touches rows not already in the target state, so a
    re-run is a no-op there; recompute/rebuild are idempotent by design.
  * CHUNKED — step 1 updates in BATCH-sized commits; dirty identities are gathered
    incrementally from what was actually changed (interruption-tolerant).
  * SINGLE-WORKSPACE PROD SAFE — iterates only workspaces that actually have data.

PREREQUISITE (must be deployed BEFORE running this):
  conflict_service.rebuild_workspace / detect_for_canonicals group by
  ``canonical_url_id``. GBP links keep their canonical_url_id, so the desk (step 3)
  only excludes them once those grouping queries filter out GBP link types. If the
  GBP-exclusion code is NOT yet live, step 3 will re-group GBP links. Deploy the
  service change first, then run this.

Run on the server (single-workspace prod), from backend/, in the app venv:

    cd /home/ls_user/htdocs/72.62.81.34.nip.io/backend
    venv/bin/python scripts/backfill_gbp_dedup_exclusion.py

Add --dry-run to report counts without writing.
"""

from __future__ import annotations

import argparse
import asyncio
import uuid

from sqlalchemy import text

from app.db.session import dispose_engines, session_scope
from app.services import conflict_service, duplicate_service

BATCH = 5000

# GBP by NAME on the denormalized link_type column (case-insensitive substring),
# matching the go-forward rule exactly (import_service._is_gbp / conflict_service
# _non_gbp_clause), so backfill and runtime never disagree. COALESCE keeps NULL
# link types out of the match (they are not GBP).
_GBP_PRED = "(COALESCE(b.link_type, '') ILIKE '%GBP%')"

# A row still needs work if it is attached to an identity or not yet marked unique.
_NEEDS_CHANGE = (
    "(b.link_identity_id IS NOT NULL "
    " OR b.duplicate_status IS DISTINCT FROM 'unique' "
    " OR b.is_duplicate)"
)


async def _detach_gbp(db, ws: uuid.UUID) -> tuple[int, set[uuid.UUID]]:
    """Chunked: null identity + mark unique on GBP links; return (count, old identities)."""
    detached = 0
    dirty: set[uuid.UUID] = set()
    stmt = text(
        f"""
        WITH picked AS (
            SELECT b.id, b.link_identity_id AS old_iid
            FROM backlink_records b
            WHERE b.workspace_id = :ws
              AND {_GBP_PRED}
              AND {_NEEDS_CHANGE}
            LIMIT :n
        )
        UPDATE backlink_records t
           SET link_identity_id = NULL,
               duplicate_status = 'unique',
               is_duplicate = false
          FROM picked
         WHERE t.id = picked.id
        RETURNING picked.old_iid
        """
    )
    while True:
        rows = (await db.execute(stmt, {"ws": ws, "n": BATCH})).fetchall()
        if not rows:
            break
        detached += len(rows)
        dirty.update(r[0] for r in rows if r[0] is not None)
        await db.commit()  # commit each batch (chunked, resumable)
    return detached, dirty


async def _count_gbp(db, ws: uuid.UUID) -> int:
    return (
        await db.execute(
            text(f"SELECT count(*) FROM backlink_records b WHERE b.workspace_id = :ws AND {_GBP_PRED}"),
            {"ws": ws},
        )
    ).scalar_one()


async def run(dry_run: bool) -> None:
    async with session_scope() as db:
        ws_ids = (
            await db.execute(text("SELECT DISTINCT workspace_id FROM backlink_records"))
        ).scalars().all()

        for ws in ws_ids:
            total_gbp = await _count_gbp(db, ws)
            if dry_run:
                needs = (
                    await db.execute(
                        text(
                            f"SELECT count(*) FROM backlink_records b "
                            f"WHERE b.workspace_id = :ws AND {_GBP_PRED} AND {_NEEDS_CHANGE}"
                        ),
                        {"ws": ws},
                    )
                ).scalar_one()
                print(f"[dry-run] workspace {ws}: {total_gbp} GBP links, {needs} still to reconcile")
                continue

            detached, dirty = await _detach_gbp(db, ws)
            print(f"workspace {ws}: {total_gbp} GBP links; detached {detached}; "
                  f"recomputing {len(dirty)} touched identities")

            # 2. Non-GBP survivors of the touched identities re-evaluate.
            if dirty:
                await duplicate_service.recompute(db, dirty)
                await db.commit()

            # 3. Rebuild the Duplicates desk under GBP-excluding grouping logic
            #    (preserves prior human resolutions for surviving groups).
            groups = await conflict_service.rebuild_workspace(db, ws)
            await db.commit()
            print(f"workspace {ws}: rebuilt {groups} conflict group(s)")

    await dispose_engines()


def main() -> None:
    ap = argparse.ArgumentParser(description="Backfill GBP duplicate-system exclusion.")
    ap.add_argument("--dry-run", action="store_true", help="report counts, write nothing")
    args = ap.parse_args()
    asyncio.run(run(args.dry_run))


if __name__ == "__main__":
    main()
