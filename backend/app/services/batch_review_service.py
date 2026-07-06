"""Review batches (0029): the staging layer between manual imports and the
production tables.

Manual link imports (paste/file) and domain imports land here as ``batch_items``
inside a batch of kind ``link_review`` / ``domain_import``. Each item knows its
*presence* (new / existing / duplicate vs. the main DB and within the batch) and
its *state* (pending → checking → checked | failed → approved | rejected). QA
verdicts and fetched metrics are written into ``item.payload`` ONLY — nothing
reaches ``backlink_records`` or ``source_domains`` until a user approves items,
at which point:

* links  → an ``Import`` run through the normal ``import_service`` pipeline
  (same upsert/dedup/recompute path as every other import), linked to the SAME
  batch so its logs and error rows show up in the batch history;
* domains → an upsert into ``source_domains`` with ``origin='imported'`` so the
  recompute orphan-sweep never deletes them.

Unlike ``batch_service`` (fail-open bookkeeping), everything here is
load-bearing and runs in the caller's transaction — a failure must fail the
request.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import date, datetime, timezone

import httpx
from sqlalchemy import func, select, tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import AuthContext
from app.core.errors import NotFoundError, ValidationAppError
from app.core.logging import get_logger
from app.crawler.normalize import normalize_url, registrable_domain
from app.integrations import domain_metrics
from app.models.backlink import BacklinkRecord
from app.models.batch import Batch, BatchItem, BatchLog
from app.models.enums import ImportSource
from app.models.source_domain import SourceDomain

log = get_logger("services.batch_review")

# Item states that still need a human decision.
_OPEN_STATES = ("pending", "checking", "checked", "failed")
REVIEW_KINDS = ("link_review", "domain_import")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _log(batch_id: uuid.UUID, message: str, *, level: str = "info", data: dict | None = None) -> BatchLog:
    return BatchLog(batch_id=batch_id, level=level, message=message[:4000], data=data or {})


async def load_batch(
    db: AsyncSession, ctx: AuthContext, batch_id: uuid.UUID, *, review_only: bool = False
) -> Batch:
    batch = await db.get(Batch, batch_id)
    if batch is None or batch.workspace_id != ctx.workspace_id:
        raise NotFoundError("Batch not found")
    if batch.project_id:
        ctx.assert_project(batch.project_id)
    if review_only and batch.kind not in REVIEW_KINDS:
        raise ValidationAppError("This batch has no reviewable items")
    return batch


# ── Staging ──────────────────────────────────────────────────────────────────


async def stage_link_import(
    db: AsyncSession,
    ctx: AuthContext,
    *,
    project_id: uuid.UUID,
    rows: list[dict[str, str]],
    source: ImportSource,
    filename: str | None = None,
) -> Batch:
    """Create a ``link_review`` batch from already-mapped import rows.

    ``rows`` are canonical-field dicts (``source_page_url``/``target_url``/…) —
    the caller applies column mapping first. Presence is computed against the
    project's existing links in bulk; in-batch repeats are kept as visible
    ``duplicate`` rows (their key is salted so the per-batch unique holds).
    """
    if not rows:
        raise ValidationAppError("No rows found to import")
    if len(rows) > 20000:
        raise ValidationAppError("Too many rows for one review batch (max 20,000)")

    batch = Batch(
        workspace_id=ctx.workspace_id,
        project_id=project_id,
        kind="link_review",
        status="review",
        label=f"Links import — {filename or source.value} ({len(rows)} rows)",
        started_by=ctx.user.id,
        totals={"total": len(rows), "done": 0},
        counters={},
        meta={"source": source.value, "filename": filename or ""},
    )
    db.add(batch)
    await db.flush()

    # Normalize every row once; collect valid pairs for the bulk presence query.
    prepared: list[dict] = []
    for idx, mapped in enumerate(rows):
        source_raw = (mapped.get("source_page_url") or "").strip()
        target_raw = (mapped.get("target_url") or "").strip()
        entry: dict = {
            "mapped": {k: v for k, v in mapped.items() if v},
            "source_raw": source_raw,
            "target_raw": target_raw,
            "row": idx + 1,
        }
        if not source_raw:
            entry["error"] = "Missing source URL"
        elif not target_raw:
            entry["error"] = "Missing target URL"
        else:
            src = normalize_url(source_raw)
            tgt = normalize_url(target_raw)
            if not src.valid:
                entry["error"] = f"Invalid source URL ({src.error or 'unparseable'})"
            elif not tgt.valid:
                entry["error"] = f"Invalid target URL ({tgt.error or 'unparseable'})"
            else:
                entry["pair"] = (src.normalized, tgt.normalized)
                entry["source_domain"] = src.registrable_domain
        prepared.append(entry)

    # One bulk lookup: which (source, target) pairs already live in this project?
    pairs = sorted({e["pair"] for e in prepared if "pair" in e})
    existing_pairs: set[tuple[str, str]] = set()
    for i in range(0, len(pairs), 400):
        chunk = pairs[i : i + 400]
        found = await db.execute(
            select(
                BacklinkRecord.source_url_normalized, BacklinkRecord.target_url_normalized
            ).where(
                BacklinkRecord.workspace_id == ctx.workspace_id,
                BacklinkRecord.project_id == project_id,
                tuple_(
                    BacklinkRecord.source_url_normalized, BacklinkRecord.target_url_normalized
                ).in_(chunk),
            )
        )
        existing_pairs.update((s, t) for s, t in found.all())

    seen: dict[str, int] = {}
    counts = {"new": 0, "existing": 0, "duplicate": 0, "invalid": 0}
    for entry in prepared:
        if "pair" in entry:
            base_key = _sha(f"{entry['pair'][0]}|{entry['pair'][1]}")
        else:
            base_key = _sha(f"row|{entry['source_raw']}|{entry['target_raw']}|{entry['row']}")
        repeat = seen.get(base_key, 0)
        seen[base_key] = repeat + 1

        if "error" in entry:
            presence, state = "new", "failed"
            counts["invalid"] += 1
        elif repeat:
            presence, state = "duplicate", "pending"
            counts["duplicate"] += 1
        elif entry["pair"] in existing_pairs:
            presence, state = "existing", "pending"
            counts["existing"] += 1
        else:
            presence, state = "new", "pending"
            counts["new"] += 1

        payload: dict = {"mapped": entry["mapped"], "row": entry["row"]}
        if entry.get("source_domain"):
            payload["source_domain"] = entry["source_domain"]
        db.add(
            BatchItem(
                workspace_id=ctx.workspace_id,
                batch_id=batch.id,
                project_id=project_id,
                kind="link",
                label=entry["source_raw"] or f"(row {entry['row']})",
                key_hash=base_key if not repeat else _sha(f"{base_key}#{repeat}"),
                presence=presence,
                state=state,
                payload=payload,
                error=entry.get("error"),
            )
        )

    batch.counters = counts
    db.add(
        _log(
            batch.id,
            f"Staged {len(prepared)} links for review — {counts['new']} new, "
            f"{counts['existing']} already in the project, {counts['duplicate']} repeated "
            f"in this import, {counts['invalid']} invalid. Nothing is added until you approve.",
        )
    )
    await db.flush()
    return batch


def parse_domain_lines(text_block: str) -> list[str]:
    """Accept one domain or URL per line (commas/whitespace tolerated) and
    return normalized registrable domains, order-preserving and de-duplicated."""
    out: list[str] = []
    seen: set[str] = set()
    for raw_line in text_block.replace(",", "\n").splitlines():
        token = raw_line.strip().strip(".").lower()
        if not token or token.startswith("#"):
            continue
        if "://" in token or token.startswith("www."):
            norm = normalize_url(token if "://" in token else f"https://{token}")
            domain = norm.registrable_domain if norm.valid else ""
        else:
            domain = registrable_domain(token.split("/")[0])
        if domain and "." in domain and domain not in seen:
            seen.add(domain)
            out.append(domain)
    return out


async def stage_domain_import(
    db: AsyncSession, ctx: AuthContext, *, text_block: str, label: str | None = None
) -> Batch:
    """Create a ``domain_import`` batch from a pasted list of domains/URLs.
    Repeated lines are collapsed (counted, not staged); presence is checked
    against the workspace's ``source_domains`` catalog."""
    lines = [ln for ln in text_block.replace(",", "\n").splitlines() if ln.strip()]
    domains = parse_domain_lines(text_block)
    if not domains:
        raise ValidationAppError("No valid domains found — paste one domain or URL per line")
    if len(domains) > 10000:
        raise ValidationAppError("Too many domains for one review batch (max 10,000)")

    batch = Batch(
        workspace_id=ctx.workspace_id,
        kind="domain_import",
        status="review",
        label=label or f"Domain import ({len(domains)} domains)",
        started_by=ctx.user.id,
        totals={"total": len(domains), "done": 0},
        counters={},
        meta={},
    )
    db.add(batch)
    await db.flush()

    existing: set[str] = set()
    for i in range(0, len(domains), 500):
        chunk = domains[i : i + 500]
        found = await db.execute(
            select(SourceDomain.domain_key).where(
                SourceDomain.workspace_id == ctx.workspace_id,
                SourceDomain.domain_key.in_(chunk),
            )
        )
        existing.update(d for (d,) in found.all())

    counts = {"new": 0, "existing": 0, "duplicate": max(0, len(lines) - len(domains)), "invalid": 0}
    for domain in domains:
        presence = "existing" if domain in existing else "new"
        counts[presence] += 1
        db.add(
            BatchItem(
                workspace_id=ctx.workspace_id,
                batch_id=batch.id,
                kind="domain",
                label=domain,
                key_hash=_sha(domain),
                presence=presence,
                state="pending",
                payload={},
            )
        )

    batch.counters = counts
    db.add(
        _log(
            batch.id,
            f"Staged {len(domains)} domains for review — {counts['new']} new, "
            f"{counts['existing']} already in the catalog"
            + (f", {counts['duplicate']} repeated lines collapsed" if counts["duplicate"] else "")
            + ". Check metrics, then approve the ones you want to keep.",
        )
    )
    await db.flush()
    return batch


