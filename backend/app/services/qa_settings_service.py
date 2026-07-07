"""Workspace-overridable QA execution settings (Tranche G).

The crawl/QA engine reads its knobs from ``config.py`` (deploy-wide defaults).
This service lets a workspace admin override a whitelisted, bounds-checked subset
at runtime — stored as a single ``qa_execution`` row in the ``settings`` KV table
(no migration). ``get_effective`` merges stored overrides over the config
defaults, clamping every value, and the staged-QA worker + enqueue path read it so
changes take effect on the next check. Anything not overridden inherits config.

Knobs (all optional; each clamped to a safe range):
  chunk_size        — staged links per worker task
  connect_timeout / read_timeout / total_timeout — HTTP crawl timeouts (seconds)
  rate_per_sec / burst — per-domain politeness (token bucket)
  render_enabled    — use the headless browser for JS pages
  render_timeout_ms — browser page timeout
  render_wait_until — load | domcontentloaded | networkidle
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.settings import Setting

_KEY = "qa_execution"
_WAIT_UNTIL = ("load", "domcontentloaded", "networkidle")

# key → (config attribute for the default, kind, min, max). Bools/enums use kind.
_KNOBS: dict[str, tuple[str, str, float | None, float | None]] = {
    "chunk_size": ("BATCH_QA_CHUNK_SIZE", "int", 1, 200),
    "connect_timeout": ("CRAWL_CONNECT_TIMEOUT", "float", 1, 120),
    "read_timeout": ("CRAWL_READ_TIMEOUT", "float", 1, 300),
    "total_timeout": ("CRAWL_TOTAL_TIMEOUT", "float", 1, 600),
    "rate_per_sec": ("CRAWL_DEFAULT_RATE_PER_SEC", "float", 0.1, 50),
    "burst": ("CRAWL_DEFAULT_BURST", "int", 1, 100),
    "render_enabled": ("RENDER_ENABLED", "bool", None, None),
    "render_timeout_ms": ("RENDER_TIMEOUT_MS", "int", 1000, 120000),
    "render_wait_until": ("RENDER_WAIT_UNTIL", "enum", None, None),
}


def _coerce(key: str, raw, kind: str, lo, hi):
    """Coerce + clamp one value to its kind/range; return None if unusable."""
    try:
        if kind == "bool":
            return bool(raw)
        if kind == "enum":
            v = str(raw)
            return v if v in _WAIT_UNTIL else None
        if kind == "int":
            v = int(float(raw))
        else:
            v = float(raw)
    except (TypeError, ValueError):
        return None
    if lo is not None:
        v = max(lo if kind == "float" else int(lo), v)
    if hi is not None:
        v = min(hi if kind == "float" else int(hi), v)
    return v


def defaults() -> dict:
    """Config-derived defaults for every knob (the deploy-wide baseline)."""
    return {key: getattr(settings, attr) for key, (attr, *_rest) in _KNOBS.items()}


async def _stored(db: AsyncSession, ws: uuid.UUID) -> dict:
    row = (
        await db.execute(
            select(Setting).where(Setting.workspace_id == ws, Setting.key == _KEY)
        )
    ).scalar_one_or_none()
    return dict(row.value or {}) if row is not None else {}


async def get_effective(db: AsyncSession, ws: uuid.UUID) -> dict:
    """Resolved knob values: config defaults with valid workspace overrides applied."""
    base = defaults()
    stored = await _stored(db, ws)
    for key, (attr, kind, lo, hi) in _KNOBS.items():
        if key in stored and stored[key] is not None:
            v = _coerce(key, stored[key], kind, lo, hi)
            if v is not None:
                base[key] = v
    return base


async def describe(db: AsyncSession, ws: uuid.UUID) -> dict:
    """For the admin UI: effective values + per-knob default/min/max/overridden."""
    stored = await _stored(db, ws)
    eff = await get_effective(db, ws)
    meta: dict[str, dict] = {}
    for key, (attr, kind, lo, hi) in _KNOBS.items():
        meta[key] = {
            "default": getattr(settings, attr),
            "min": lo, "max": hi, "kind": kind,
            "overridden": key in stored and stored[key] is not None,
        }
    return {
        "effective": eff,
        "meta": meta,
        "wait_until_choices": list(_WAIT_UNTIL),
    }


async def save(db: AsyncSession, ws: uuid.UUID, overrides: dict) -> dict:
    """Upsert the workspace's QA overrides. Unknown keys ignored; each value
    coerced + clamped. A null/absent value clears that override (back to default)."""
    clean: dict = {}
    for key, (attr, kind, lo, hi) in _KNOBS.items():
        if key not in overrides:
            continue
        raw = overrides[key]
        if raw is None or raw == "":
            continue  # cleared → inherit config default
        v = _coerce(key, raw, kind, lo, hi)
        if v is not None:
            clean[key] = v
    row = (
        await db.execute(
            select(Setting).where(Setting.workspace_id == ws, Setting.key == _KEY)
        )
    ).scalar_one_or_none()
    if row is None:
        db.add(Setting(workspace_id=ws, key=_KEY, value=clean, is_secret=False))
    else:
        row.value = clean
    await db.commit()
    return await describe(db, ws)
