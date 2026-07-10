"""Link-type standardization: scan → propose → merge/rename → sheet-tab renames.

Phase 10 P1. The catalog accumulated ~72 raw names for ~20 real types (mis-
spellings, case/plural/abbreviation variants) that also live in Google Sheet TAB
NAMES and half a dozen denormalized stores. This service is the one place that
moves a link type safely:

* ``merge_proposal``  — pure scan of the workspace catalog, grouped by an
  aggressive normalizer + typo dictionary; each group suggests the master
  (most-used, best-cased). The ADMIN REVIEWS this before anything runs.
* ``merge_types``     — one transaction under a pg advisory lock: repoints
  backlink_records (id + denormalized name), workforce name-keyed stores,
  task/template link_type_names arrays, sheet-tab link_type_name + field
  constants, scoring versions; soft-deletes the loser with ``merged_into_id``
  set (the alias layer ``resolve_canonical`` follows forever after).
* ``rename_type``     — same rewrites keyed on the old name, no loser row.
* ``apply_sheet_tab_renames`` — the EXTERNAL side effect, sequenced AFTER the
  DB commit: renames the actual Google Sheet tabs (by stable gid), and only
  after each SUCCESSFUL rename updates the stored ``sheet_tab`` strings —
  write-back opens worksheets BY NAME, so order matters. Per-tab fail-open.

Nothing here is called from raw alembic: merges need the Google side effect,
the advisory lock, and audit logging.
"""

from __future__ import annotations

import asyncio
import re
import uuid
from datetime import datetime, timezone
from difflib import SequenceMatcher

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import AuthContext
from app.core.errors import ConflictError, NotFoundError, ValidationAppError
from app.core.logging import get_logger
from app.models.backlink import BacklinkRecord
from app.models.link_type import LinkType
from app.models.sheet_tab import GoogleSheetTab
from app.models.sheets import SheetSource
from app.services.link_type_service import slugify

log = get_logger("services.link_type_merge")

# backlink_records.link_type is varchar(60) — a longer master name would truncate
# on write and re-split the type. Enforce at merge/rename time.
MAX_NAME = 60

# Word-level fixes for the misspellings seen in production data. Applied before
# grouping so "Busniess Listing" and "Business Listing" share a key.
_WORD_FIXES = {
    "busniess": "business", "busniees": "business", "businesss": "business",
    "bussiness": "business", "biz": "business",
    "lisitng": "listing", "listting": "listing", "listings": "listing",
    "socail": "social", "bookamrking": "bookmarking", "bookmarkings": "bookmarking",
    "marking": "marking",  # kept: "book marking" collapses via space removal
    "submissions": "submission", "profiles": "profile", "forums": "forum",
    "postings": "posting", "ads": "ad", "articles": "article",
}


def _norm_key(name: str) -> str:
    """Aggressive grouping key: lowercase, fix known typos word-wise, normalize
    web-2.0 spellings, drop all non-alphanumerics. "Book Marking" == "Bookmarking",
    "WEB2.0" == "web-2.0" == "Web 2.o"."""
    low = (name or "").strip().lower()
    low = low.replace("2.o", "2.0").replace("web 2", "web2").replace("web-2", "web2")
    words = [_WORD_FIXES.get(w, w) for w in re.split(r"[^a-z0-9]+", low) if w]
    return "".join(words)


# Curated aliases for known production abbreviations/synonyms the fuzzy pass
# can't see (norm-key → the master's norm-key). Extend as new ones appear.
_KNOWN_ALIASES = {
    "sbm": "socialbookmarking",           # SBM
    "bookmarking": "socialbookmarking",   # Book Marking / Bookmarking
    "imagesub": "imagesubmission",        # Image Sub
    "pdf": "pdfsubmission",               # PDF
    "profilesubmission": "profile",       # Profile Submission
}


def _is_gbpish(name: str) -> bool:
    low = (name or "").lower()
    return "gbp" in low or "gmb" in low