# ── Reading items ────────────────────────────────────────────────────────────


async def item_counts(db: AsyncSession, batch_id: uuid.UUID) -> dict:
    rows = (
        await db.execute(
            select(BatchItem.state, BatchItem.presence, func.count())
            .where(BatchItem.batch_id == batch_id)
            .group_by(BatchItem.state, BatchItem.presence)
        )
    ).all()
    by_state: dict[str, int] = {}
    by_presence: dict[str, int] = {}
    total = 0
    for state, presence, n in rows:
        by_state[state] = by_state.get(state, 0) + n
        by_presence[presence] = by_presence.get(presence, 0) + n
        total += n
    return {"total": total, "by_state": by_state, "by_presence": by_presence}


def _filtered_items_stmt(
    batch_id: uuid.UUID, *, state: str | None, presence: str | None, q: str | None
):
    stmt = select(BatchItem).where(BatchItem.batch_id == batch_id)
    if state:
        wanted = [s.strip() for s in state.split(",") if s.strip()]
        if wanted:
            stmt = stmt.where(BatchItem.state.in_(wanted))
    if presence:
        wanted = [p.strip() for p in presence.split(",") if p.strip()]
        if wanted:
            stmt = stmt.where(BatchItem.presence.in_(wanted))
    if q:
        stmt = stmt.where(BatchItem.label.ilike(f"%{q.strip()}%"))
    return stmt


