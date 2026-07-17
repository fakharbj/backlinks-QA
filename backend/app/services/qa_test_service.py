"""Temp QA lab service (Phase 11) — candidate backlink tests, fully isolated.

CRUD for QA test batches + their links, plus a summary. Auto-QA is queued to
the isolated worker (``tasks.qa_test.run_test``) which writes results only to
``qa_test_links``. Nothing here reads or writes production tables.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import AuthContext
from app.core.errors import NotFoundError, ValidationAppError
from app.models.qa_test import QATestBatch, QATestLink

# Column-name → canonical field, matched against a detected header row.
_COL_ALIASES = {
    "source_url": ("links", "link", "url", "source url", "source_url", "source", "backlink", "backlinks", "page"),
    "link_type": ("type", "link type", "link_type", "category"),
    "account_email": ("email", "e-mail", "mail", "account email", "login"),
    "account_password": ("password", "pass", "pwd", "account password"),
    "claimed_da": ("da", "domain authority", "da score"),
    "claimed_spam": ("ss", "spam", "spam score", "spam_score", "ss score"),
    "target_url": ("target", "target url", "target_url", "destination"),
    "anchor_text": ("anchor", "anchor text", "anchor_text"),
}
_HEADER_HINTS = ("link", "url", "source", "backlink")
_URL_RE = re.compile(r"https?://", re.I)


def _split_row(line: str) -> list[str]:
    """Split a pasted row on TAB (sheet paste) or comma (CSV). Tabs win when
    present, so URLs containing commas survive a tab-delimited paste."""
    if "\t" in line:
        return [c.strip() for c in line.split("\t")]
    return [c.strip() for c in line.split(",")]


def _int_or_none(v: str | None) -> int | None:
    if not v:
        return None
    m = re.search(r"-?\d+", v)
    return int(m.group()) if m else None


def _map_header(cells: list[str]) -> dict[int, str] | None:
    """If these cells look like a header row, return {col index → canonical
    field}. A header must place a URL/link column somewhere."""
    idx: dict[int, str] = {}
    for i, c in enumerate(cells):
        key = c.strip().lower()
        for field, aliases in _COL_ALIASES.items():
            if key in aliases:
                idx[i] = field
                break
    if any(f == "source_url" for f in idx.values()):
        return idx
    return None


def parse_test_links(text: str) -> list[dict]:
    """Parse a candidate's submission — tolerant of the real trial-task sheet.

    Handles: a free-text task brief above the table (ignored), a header row
    like ``Links  Type  Email  Password  DA  SS`` (TAB or comma separated),
    grouped rows with blank separators, ``competitor`` rows (no creds), and
    the simple fallbacks (one URL per line, or a plain CSV). Every row must
    contain a URL to count."""
    text = (text or "").strip()
    if not text:
        return []
    rows = [ln for ln in text.splitlines() if ln.strip()]
    # 1) Find a header row anywhere in the paste (skips the task-brief lines).
    header: dict[int, str] | None = None
    body_start = 0
    for i, line in enumerate(rows):
        low = line.lower()
        if any(h in low for h in _HEADER_HINTS) and ("\t" in line or "," in line):
            mapped = _map_header(_split_row(line))
            if mapped:
                header, body_start = mapped, i + 1
                break

    out: list[dict] = []
    if header is not None:
        src_idx = next(i for i, f in header.items() if f == "source_url")
        for line in rows[body_start:]:
            cells = _split_row(line)
            if len(cells) <= src_idx:
                continue
            src = cells[src_idx].strip()
            if not _URL_RE.search(src):
                continue  # separator / stray line
            rec: dict = {"source_url": src}
            for i, field in header.items():
                if i == src_idx or i >= len(cells):
                    continue
                val = cells[i].strip()
                if not val:
                    continue
                if field in ("claimed_da", "claimed_spam"):
                    rec[field] = _int_or_none(val)
                else:
                    rec[field] = val
            lt = (rec.get("link_type") or "").strip().lower()
            rec["is_competitor"] = "competitor" in lt or "compitor" in lt
            out.append(rec)
        return out[:500]

    # 2) Fallbacks: bare URL per line, or "url, target, anchor, type".
    for line in rows:
        if not _URL_RE.search(line):
            continue
        parts = _split_row(line)
        out.append({
            "source_url": parts[0],
            "target_url": parts[1] if len(parts) > 1 and parts[1] else None,
            "anchor_text": parts[2] if len(parts) > 2 and parts[2] else None,
            "link_type": parts[3] if len(parts) > 3 and parts[3] else None,
            "is_competitor": False,
        })
    return out[:500]


async def create_batch(
    db: AsyncSession, ctx: AuthContext, *, candidate_name: str,
    candidate_email: str | None, role_applied: str | None, notes: str | None,
    links_text: str, default_target: str | None = None, brief: str | None = None,
) -> QATestBatch:
    name = (candidate_name or "").strip()
    if not name:
        raise ValidationAppError("Candidate name is required.")
    parsed = parse_test_links(links_text)
    if not parsed:
        raise ValidationAppError("Add at least one link (paste the candidate's sheet, or one URL per line).")
    batch = QATestBatch(
        workspace_id=ctx.workspace_id, candidate_name=name[:200],
        candidate_email=(candidate_email or "").strip()[:255] or None,
        role_applied=(role_applied or "").strip()[:120] or None,
        notes=(notes or "").strip()[:1000] or None,
        brief=(brief or "").strip()[:8000] or None,
        status="draft", created_by=ctx.user.id,
    )
    db.add(batch)
    await db.flush()
    now = datetime.now(timezone.utc)
    for row in parsed:
        is_comp = bool(row.get("is_competitor"))
        db.add(QATestLink(
            batch_id=batch.id, workspace_id=ctx.workspace_id,
            source_url=row["source_url"][:2000],
            # Competitor rows are references, not backlinks — no target defaulting.
            target_url=(row.get("target_url") or (None if is_comp else default_target) or None),
            anchor_text=(row.get("anchor_text") or None),
            link_type=(row.get("link_type") or None),
            account_email=(row.get("account_email") or None),
            account_password=(row.get("account_password") or None),
            claimed_da=row.get("claimed_da"),
            claimed_spam=row.get("claimed_spam"),
            is_competitor=is_comp,
            # Competitors skip QA entirely — recorded as a reference.
            state="reference" if is_comp else "pending",
            created_at=now,
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
        "notes": b.notes, "brief": b.brief, "status": b.status,
        "created_at": b.created_at.isoformat() if b.created_at else None,
        "links": [
            {
                "id": str(x.id), "source_url": x.source_url, "target_url": x.target_url,
                "anchor_text": x.anchor_text, "link_type": x.link_type,
                "account_email": x.account_email, "account_password": x.account_password,
                "claimed_da": x.claimed_da, "claimed_spam": x.claimed_spam,
                "is_competitor": x.is_competitor,
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
    # Competitor references are never QA'd — leave their state untouched.
    await db.execute(
        QATestLink.__table__.update()
        .where(QATestLink.batch_id == b.id, QATestLink.is_competitor.is_(False))
        .values(state="checking")
    )
    await db.flush()
    return b