def _title_case(name: str) -> str:
    return " ".join(w if w.isupper() else w.capitalize() for w in name.split())


async def merge_proposal(db: AsyncSession, ctx: AuthContext) -> dict:
    """Scan the catalog and group duplicate/misspelled types. Returns groups the
    admin reviews; NOTHING is changed here. Suggested master = the most-used
    member (ties → nicest casing), never crossing the GBP/GMB boundary into a
    non-GBP name or vice versa."""
    types = list(
        (
            await db.execute(
                select(LinkType).where(
                    LinkType.workspace_id == ctx.workspace_id, LinkType.deleted_at.is_(None)
                )
            )
        ).scalars().all()
    )
    counts = dict(
        (
            await db.execute(
                select(
                    func.lower(func.btrim(BacklinkRecord.link_type)), func.count()
                )
                .where(
                    BacklinkRecord.workspace_id == ctx.workspace_id,
                    BacklinkRecord.link_type.is_not(None),
                )
                .group_by(func.lower(func.btrim(BacklinkRecord.link_type)))
            )
        ).all()
    )

    def usage(t: LinkType) -> int:
        return int(counts.get(t.name.strip().lower(), 0))

    # 1) Exact normalized-key groups (curated aliases fold in here too).
    groups: dict[str, list[LinkType]] = {}
    for t in types:
        raw_key = _norm_key(t.name)
        raw_key = _KNOWN_ALIASES.get(raw_key, raw_key)
        # GBP/GMB types group apart from their plain counterparts: prefix the key.
        key = ("gbp:" if _is_gbpish(t.name) else "") + raw_key
        groups.setdefault(key, []).append(t)

    # 2) Fuzzy pass, same GBP side only: fold keys that are (a) near-identical
    #    (typo residue, ratio ≥ 0.87) or (b) prefix-contained with most of the
    #    longer key shared ("classifiedad" ⊂ "classifiedadposting") — the owner's
    #    "Classified Ads / Classified Ads Posting are one type" case.
    def _same(a: str, b: str) -> bool:
        ka, kb = a.removeprefix("gbp:"), b.removeprefix("gbp:")
        if SequenceMatcher(None, ka, kb).ratio() >= 0.87:
            return True
        short, long_ = sorted((ka, kb), key=len)
        return len(short) >= 6 and long_.startswith(short) and len(short) / len(long_) >= 0.6

    keys = sorted(groups.keys(), key=lambda k: -sum(usage(t) for t in groups[k]))
    merged_into: dict[str, str] = {}
    for i, a in enumerate(keys):
        if a in merged_into:
            continue
        for b in keys[i + 1:]:
            if b in merged_into or a.startswith("gbp:") != b.startswith("gbp:"):
                continue
            if _same(a, b):
                groups[a].extend(groups[b])
                merged_into[b] = a
    for b in merged_into:
        groups.pop(b, None)

    out = []
    for key, members in groups.items():
        if len(members) < 2:
            continue
        members.sort(key=lambda t: (-usage(t), t.name))
        best = members[0]
        # Suggest a cleanly-cased master name (keep the exact top name when it
        # already looks clean — owner can override in the review UI anyway).
        suggested = best.name.strip()
        if suggested.islower() or suggested.isupper():
            suggested = _title_case(suggested)
        out.append({
            "suggested_master": suggested[:MAX_NAME],
            "suggested_master_id": str(best.id),
            "members": [
                {"id": str(t.id), "name": t.name, "backlinks": usage(t)} for t in members
            ],
            "total_backlinks": sum(usage(t) for t in members),
        })
    out.sort(key=lambda g: -g["total_backlinks"])
    return {"groups": out, "distinct_types": len(types)}