async def list_items(
    db: AsyncSession,
    ctx: AuthContext,
    batch_id: uuid.UUID,
    *,
    state: str | None = None,
    presence: str | None = None,
    q: str | None = None,
    limit: int = 200,
    offset: int = 0,
) -> dict:
    batch = await load_batch(db, ctx, batch_id)
    stmt = (
        _filtered_items_stmt(batch.id, state=state, presence=presence, q=q)
        .order_by(BatchItem.created_at.asc(), BatchItem.id.asc())
        .limit(max(1, min(limit, 500)))
        .offset(max(0, offset))
    )
    items = (await db.execute(stmt)).scalars().all()
    counts = await item_counts(db, batch.id)
    return {
        "items": [
            {
                "id": it.id,
                "kind": it.kind,
                "label": it.label,
                "presence": it.presence,
                "state": it.state,
                "error": it.error,
                "payload": it.payload or {},
                "checked_at": it.checked_at.isoformat() if it.checked_at else None,
                "approved_at": it.approved_at.isoformat() if it.approved_at else None,
                "created_at": it.created_at.isoformat() if it.created_at else None,
            }
            for it in items
        ],
        "counts": counts,
    }


async def _select_items(
    db: AsyncSession,
    batch: Batch,
    *,
    item_ids: list[uuid.UUID] | None,
    state: str | None = None,
    presence: str | None = None,
    q: str | None = None,
    allowed_states: tuple[str, ...] = _OPEN_STATES,
) -> list[BatchItem]:
    """Resolve an action's target set: explicit ids, or everything matching the
    filter. Terminal items (approved/rejected) are never re-targeted."""
    if item_ids:
        stmt = select(BatchItem).where(
            BatchItem.batch_id == batch.id, BatchItem.id.in_(item_ids[:20000])
        )
    else:
        stmt = _filtered_items_stmt(batch.id, state=state, presence=presence, q=q)
    stmt = stmt.where(BatchItem.state.in_(allowed_states))
    return list((await db.execute(stmt)).scalars().all())


