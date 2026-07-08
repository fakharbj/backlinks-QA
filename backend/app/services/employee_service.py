"""Employee code catalog + sheet-user reconciliation (Phase 8, feature 3).

``sync_from_data`` backfills the catalog + mappings from whatever is already on the
backlinks (the sheet "User" label + "Employee Code"), auto-linking a label to an
app user when import previously resolved it (``assigned_user_id``). The rest is
tenant-scoped CRUD with code-uniqueness validation.
"""

from __future__ import annotations

import difflib
import re
import uuid

from sqlalchemy import String, bindparam, cast, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import AuthContext
from app.core.errors import ConflictError, NotFoundError, ValidationAppError
from app.models.backlink import BacklinkRecord
from app.models.employee import EmployeeCode, UserEmployeeMapping
from app.models.user import User, WorkspaceMember
from app.models.workforce import (
    LeaveRequest,
    TaskAssignment,
    TaskWeekTemplate,
    TeamLeadAssignment,
    UserProductivityOverride,
)
from app.schemas.employee import EmployeeCodeCreate, EmployeeCodeUpdate, EmployeeMappingUpdate


async def _app_users(db: AsyncSession, workspace_id: uuid.UUID) -> list[dict]:
    rows = (
        await db.execute(
            select(User.id, User.full_name, User.email)
            .join(WorkspaceMember, WorkspaceMember.user_id == User.id)
            .where(WorkspaceMember.workspace_id == workspace_id)
            .order_by(User.full_name.asc())
        )
    ).all()
    return [{"id": uid, "name": name, "email": email} for uid, name, email in rows]


async def overview(db: AsyncSession, ctx: AuthContext) -> dict:
    users = await _app_users(db, ctx.workspace_id)
    name_by_id = {u["id"]: (u["name"] or u["email"]) for u in users}

    codes = list(
        (
            await db.execute(
                select(EmployeeCode)
                .where(
                    EmployeeCode.workspace_id == ctx.workspace_id,
                    EmployeeCode.deleted_at.is_(None),
                )
                .order_by(EmployeeCode.code.asc())
            )
        ).scalars().all()
    )

    mappings = list(
        (
            await db.execute(
                select(UserEmployeeMapping)
                .where(UserEmployeeMapping.workspace_id == ctx.workspace_id)
                .order_by(UserEmployeeMapping.sheet_user_label.asc())
            )
        ).scalars().all()
    )

    # Backlink counts per sheet label (one grouped query, not per-row).
    counts = dict(
        (
            await db.execute(
                select(BacklinkRecord.assigned_user_label, func.count())
                .where(
                    BacklinkRecord.workspace_id == ctx.workspace_id,
                    BacklinkRecord.assigned_user_label.is_not(None),
                )
                .group_by(BacklinkRecord.assigned_user_label)
            )
        ).all()
    )

    return {
        "codes": [
            {
                "id": c.id, "code": c.code, "display_name": c.display_name,
                "user_id": c.user_id, "user_name": name_by_id.get(c.user_id),
                "is_active": c.is_active,
            }
            for c in codes
        ],
        "mappings": [
            {
                "id": m.id, "sheet_user_label": m.sheet_user_label, "user_id": m.user_id,
                "user_name": name_by_id.get(m.user_id),
                "employee_code_id": m.employee_code_id,
                "is_active": m.is_active,
                "canonical_label": m.canonical_label,
                "backlink_count": int(counts.get(m.sheet_user_label, 0)),
            }
            for m in mappings
        ],
        "app_users": users,
    }