async def _usage_counts(db: AsyncSession, ws: uuid.UUID, lt: LinkType) -> dict:
    name = lt.name.strip()
    p = {"ws": ws, "name": name.lower(), "id": lt.id}
    async def _n(sql: str) -> int:
        return int((await db.execute(text(sql), p)).scalar() or 0)
    return {
        "backlinks": await _n(
            "SELECT count(*) FROM backlink_records WHERE workspace_id=:ws "
            "AND (link_type_id=:id OR lower(btrim(link_type))=:name)"
        ),
        "sheet_tabs": await _n(
            "SELECT count(*) FROM google_sheet_project_tabs WHERE workspace_id=:ws "
            "AND (lower(btrim(tab_name))=:name OR lower(btrim(coalesce(link_type_name,'')))=:name)"
        ),
        "tasks": await _n(
            "SELECT count(*) FROM task_assignments WHERE workspace_id=:ws "
            "AND EXISTS (SELECT 1 FROM unnest(link_type_names) x WHERE lower(btrim(x))=:name)"
        ),
        "templates": await _n(
            "SELECT count(*) FROM task_week_templates WHERE workspace_id=:ws "
            "AND link_type_names IS NOT NULL "
            "AND EXISTS (SELECT 1 FROM unnest(link_type_names) x WHERE lower(btrim(x))=:name)"
        ),
        "productivity_rates": await _n(
            "SELECT count(*) FROM link_type_productivity WHERE workspace_id=:ws "
            "AND lower(btrim(link_type_name))=:name"
        ),
        "user_rate_overrides": await _n(
            "SELECT count(*) FROM user_productivity_overrides WHERE workspace_id=:ws "
            "AND lower(btrim(link_type_name))=:name"
        ),
        "scoring_versions": await _n(
            "SELECT count(*) FROM scoring_rule_versions WHERE workspace_id=:ws AND is_latest "
            "AND ((scope='link_type' AND scope_ref_id=:id) OR (scope='project_link_type' AND link_type_id=:id))"
        ),
    }


async def _get_active(db: AsyncSession, ctx: AuthContext, type_id: uuid.UUID) -> LinkType:
    lt = await db.get(LinkType, type_id)
    if lt is None or lt.workspace_id != ctx.workspace_id or lt.deleted_at is not None:
        raise NotFoundError("Link type not found")
    return lt


async def merge_preview(
    db: AsyncSession, ctx: AuthContext, loser_id: uuid.UUID, winner_id: uuid.UUID
) -> dict:
    loser = await _get_active(db, ctx, loser_id)
    winner = await _get_active(db, ctx, winner_id)
    return {
        "loser": {"id": str(loser.id), "name": loser.name},
        "winner": {"id": str(winner.id), "name": winner.name},
        "will_update": await _usage_counts(db, ctx.workspace_id, loser),
        "gbp_boundary_crossed": _is_gbpish(loser.name) != _is_gbpish(winner.name),
    }