def _refresh_review_progress(batch: Batch, counts: dict) -> None:
    """totals.done = resolved items; close the batch when nothing is open."""
    by_state = counts.get("by_state", {})
    resolved = int(by_state.get("approved", 0)) + int(by_state.get("rejected", 0))
    open_count = sum(int(by_state.get(s, 0)) for s in _OPEN_STATES)
    batch.totals = {**(batch.totals or {}), "total": counts.get("total", 0), "done": resolved}
    if open_count == 0 and counts.get("total", 0) > 0:
        batch.status = "completed"
        batch.finished_at = _now()
    elif batch.status not in ("running",):
        batch.status = "review"


# ── Checks ───────────────────────────────────────────────────────────────────


async def begin_link_check(
    db: AsyncSession,
    ctx: AuthContext,
    batch_id: uuid.UUID,
    *,
    item_ids: list[uuid.UUID] | None,
    state: str | None = None,
    presence: str | None = None,
    q: str | None = None,
) -> list[uuid.UUID]:
    """Mark link items 'checking' and return their ids for the router to
    enqueue AFTER commit (staged QA runs on the worker — real crawls)."""
    batch = await load_batch(db, ctx, batch_id, review_only=True)
    if batch.kind != "link_review":
        raise ValidationAppError("QA checks apply to links-import batches")
    items = await _select_items(
        db, batch, item_ids=item_ids, state=state or "pending,failed,checked",
        presence=presence, q=q, allowed_states=("pending", "failed", "checked"),
    )
    # Validation failures (no URL) can never crawl — leave them failed.
    runnable = [it for it in items if not (it.state == "failed" and not it.payload.get("source_domain"))]
    for it in runnable:
        it.state = "checking"
        it.error = None
    if runnable:
        batch.status = "running"
        batch.meta = {**(batch.meta or {}), "current_step": f"QA check queued for {len(runnable)} links"}
        db.add(_log(batch.id, f"QA check started for {len(runnable)} staged links (isolated — results stay in this batch)."))
    await db.flush()
    return [it.id for it in runnable]