async def sync_from_data(db: AsyncSession, ctx: AuthContext) -> dict:
    """Backfill codes + label mappings from current backlink data (idempotent)."""
    existing_codes = set(
        (
            await db.execute(
                select(EmployeeCode.code).where(EmployeeCode.workspace_id == ctx.workspace_id)
            )
        ).scalars().all()
    )
    code_rows = (
        await db.execute(
            select(func.distinct(BacklinkRecord.employee_code)).where(
                BacklinkRecord.workspace_id == ctx.workspace_id,
                BacklinkRecord.employee_code.is_not(None),
                BacklinkRecord.employee_code != "",
            )
        )
    ).scalars().all()
    new_codes = 0
    for raw in code_rows:
        code = (raw or "").strip()
        if code and code not in existing_codes:
            db.add(EmployeeCode(workspace_id=ctx.workspace_id, code=code))
            existing_codes.add(code)
            new_codes += 1

    existing_labels = set(
        (
            await db.execute(
                select(UserEmployeeMapping.sheet_user_label).where(
                    UserEmployeeMapping.workspace_id == ctx.workspace_id
                )
            )
        ).scalars().all()
    )
    label_rows = (
        await db.execute(
            select(
                BacklinkRecord.assigned_user_label,
                func.min(cast(BacklinkRecord.assigned_user_id, String)),
            )
            .where(
                BacklinkRecord.workspace_id == ctx.workspace_id,
                BacklinkRecord.assigned_user_label.is_not(None),
                BacklinkRecord.assigned_user_label != "",
            )
            .group_by(BacklinkRecord.assigned_user_label)
        )
    ).all()
    new_maps = 0
    for label, any_user in label_rows:
        lbl = (label or "").strip()
        if lbl and lbl not in existing_labels:
            uid = uuid.UUID(any_user) if any_user else None
            db.add(
                UserEmployeeMapping(
                    workspace_id=ctx.workspace_id, sheet_user_label=lbl, user_id=uid
                )
            )
            existing_labels.add(lbl)
            new_maps += 1

    await db.flush()
    return {"new_codes": new_codes, "new_mappings": new_maps}