async def _rewrite_name_keyed_stores(
    db: AsyncSession, ws: uuid.UUID, old_name: str, new_name: str,
    loser_id: uuid.UUID | None, winner_id: uuid.UUID | None,
) -> dict:
    """The shared DB rewrites for merge AND rename (everything keyed by the NAME
    string). Caller owns the transaction."""
    p = {"ws": ws, "old": old_name, "old_l": old_name.strip().lower(), "new": new_name}
    changed: dict[str, int] = {}

    async def _run(label: str, sql: str, params: dict | None = None) -> None:
        res = await db.execute(text(sql), params or p)
        changed[label] = res.rowcount or 0

    # Denormalized backlink string (+ FK repoint when merging).
    if loser_id is not None and winner_id is not None:
        await _run(
            "backlinks",
            "UPDATE backlink_records SET link_type=:new, link_type_id=:win "
            "WHERE workspace_id=:ws AND (link_type_id=:lose OR lower(btrim(link_type))=:old_l)",
            {**p, "win": winner_id, "lose": loser_id},
        )
    else:
        await _run(
            "backlinks",
            "UPDATE backlink_records SET link_type=:new "
            "WHERE workspace_id=:ws AND lower(btrim(link_type))=:old_l",
        )

    # Workforce per-type rates: keep-winner-on-collision, else rename.
    await _run(
        "productivity_dropped",
        "DELETE FROM link_type_productivity l WHERE l.workspace_id=:ws "
        "AND lower(btrim(l.link_type_name))=:old_l AND EXISTS ("
        "  SELECT 1 FROM link_type_productivity w WHERE w.workspace_id=:ws "
        "  AND lower(btrim(w.link_type_name))=lower(btrim(:new)) AND w.id <> l.id)",
    )
    await _run(
        "productivity_renamed",
        "UPDATE link_type_productivity SET link_type_name=:new "
        "WHERE workspace_id=:ws AND lower(btrim(link_type_name))=:old_l",
    )
    await _run(
        "user_overrides_dropped",
        "DELETE FROM user_productivity_overrides l WHERE l.workspace_id=:ws "
        "AND lower(btrim(l.link_type_name))=:old_l AND EXISTS ("
        "  SELECT 1 FROM user_productivity_overrides w WHERE w.workspace_id=:ws "
        "  AND w.user_label=l.user_label "
        "  AND lower(btrim(w.link_type_name))=lower(btrim(:new)) AND w.id <> l.id)",
    )
    await _run(
        "user_overrides_renamed",
        "UPDATE user_productivity_overrides SET link_type_name=:new "
        "WHERE workspace_id=:ws AND lower(btrim(link_type_name))=:old_l",
    )

    # Task/template arrays: replace + de-duplicate.
    for label, table in (("tasks", "task_assignments"), ("templates", "task_week_templates")):
        await _run(
            label,
            f"UPDATE {table} SET link_type_names = ("
            "  SELECT coalesce(array_agg(DISTINCT CASE WHEN lower(btrim(x))=:old_l THEN :new ELSE x END), '{{}}')"
            "  FROM unnest(link_type_names) x)"
            " WHERE workspace_id=:ws AND link_type_names IS NOT NULL"
            "  AND EXISTS (SELECT 1 FROM unnest(link_type_names) x WHERE lower(btrim(x))=:old_l)",
        )

    # Sheet-tab link-type binding + per-tab constants (tab NAME renames happen in
    # apply_sheet_tab_renames AFTER commit — Google first, strings after).
    await _run(
        "tab_link_type_name",
        "UPDATE google_sheet_project_tabs SET link_type_name=:new "
        "WHERE workspace_id=:ws AND lower(btrim(coalesce(link_type_name,'')))=:old_l",
    )
    await _run(
        "tab_constants",
        "UPDATE google_sheet_project_tabs SET field_constants = "
        "jsonb_set(field_constants, '{link_type}', to_jsonb(:new::text)) "
        "WHERE workspace_id=:ws AND field_constants->>'link_type' IS NOT NULL "
        "AND lower(btrim(field_constants->>'link_type'))=:old_l",
    )
    return changed


async def _repoint_scoring(
    db: AsyncSession, ws: uuid.UUID, loser_id: uuid.UUID, winner_id: uuid.UUID
) -> dict:
    """Move the loser's scoring versions to the winner where the winner has no
    version for that scope; otherwise RETIRE the loser's (winner's config wins).
    Preserves the service-enforced one-is-latest-per-scope invariant."""
    p = {"ws": ws, "lose": loser_id, "win": winner_id}
    out: dict[str, int] = {}
    # link_type scope (scope_ref_id = the type).
    r1 = await db.execute(text(
        "UPDATE scoring_rule_versions SET is_latest=false "
        "WHERE workspace_id=:ws AND scope='link_type' AND scope_ref_id=:lose AND is_latest "
        "AND EXISTS (SELECT 1 FROM scoring_rule_versions w WHERE w.workspace_id=:ws "
        "  AND w.scope='link_type' AND w.scope_ref_id=:win AND w.is_latest)"), p)
    r2 = await db.execute(text(
        "UPDATE scoring_rule_versions SET scope_ref_id=:win "
        "WHERE workspace_id=:ws AND scope='link_type' AND scope_ref_id=:lose"), p)
    # project_link_type scope (project in scope_ref_id, type in link_type_id).
    r3 = await db.execute(text(
        "UPDATE scoring_rule_versions SET is_latest=false "
        "WHERE workspace_id=:ws AND scope='project_link_type' AND link_type_id=:lose AND is_latest "
        "AND EXISTS (SELECT 1 FROM scoring_rule_versions w WHERE w.workspace_id=:ws "
        "  AND w.scope='project_link_type' AND w.scope_ref_id=scoring_rule_versions.scope_ref_id "
        "  AND w.link_type_id=:win AND w.is_latest)"), p)
    r4 = await db.execute(text(
        "UPDATE scoring_rule_versions SET link_type_id=:win "
        "WHERE workspace_id=:ws AND scope='project_link_type' AND link_type_id=:lose"), p)
    out["scoring_retired"] = (r1.rowcount or 0) + (r3.rowcount or 0)
    out["scoring_repointed"] = (r2.rowcount or 0) + (r4.rowcount or 0)
    return out