async def check_domain_items(
    db: AsyncSession,
    ctx: AuthContext,
    batch_id: uuid.UUID,
    *,
    item_ids: list[uuid.UUID] | None,
    providers: set[str] | None = None,
    state: str | None = None,
    presence: str | None = None,
    q: str | None = None,
) -> dict:
    """Fetch DA/PA/Spam (Moz), AS/traffic (Semrush) and age for staged domains,
    INLINE like /source-domains/fetch-metrics, capped per call. Results land in
    ``item.payload['metrics']`` only — the catalog is untouched until approval."""
    batch = await load_batch(db, ctx, batch_id, review_only=True)
    if batch.kind != "domain_import":
        raise ValidationAppError("Metric checks apply to domain-import batches")
    items = await _select_items(
        db, batch, item_ids=item_ids, state=state or "pending,failed,checked",
        presence=presence, q=q, allowed_states=("pending", "failed", "checked"),
    )
    cap = max(1, settings.BATCH_DOMAIN_CHECK_CAP)
    todo, remaining = items[:cap], max(0, len(items) - cap)

    checked = 0
    timeout = httpx.Timeout(settings.DOMAIN_METRICS_TIMEOUT_SECONDS)
    async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
        for it in todo:
            try:
                metrics = await domain_metrics.fetch_all(it.label, client, providers=providers)
                payload = dict(it.payload or {})
                stored = {
                    k: (v.isoformat() if isinstance(v, (datetime, date)) else v)
                    for k, v in metrics.items()
                }
                payload["metrics"] = {**payload.get("metrics", {}), **stored}
                it.payload = payload
                it.state = "checked"
                it.error = None
                it.checked_at = _now()
                checked += 1
            except Exception as exc:  # noqa: BLE001 — one bad domain must not kill the run
                it.state = "failed"
                it.error = f"Metrics check failed: {exc!r}"[:500]
    batch.counters = {**(batch.counters or {}), "api_calls": int((batch.counters or {}).get("api_calls", 0)) + checked}
    scope = "+".join(sorted(providers)) if providers else "all providers"
    db.add(
        _log(
            batch.id,
            f"Checked metrics for {checked} domains ({scope})"
            + (f" — {remaining} still waiting, run the check again." if remaining else "."),
        )
    )
    await db.flush()
    return {"checked": checked, "remaining": remaining}


# ── Decisions ────────────────────────────────────────────────────────────────