async def create_code(db: AsyncSession, ctx: AuthContext, payload: EmployeeCodeCreate) -> EmployeeCode:
    code = payload.code.strip()
    exists = (
        await db.execute(
            select(EmployeeCode).where(
                EmployeeCode.workspace_id == ctx.workspace_id,
                EmployeeCode.code == code,
                EmployeeCode.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if exists is not None:
        raise ConflictError("That employee code already exists")
    ec = EmployeeCode(
        workspace_id=ctx.workspace_id, code=code,
        display_name=payload.display_name, user_id=payload.user_id,
    )
    db.add(ec)
    await db.flush()
    return ec


async def _get_code(db: AsyncSession, ctx: AuthContext, code_id: uuid.UUID) -> EmployeeCode:
    ec = await db.get(EmployeeCode, code_id)
    if ec is None or ec.workspace_id != ctx.workspace_id or ec.deleted_at is not None:
        raise NotFoundError("Employee code not found")
    return ec


async def update_code(
    db: AsyncSession, ctx: AuthContext, code_id: uuid.UUID, payload: EmployeeCodeUpdate
) -> EmployeeCode:
    ec = await _get_code(db, ctx, code_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(ec, field, value)
    await db.flush()
    return ec


async def delete_code(db: AsyncSession, ctx: AuthContext, code_id: uuid.UUID) -> None:
    from datetime import datetime, timezone

    ec = await _get_code(db, ctx, code_id)
    ec.deleted_at = datetime.now(timezone.utc)
    ec.deleted_by = ctx.user.id
    ec.is_active = False
    await db.flush()


async def update_mapping(
    db: AsyncSession, ctx: AuthContext, mapping_id: uuid.UUID, payload: EmployeeMappingUpdate
) -> UserEmployeeMapping:
    m = await db.get(UserEmployeeMapping, mapping_id)
    if m is None or m.workspace_id != ctx.workspace_id:
        raise NotFoundError("Mapping not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(m, field, value)
    await db.flush()
    return m


# ── Identity merge (misspelled / alternate spellings of one person) ───────────

def _norm_key(label: str | None) -> str:
    """Fuzzy-comparison key: lowercased, punctuation→space, collapsed, trimmed."""
    return re.sub(r"[^a-z0-9]+", " ", (label or "").strip().lower()).strip()


async def alias_map(db: AsyncSession, workspace_id: uuid.UUID) -> dict[str, str]:
    """{lower(variant_label): canonical_label} for the workspace, chains resolved to
    a fixed point so 'Keven'→'Kevin'→'Kevin K' all land on 'Kevin K'."""
    rows = (
        await db.execute(
            select(UserEmployeeMapping.sheet_user_label, UserEmployeeMapping.canonical_label).where(
                UserEmployeeMapping.workspace_id == workspace_id,
                UserEmployeeMapping.canonical_label.is_not(None),
            )
        )
    ).all()
    raw: dict[str, str] = {}
    for label, canon in rows:
        c = (canon or "").strip()
        if label and c:
            raw[label.strip().lower()] = c
    resolved: dict[str, str] = {}
    for key, canon in raw.items():
        seen = {key}
        cur = canon
        for _ in range(len(raw) + 1):
            nxt = raw.get(cur.strip().lower())
            if nxt is None or cur.strip().lower() in seen:
                break
            seen.add(cur.strip().lower())
            cur = nxt
        resolved[key] = cur
    return resolved


def normalize_label(label: str | None, amap: dict[str, str]) -> str | None:
    """Roll a raw label up to its canonical spelling (case-insensitive); unknown
    labels pass through unchanged."""
    if label is None:
        return None
    cleaned = label.strip()
    if not cleaned:
        return cleaned
    return amap.get(cleaned.lower(), cleaned)


async def _upsert_mapping(
    db: AsyncSession, ctx: AuthContext, label: str, *,
    canonical_label: str | None, user_id: uuid.UUID | None, is_active: bool,
) -> UserEmployeeMapping:
    m = (
        await db.execute(
            select(UserEmployeeMapping).where(
                UserEmployeeMapping.workspace_id == ctx.workspace_id,
                UserEmployeeMapping.sheet_user_label == label,
            )
        )
    ).scalar_one_or_none()
    if m is None:
        m = UserEmployeeMapping(workspace_id=ctx.workspace_id, sheet_user_label=label)
        db.add(m)
    m.canonical_label = canonical_label
    if user_id is not None:
        m.user_id = user_id
    m.is_active = is_active
    return m


async def _canonicalize_label_column(
    db: AsyncSession, workspace_id: uuid.UUID, table: str, col: str,
    canonical: str, alias_lowers: list[str], key_cols: list[str] | None,
) -> None:
    """Rename a workforce label column alias→canonical. For a table whose unique key
    includes the label, first DELETE alias rows that would collide with an existing
    canonical row on the rest of the key (``key_cols``), then UPDATE the rest."""
    if not alias_lowers:
        return
    params = {"ws": workspace_id, "canon": canonical, "aliases": alias_lowers}
    if key_cols:
        keyjoin = " AND ".join([f"t.{k} IS NOT DISTINCT FROM c.{k}" for k in key_cols])
        await db.execute(
            text(
                f"DELETE FROM {table} t USING {table} c "
                f"WHERE t.workspace_id = :ws AND lower(t.{col}) IN :aliases "
                f"AND c.workspace_id = :ws AND lower(c.{col}) = lower(:canon) AND {keyjoin}"
            ).bindparams(bindparam("aliases", expanding=True)),
            params,
        )
    await db.execute(
        text(
            f"UPDATE {table} SET {col} = :canon "
            f"WHERE workspace_id = :ws AND lower({col}) IN :aliases"
        ).bindparams(bindparam("aliases", expanding=True)),
        params,
    )


async def merge_labels(
    db: AsyncSession, ctx: AuthContext, canonical_label: str,
    alias_labels: list[str], user_id: uuid.UUID | None = None,
) -> dict:
    """Fold spelling variants / alternate names of one person into a single canonical
    label. Rewrites existing backlink rows + every parallel workforce label column,
    normalizes future imports (via alias_map), deactivates the alias catalog rows so
    pickers stop offering them, and links them to one app user. Idempotent."""
    canonical = (canonical_label or "").strip()
    if not canonical:
        raise ValidationAppError("A canonical name is required to merge into.")
    seen: set[str] = set()
    aliases: list[str] = []
    for a in alias_labels or []:
        s = (a or "").strip()
        if s and s.lower() != canonical.lower() and s.lower() not in seen:
            seen.add(s.lower())
            aliases.append(s)
    if not aliases:
        raise ValidationAppError("Pick at least one different name to merge into the canonical.")
    alias_lowers = [a.lower() for a in aliases]

    # 1) Canonical is its own identity (canonical_label=NULL), active, carrying user_id.
    canon_map = await _upsert_mapping(
        db, ctx, canonical, canonical_label=None, user_id=user_id, is_active=True
    )
    resolved_uid = user_id or canon_map.user_id
    # 2) Alias rows → point at canonical, deactivated (hidden from pickers), same user.
    for a in aliases:
        await _upsert_mapping(
            db, ctx, a, canonical_label=canonical, user_id=resolved_uid, is_active=False
        )
    # 3) Flatten chains: rows that pointed at an alias now point at canonical.
    await db.execute(
        update(UserEmployeeMapping)
        .where(
            UserEmployeeMapping.workspace_id == ctx.workspace_id,
            func.lower(UserEmployeeMapping.canonical_label).in_(alias_lowers),
        )
        .values(canonical_label=canonical)
    )
    # 4) Rewrite existing backlinks (aliases + any stray case-variant of the canonical).
    match_lowers = alias_lowers + [canonical.lower()]
    vals: dict = {"assigned_user_label": canonical}
    if resolved_uid is not None:
        vals["assigned_user_id"] = resolved_uid
    res = await db.execute(
        update(BacklinkRecord)
        .where(
            BacklinkRecord.workspace_id == ctx.workspace_id,
            func.lower(func.btrim(BacklinkRecord.assigned_user_label)).in_(match_lowers),
        )
        .values(**vals)
    )
    rows_relabeled = res.rowcount or 0
    # 5) Canonicalize the parallel workforce label columns (conflict-safe on uniques).
    await _canonicalize_label_column(
        db, ctx.workspace_id, TaskAssignment.__tablename__, "user_label",
        canonical, alias_lowers, key_cols=["project_id", "day"],
    )
    await _canonicalize_label_column(
        db, ctx.workspace_id, TaskWeekTemplate.__tablename__, "user_label",
        canonical, alias_lowers, key_cols=["weekday", "project_id"],
    )
    await _canonicalize_label_column(
        db, ctx.workspace_id, UserProductivityOverride.__tablename__, "user_label",
        canonical, alias_lowers, key_cols=["link_type_name"],
    )
    await _canonicalize_label_column(
        db, ctx.workspace_id, TeamLeadAssignment.__tablename__, "member_label",
        canonical, alias_lowers, key_cols=["manager_user_id"],
    )
    await _canonicalize_label_column(
        db, ctx.workspace_id, LeaveRequest.__tablename__, "user_label",
        canonical, alias_lowers, key_cols=None,
    )
    await db.flush()
    return {
        "canonical_label": canonical, "alias_labels": aliases,
        "rows_relabeled": int(rows_relabeled), "mappings_upserted": len(aliases) + 1,
    }


async def suggest_label_groups(db: AsyncSession, ctx: AuthContext, threshold: float | None = None) -> dict:
    """Cluster sheet-user labels that look like spelling variants of one person
    (difflib on a normalized key). Suggestions only — a manual merge confirms, and
    genuinely different names for one person (Kashif == Kevin) aren't detected."""
    thr = threshold if threshold is not None else settings.EMPLOYEE_LABEL_SUGGEST_THRESHOLD
    counts: dict[str, int] = {}
    for lbl, n in (
        await db.execute(
            select(BacklinkRecord.assigned_user_label, func.count())
            .where(
                BacklinkRecord.workspace_id == ctx.workspace_id,
                BacklinkRecord.assigned_user_label.is_not(None),
                func.btrim(BacklinkRecord.assigned_user_label) != "",
            )
            .group_by(BacklinkRecord.assigned_user_label)
        )
    ).all():
        if lbl and lbl.strip():
            counts[lbl] = int(n)
    # Include catalogued, not-yet-merged labels (count 0) so zero-row spellings show.
    for lbl in (
        await db.execute(
            select(UserEmployeeMapping.sheet_user_label).where(
                UserEmployeeMapping.workspace_id == ctx.workspace_id,
                UserEmployeeMapping.canonical_label.is_(None),
            )
        )
    ).scalars().all():
        if lbl and lbl.strip():
            counts.setdefault(lbl, 0)

    labels = sorted(counts.items(), key=lambda t: (-t[1], _norm_key(t[0])))
    clusters: list[dict] = []
    for label, cnt in labels:
        key = _norm_key(label)
        best = None
        for c in clusters:
            ratio = difflib.SequenceMatcher(None, key, c["seed_key"]).ratio()
            if ratio >= thr and (best is None or ratio > best[1]):
                best = (c, ratio)
        if best:
            c, ratio = best
            c["members"].append({"label": label, "backlink_count": cnt})
            c["min_ratio"] = min(c["min_ratio"], ratio)
        else:
            clusters.append({
                "key": key or label, "seed_key": key, "canonical": label,
                "members": [{"label": label, "backlink_count": cnt}], "min_ratio": 1.0,
            })
    out = [
        {
            "key": c["key"], "canonical": c["canonical"], "score": round(c["min_ratio"], 3),
            "members": sorted(c["members"], key=lambda x: -x["backlink_count"]),
        }
        for c in clusters if len(c["members"]) >= 2
    ]
    out.sort(key=lambda c: (-len(c["members"]), -sum(m["backlink_count"] for m in c["members"])))
    return {"clusters": out}