async def merge_types(
    db: AsyncSession, ctx: AuthContext, loser_id: uuid.UUID, winner_id: uuid.UUID
) -> dict:
    """Merge ``loser`` into ``winner`` (DB half; call apply_sheet_tab_renames after
    commit for the Google side). One transaction under a workspace advisory lock."""
    if loser_id == winner_id:
        raise ValidationAppError("A link type cannot be merged into itself.")
    loser = await _get_active(db, ctx, loser_id)
    winner = await _get_active(db, ctx, winner_id)
    if len(winner.name.strip()) > MAX_NAME:
        raise ValidationAppError(
            f"Master name is longer than {MAX_NAME} characters (backlink storage limit)."
        )
    # Serialize merges per workspace (concurrent merges could race the repoints).
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext('lt-merge:' || :ws))"),
        {"ws": str(ctx.workspace_id)},
    )

    changed = await _rewrite_name_keyed_stores(
        db, ctx.workspace_id, loser.name, winner.name.strip(), loser.id, winner.id
    )
    changed |= await _repoint_scoring(db, ctx.workspace_id, loser.id, winner.id)

    # Soft-delete the loser as an ALIAS (redirect layer). Its slug stays occupied,
    # which is the point: resolve_canonical finds it and follows merged_into_id.
    loser.merged_into_id = winner.id
    loser.deleted_at = datetime.now(timezone.utc)
    loser.deleted_by = ctx.user.id
    loser.is_active = False
    # Re-target any existing aliases of the loser straight at the winner (keeps
    # redirect chains one hop deep — no cycles possible).
    await db.execute(
        text(
            "UPDATE link_types SET merged_into_id=:win "
            "WHERE workspace_id=:ws AND merged_into_id=:lose"
        ),
        {"ws": ctx.workspace_id, "win": winner.id, "lose": loser.id},
    )
    await db.flush()

    return {
        "merged": {"id": str(loser.id), "name": loser.name},
        "into": {"id": str(winner.id), "name": winner.name},
        "changed": changed,
        "gbp_boundary_crossed": _is_gbpish(loser.name) != _is_gbpish(winner.name),
    }


async def rename_type(
    db: AsyncSession, ctx: AuthContext, type_id: uuid.UUID, new_name: str
) -> dict:
    """Rename a master (correct a spelling). If the new name's slug already exists
    on ANOTHER live type, that is a merge — refuse and say so."""
    new_name = (new_name or "").strip()
    if not new_name:
        raise ValidationAppError("New name is required.")
    if len(new_name) > MAX_NAME:
        raise ValidationAppError(f"Name is longer than {MAX_NAME} characters.")
    lt = await _get_active(db, ctx, type_id)
    slug = slugify(new_name)
    clash = (
        await db.execute(
            select(LinkType).where(
                LinkType.workspace_id == ctx.workspace_id,
                LinkType.slug == slug,
                LinkType.id != lt.id,
                LinkType.deleted_at.is_(None),
            )
        )
    ).scalars().first()
    if clash is not None:
        raise ConflictError(
            f'"{clash.name}" already exists — use Merge to fold "{lt.name}" into it.'
        )
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext('lt-merge:' || :ws))"),
        {"ws": str(ctx.workspace_id)},
    )
    old_name = lt.name
    changed = await _rewrite_name_keyed_stores(
        db, ctx.workspace_id, old_name, new_name, None, None
    )
    lt.name = new_name
    lt.slug = slug
    await db.flush()
    return {"renamed": {"id": str(lt.id), "from": old_name, "to": new_name}, "changed": changed}