async def approve_items(
    db: AsyncSession,
    ctx: AuthContext,
    batch_id: uuid.UUID,
    *,
    item_ids: list[uuid.UUID] | None,
    state: str | None = None,
    presence: str | None = None,
    q: str | None = None,
) -> dict:
    """Approve staged items into the production tables.

    Links: run the normal import pipeline (same dedup/upsert/recompute) via an
    ``Import`` linked to this batch. Domains: upsert into ``source_domains``
    with ``origin='imported'`` carrying any fetched metrics.
    """
    batch = await load_batch(db, ctx, batch_id, review_only=True)
    items = await _select_items(
        db, batch, item_ids=item_ids, state=state, presence=presence, q=q,
        allowed_states=("pending", "checked"),
    )
    if not items:
        return {"approved": 0, "message": "Nothing to approve (only pending/checked items can be approved)"}

    now = _now()
    result: dict = {"approved": len(items)}

    if batch.kind == "link_review":
        from app.models.imports import Import
        from app.services import import_service

        rows = [dict(it.payload.get("mapped") or {}) for it in items]
        source = ImportSource((batch.meta or {}).get("source") or "paste")
        imp = await import_service.create_import(
            db, ctx, project_id=batch.project_id, source=source,
            filename=(batch.meta or {}).get("filename") or None,
        )
        imp.batch_id = batch.id
        await import_service.stage_rows(db, imp, rows)
        for it in items:
            it.state = "approved"
            it.approved_at = now
        import_id = imp.id
        new_ids = await import_service.process(db, import_id)
        # process() commits internally every N rows — re-load for final counters.
        imp = await db.get(Import, import_id)
        result.update(
            {
                "import_id": str(imp.id),
                "new_rows": imp.new_rows or 0,
                "updated_rows": imp.updated_rows or 0,
                "error_rows": imp.error_rows or 0,
            }
        )
        db.add(
            _log(
                batch.id,
                f"Approved {len(items)} links → {imp.new_rows or 0} added, "
                f"{imp.updated_rows or 0} refreshed existing, {imp.error_rows or 0} errors.",
                level="warn" if (imp.error_rows or 0) else "info",
                data={"import_id": str(imp.id)},
            )
        )
        if settings.AUTO_QA_ON_IMPORT and new_ids:
            from app.workers.dispatch import enqueue_backlinks

            enqueue_backlinks(new_ids)
    else:  # domain_import
        inserted = 0
        for it in items:
            m = it.payload.get("metrics") or {}
            values = {
                "workspace_id": ctx.workspace_id,
                "domain_key": it.label,
                "grouping": "registrable",
                "origin": "imported",
                "backlink_count": 0, "indexed_count": 0, "not_indexed_count": 0,
                "uncertain_count": 0, "unchecked_count": 0, "dofollow_count": 0,
                "nofollow_count": 0, "duplicate_count": 0, "project_count": 0,
                "user_count": 0, "link_type_distribution": {},
                "da": m.get("da"), "pa": m.get("pa"), "spam_score": m.get("spam_score"),
                "semrush_as": m.get("semrush_as"), "semrush_traffic": m.get("semrush_traffic"),
                "semrush_keywords": m.get("semrush_keywords"),
                "domain_age_days": m.get("domain_age_days"),
                "domain_created_on": (
                    date.fromisoformat(m["domain_created_on"][:10])
                    if m.get("domain_created_on") else None
                ),
                "metrics_updated_at": (
                    datetime.fromisoformat(m["metrics_updated_at"])
                    if m.get("metrics_updated_at") else None
                ),
            }
            stmt = pg_insert(SourceDomain).values(**values)
            stmt = stmt.on_conflict_do_update(
                constraint="uq_source_domains_ws_domain",
                set_={
                    # Merge metrics without wiping better data already stored.
                    "da": func.coalesce(stmt.excluded.da, SourceDomain.da),
                    "pa": func.coalesce(stmt.excluded.pa, SourceDomain.pa),
                    "spam_score": func.coalesce(stmt.excluded.spam_score, SourceDomain.spam_score),
                    "semrush_as": func.coalesce(stmt.excluded.semrush_as, SourceDomain.semrush_as),
                    "semrush_traffic": func.coalesce(stmt.excluded.semrush_traffic, SourceDomain.semrush_traffic),
                    "semrush_keywords": func.coalesce(stmt.excluded.semrush_keywords, SourceDomain.semrush_keywords),
                    "domain_age_days": func.coalesce(stmt.excluded.domain_age_days, SourceDomain.domain_age_days),
                    "domain_created_on": func.coalesce(stmt.excluded.domain_created_on, SourceDomain.domain_created_on),
                    "metrics_updated_at": func.coalesce(stmt.excluded.metrics_updated_at, SourceDomain.metrics_updated_at),
                    "updated_at": func.now(),
                },
            )
            await db.execute(stmt)
            it.state = "approved"
            it.approved_at = now
            inserted += 1
        result["domains_added"] = inserted
        db.add(
            _log(
                batch.id,
                f"Approved {inserted} domains into the Source Domains catalog "
                "(kept even with zero backlinks — origin: imported).",
            )
        )

    batch.counters = {
        **(batch.counters or {}),
        "approved": int((batch.counters or {}).get("approved", 0)) + len(items),
    }
    # autoflush is off — flush the state changes so the counts query sees them.
    await db.flush()
    counts = await item_counts(db, batch.id)
    _refresh_review_progress(batch, counts)
    await db.flush()
    return result


async def reject_items(
    db: AsyncSession,
    ctx: AuthContext,
    batch_id: uuid.UUID,
    *,
    item_ids: list[uuid.UUID] | None,
    state: str | None = None,
    presence: str | None = None,
    q: str | None = None,
) -> dict:
    batch = await load_batch(db, ctx, batch_id, review_only=True)
    items = await _select_items(
        db, batch, item_ids=item_ids, state=state, presence=presence, q=q,
        allowed_states=_OPEN_STATES,
    )
    now = _now()
    for it in items:
        it.state = "rejected"
        it.approved_at = now
    if items:
        batch.counters = {
            **(batch.counters or {}),
            "rejected": int((batch.counters or {}).get("rejected", 0)) + len(items),
        }
        db.add(_log(batch.id, f"Rejected {len(items)} items — they will never be imported."))
    # autoflush is off — flush the state changes so the counts query sees them.
    await db.flush()
    counts = await item_counts(db, batch.id)
    _refresh_review_progress(batch, counts)
    await db.flush()
    return {"rejected": len(items)}
