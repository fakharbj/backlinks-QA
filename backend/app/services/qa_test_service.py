"""Temp QA lab service (Phase 11) — candidate backlink tests, fully isolated.

CRUD for QA test batches + their links, plus a summary. Auto-QA is queued to
the isolated worker (``tasks.qa_test.run_test``) which writes results only to
``qa_test_links``. Nothing here reads or writes production tables.
"""

from __future__ import annotations

import csv
import io
import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import AuthContext
from app.core.errors import NotFoundError, ValidationAppError
from app.models.qa_test import QATestBatch, QATestLink

_HEADER_HINTS = {"source", "source url", "url", "source_url", "link"}


def parse_test_links(text: str) -> list[dict]:
    """Parse pasted links. Accepts one URL per line, OR CSV with a header row
    (source_url[,target_url,anchor,link_type]). Bare-URL lines always work."""
    text = (text or "").strip()
    if not text:
        return []
    lines = [ln for ln in text.splitlines() if ln.strip()]
    first = lines[0].lower()
    has_header = ("," in first or "\t" in first) and any(h in first for h in _HEADER_HINTS)
    out: list[dict] = []
    if has_header:
        rdr = csv.DictReader(io.StringIO(text))
        for row in rdr:
            low = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
            src = low.get("source_url") or low.get("source url") or low.get("source") or low.get("url") or low.get("link")
            if not src:
                continue
            out.append({
                "source_url": src,
                "target_url": low.get("target_url") or low.get("target") or low.get("target url") or None,
                "anchor_text": low.get("anchor") or low.get("anchor_text") or low.get("anchor text") or None,
                "link_type": low.get("link_type") or low.get("type") or low.get("link type") or None,
            })
    else:
        for ln in lines:
            # tolerate "url , target , anchor , type" without a header too
            parts = [p.strip() for p in ln.split(",")] if ("," in ln) else [ln.strip()]
            if not parts[0]:
                continue
            out.append({
                "source_url": parts[0],
                "target_url": parts[1] if len(parts) > 1 and parts[1] else None,
                "anchor_text": parts[2] if len(parts) > 2 and parts[2] else None,
                "link_type": parts[3] if len(parts) > 3 and parts[3] else None,
            })
    return out[:500]  # hard cap per test


async def create_batch(
    db: AsyncSession, ctx: AuthContext, *, candidate_name: str,
    candidate_email: str | None, role_applied: str | None, notes: str | None,
    links_text: str, default_target: str | None = None,
) -> QATestBatch:
    name = (candidate_name or "").strip()
    if not name:
        raise ValidationAppError("Candidate name is required.")
    parsed = parse_test_links(links_text)
    if not parsed:
        raise ValidationAppError("Add at least one link (one source URL per line).")
    batch = QATestBatch(
        workspace_id=ctx.workspace_id, candidate_name=name[:200],
        candidate_email=(candidate_email or "").strip()[:255] or None,
        role_applied=(role_applied or "").strip()[:120] or None,
        notes=(notes or "").strip()[:1000] or None,
        status="draft", created_by=ctx.user.id,
    )
    db.add(batch)
    await db.flush()
    now = datetime.now(timezone.utc)
    for row in parsed:
        db.add(QATestLink(
            batch_id=batch.id, workspace_id=ctx.workspace_id,
            source_url=row["source_url"][:2000],
            target_url=(row.get("target_url") or default_target or None),
            anchor_text=(row.get("anchor_text") or None),
            link_type=(row.get("link_type") or None),
            state="pending", created_at=now,
        ))
    await db.flush()
    return batch


async def list_batches(db: AsyncSession, ctx: AuthContext) -> list[dict]:
    rows = (
        await db.execute(
            select(QATestBatch)
            .where(QATestBatch.workspace_id == ctx.workspace_id)
            .order_by(QATestBatch.created_at.desc())
            .limit(200)
        )
    ).scalars().all()
    # Per-batch counters in one grouped query.
    counts = (
        await db.execute(
            select(
                QATestLink.batch_id,
                func.count(),
                func.count().filter(QATestLink.state == "checked"),
                func.count().filter(QATestLink.status == "PASS"),
                func.count().filter(QATestLink.status == "FAIL"),
                func.avg(QATestLink.score).filter(QATestLink.score.is_not(None)),
            )
            .where(QATestLink.workspace_id == ctx.workspace_id)
            .group_by(QATestLink.batch_id)
        )
    ).all()
    by_batch = {r[0]: r for r in counts}
    out = []
    for b in rows:
        c = by_batch.get(b.id)
        out.append({
            "id": str(b.id), "candidate_name": b.candidate_name,
            "candidate_email": b.candidate_email, "role_applied": b.role_applied,
            "notes": b.notes, "status": b.status,
            "created_at": b.created_at.isoformat() if b.created_at else None,
            "total": int(c[1]) if c else 0,
            "checked": int(c[2]) if c else 0,
            "passed": int(c[3]) if c else 0,
            "failed": int(c[4]) if c else 0,
            "avg_score": round(float(c[5]), 1) if c and c[5] is not None else None,
        })
    return out


async def _get(db: AsyncSession, ctx: AuthContext, batch_id: uuid.UUID) -> QATestBatch:
    b = await db.get(QATestBatch, batch_id)
    if b is None or b.workspace_id != ctx.workspace_id:
        raise NotFoundError("QA test not found")
    return b


async def get_batch(db: AsyncSession, ctx: AuthContext, batch_id: uuid.UUID) -> dict:
    b = await _get(db, ctx, batch_id)
    links = (
        await db.execute(
            select(QATestLink).where(QATestLink.batch_id == b.id).order_by(QATestLink.created_at)
        )
    ).scalars().all()
    return {
        "id": str(b.id), "candidate_name": b.candidate_name,
        "candidate_email": b.candidate_email, "role_applied": b.role_applied,
        "notes": b.notes, "status": b.status,
        "created_at": b.created_at.isoformat() if b.created_at else None,
        "links": [
            {
                "id": str(x.id), "source_url": x.source_url, "target_url": x.target_url,
                "anchor_text": x.anchor_text, "link_type": x.link_type,
                "state": x.state, "status": x.status, "score": x.score,
                "link_found": x.link_found, "http_status": x.http_status,
                "current_rel": x.current_rel, "current_anchor": x.current_anchor,
                "indexability": x.indexability, "matched_href": x.matched_href,
                "top_issue": x.top_issue, "facts": x.facts or {}, "error": x.error,
                "checked_at": x.checked_at.isoformat() if x.checked_at else None,
            }
            for x in links
        ],
    }


async def delete_batch(db: AsyncSession, ctx: AuthContext, batch_id: uuid.UUID) -> None:
    b = await _get(db, ctx, batch_id)
    await db.execute(delete(QATestLink).where(QATestLink.batch_id == b.id))
    await db.execute(delete(QATestBatch).where(QATestBatch.id == b.id))


async def mark_running(db: AsyncSession, ctx: AuthContext, batch_id: uuid.UUID) -> QATestBatch:
    b = await _get(db, ctx, batch_id)
    b.status = "running"
    await db.execute(
        QATestLink.__table__.update()
        .where(QATestLink.batch_id == b.id)
        .values(state="checking")
    )
    await db.flush()
    return b