async def apply_sheet_tab_renames(
    db: AsyncSession, ctx: AuthContext, old_name: str, new_name: str
) -> list[dict]:
    """Rename the ACTUAL Google Sheet tabs matching ``old_name`` → ``new_name``.

    Runs AFTER the DB merge commit. Per tab: Google rename first (by stable gid);
    only on success update the stored tab_name + the denormalized ``sheet_tab``
    strings (backlink_records / imports / sheet_sources) for that spreadsheet —
    write-back opens worksheets BY NAME, so a string update without the rename
    would break it. Fail-open: one tab's failure never blocks the rest."""
    from app.integrations import google_sheets

    rows = (
        await db.execute(
            select(GoogleSheetTab, SheetSource.spreadsheet_id)
            .join(SheetSource, SheetSource.id == GoogleSheetTab.sheet_source_id)
            .where(
                GoogleSheetTab.workspace_id == ctx.workspace_id,
                func.lower(func.btrim(GoogleSheetTab.tab_name)) == old_name.strip().lower(),
            )
        )
    ).all()
    results: list[dict] = []
    for tab, spreadsheet_id in rows:
        entry: dict = {"spreadsheet_id": spreadsheet_id, "gid": tab.gid, "from": tab.tab_name,
                       "to": new_name}
        try:
            renamed = await asyncio.to_thread(
                google_sheets.rename_worksheet, spreadsheet_id, tab.gid, new_name
            )
        except Exception as exc:  # noqa: BLE001 - fail-open per tab
            renamed = False
            entry["error"] = repr(exc)[:200]
        if not renamed:
            entry.setdefault("error", "rename_failed_or_title_taken")
            entry["ok"] = False
            results.append(entry)
            log.warning("sheet_tab_rename_failed", **entry)
            continue
        tab.tab_name = new_name
        p = {"sid": tab.sheet_source_id, "old": entry["from"], "new": new_name}
        # Guard uq_backlink_records_sheet_entry: skip rows whose (tab,row_ref)
        # would collide after the rename; report how many were left behind.
        moved = await db.execute(text(
            "UPDATE backlink_records b SET sheet_tab=:new "
            "WHERE b.source_sheet_id=:sid AND b.sheet_tab=:old AND NOT EXISTS ("
            "  SELECT 1 FROM backlink_records c WHERE c.source_sheet_id=:sid "
            "  AND c.sheet_tab=:new AND c.sheet_row_ref=b.sheet_row_ref AND c.id<>b.id)"), p)
        left = await db.execute(text(
            "SELECT count(*) FROM backlink_records WHERE source_sheet_id=:sid AND sheet_tab=:old"), p)
        await db.execute(text(
            "UPDATE imports SET sheet_tab=:new WHERE sheet_source_id=:sid AND sheet_tab=:old"), p)
        await db.execute(text(
            "UPDATE sheet_sources SET sheet_tab=:new WHERE id=:sid AND sheet_tab=:old"), p)
        entry["ok"] = True
        entry["links_repointed"] = moved.rowcount or 0
        entry["links_skipped_collision"] = int(left.scalar() or 0)
        results.append(entry)
        log.info("sheet_tab_renamed", **{k: v for k, v in entry.items() if k != "ok"})
    await db.flush()
    return results
