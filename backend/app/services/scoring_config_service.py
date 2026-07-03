"""Resolve + manage versioned scoring rule sets (Phase 8 F17–19).

Resolution MERGES the scope chain so overrides are sparse and inherit:

    global  →  workspace  →  link_type  →  project        (most specific wins)

A project that configures only ``link_rel.nofollow`` inherits every other
parameter from the workspace/global rule set; anything still unset falls back to
the QA engine's severity model. ``resolve()`` (the crawl hot path) returns the
merged ``ResolvedRuleset`` stamped with the *most specific* version id present.

The config UI uses ``effective_config`` (this scope's own sparse overrides + what
it inherits) and ``save_version`` (immutable, sequential versions; the previous
latest is retired, never edited in place).
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationAppError
from app.models.scoring import ScoringParameter, ScoringRuleVersion
from app.qa.scoring_rules import DEFAULT_RULESET, ResolvedRuleset

_SCOPES = ("global", "workspace", "link_type", "project", "project_link_type")
_DEFAULT_BANDS = {"fail_below": 30, "warn_below": 80}


async def _latest(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID | None,
    scope: str,
    scope_ref_id: uuid.UUID | None,
    link_type_id: uuid.UUID | None = None,
) -> ScoringRuleVersion | None:
    stmt = select(ScoringRuleVersion).where(
        ScoringRuleVersion.scope == scope,
        ScoringRuleVersion.is_latest.is_(True),
    )
    if scope == "global":
        stmt = stmt.where(ScoringRuleVersion.workspace_id.is_(None))
    else:
        stmt = stmt.where(ScoringRuleVersion.workspace_id == workspace_id)
    if scope_ref_id is None:
        stmt = stmt.where(ScoringRuleVersion.scope_ref_id.is_(None))
    else:
        stmt = stmt.where(ScoringRuleVersion.scope_ref_id == scope_ref_id)
    if link_type_id is None:
        stmt = stmt.where(ScoringRuleVersion.link_type_id.is_(None))
    else:
        stmt = stmt.where(ScoringRuleVersion.link_type_id == link_type_id)
    return (await db.execute(stmt.limit(1))).scalars().first()


def _merge_into(base: dict, overrides: dict) -> None:
    for param, outcomes in (overrides or {}).items():
        if isinstance(outcomes, dict):
            base.setdefault(param, {}).update(outcomes)


async def _merged_chain(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID | None,
    project_id: uuid.UUID | None,
    link_type_id: uuid.UUID | None,
) -> ResolvedRuleset:
    """Merge global→workspace→link_type→project→project×link_type (least→most
    specific). The last hop is the owners' "each project configures each link
    type" grid — it wins over everything else for that combination."""
    chain: list[tuple[str, uuid.UUID | None, uuid.UUID | None]] = [("global", None, None)]
    if workspace_id is not None:
        chain.append(("workspace", None, None))
    if link_type_id is not None:
        chain.append(("link_type", link_type_id, None))
    if project_id is not None:
        chain.append(("project", project_id, None))
    if project_id is not None and link_type_id is not None:
        chain.append(("project_link_type", project_id, link_type_id))

    merged_rules: dict = {}
    bands = dict(_DEFAULT_BANDS)
    version_id: uuid.UUID | None = None
    for scope, ref, lt in chain:
        ws = None if scope == "global" else workspace_id
        row = await _latest(db, workspace_id=ws, scope=scope, scope_ref_id=ref, link_type_id=lt)
        if row is None:
            continue
        _merge_into(merged_rules, row.rules or {})
        if row.bands:
            bands = dict(row.bands)
        version_id = row.id  # most specific present wins
    if version_id is None:
        return DEFAULT_RULESET
    return ResolvedRuleset(version_id=version_id, scope=chain[-1][0], rules=merged_rules, bands=bands)


async def resolve(
    db: AsyncSession,
    workspace_id: uuid.UUID | None,
    project_id: uuid.UUID | None = None,
    link_type_id: uuid.UUID | None = None,
) -> ResolvedRuleset:
    """Merged, most-specific rule set for a backlink (the crawl hot path)."""
    return await _merged_chain(
        db, workspace_id=workspace_id, project_id=project_id, link_type_id=link_type_id
    )


async def list_parameters(db: AsyncSession) -> list[ScoringParameter]:
    """The active scoring-parameter registry (the editable grid), in display order."""
    return list(
        (
            await db.execute(
                select(ScoringParameter)
                .where(ScoringParameter.is_active.is_(True))
                .order_by(ScoringParameter.sort_order.asc())
            )
        )
        .scalars()
        .all()
    )


def _validate_scope(
    scope: str, scope_ref_id: uuid.UUID | None, link_type_id: uuid.UUID | None = None
) -> None:
    if scope not in _SCOPES:
        raise ValidationAppError(f"Unknown scope '{scope}'.")
    if scope in ("project", "link_type") and scope_ref_id is None:
        raise ValidationAppError(f"scope '{scope}' requires scope_ref_id.")
    if scope in ("global", "workspace") and scope_ref_id is not None:
        raise ValidationAppError(f"scope '{scope}' must not have scope_ref_id.")
    if scope == "project_link_type" and (scope_ref_id is None or link_type_id is None):
        raise ValidationAppError(
            "scope 'project_link_type' needs both the project and the link type."
        )
    if scope != "project_link_type" and link_type_id is not None:
        raise ValidationAppError(f"scope '{scope}' must not have link_type_id.")


async def effective_config(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    scope: str,
    scope_ref_id: uuid.UUID | None,
    link_type_id: uuid.UUID | None = None,
) -> dict:
    """For the config grid: this scope's OWN sparse overrides + bands + version,
    plus the rule set it INHERITS from its parents (so the UI shows placeholders)."""
    _validate_scope(scope, scope_ref_id, link_type_id)
    ws = None if scope == "global" else workspace_id
    own = await _latest(
        db, workspace_id=ws, scope=scope, scope_ref_id=scope_ref_id, link_type_id=link_type_id
    )

    # Parents of this scope (what applies when a cell is left unset).
    if scope == "global":
        inherited = DEFAULT_RULESET
    elif scope == "workspace":
        inherited = await _merged_chain(db, workspace_id=None, project_id=None, link_type_id=None)
    elif scope == "project_link_type":
        # Inherits everything below it: global + workspace + the link type's own
        # rules + the project's default rules.
        inherited = await _merged_chain(
            db, workspace_id=workspace_id, project_id=scope_ref_id, link_type_id=link_type_id
        )
        # _merged_chain includes the project_link_type row itself when it exists;
        # recompute WITHOUT it so placeholders show only what's inherited.
        if own is not None:
            base: dict = {}
            for s, ref, lt in (
                ("global", None, None),
                ("workspace", None, None),
                ("link_type", link_type_id, None),
                ("project", scope_ref_id, None),
            ):
                row = await _latest(
                    db, workspace_id=None if s == "global" else workspace_id,
                    scope=s, scope_ref_id=ref, link_type_id=lt,
                )
                if row is not None:
                    _merge_into(base, row.rules or {})
            inherited = ResolvedRuleset(rules=base, bands=inherited.bands)
    else:  # project or link_type → inherit global + workspace
        inherited = await _merged_chain(
            db, workspace_id=workspace_id, project_id=None, link_type_id=None
        )

    return {
        "scope": scope,
        "scope_ref_id": scope_ref_id,
        "link_type_id": link_type_id,
        "version": own.version if own else 0,
        "version_id": own.id if own else None,
        "rules": dict(own.rules or {}) if own else {},
        "bands": dict(own.bands or {}) if own and own.bands else dict(_DEFAULT_BANDS),
        "inherited_rules": inherited.rules,
        "inherited_bands": inherited.bands or dict(_DEFAULT_BANDS),
        "note": own.note if own else None,
    }


async def save_version(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    scope: str,
    scope_ref_id: uuid.UUID | None,
    rules: dict,
    bands: dict | None,
    note: str | None,
    created_by: uuid.UUID | None,
    link_type_id: uuid.UUID | None = None,
) -> ScoringRuleVersion:
    """Create the next immutable version for a scope, retiring the previous latest."""
    _validate_scope(scope, scope_ref_id, link_type_id)
    ws = None if scope == "global" else workspace_id

    # Serialize the retire-prior + insert-next-version sequence per scope so two
    # concurrent saves can't both compute the same version / both set is_latest
    # (NULL scope_ref makes a DB partial-unique index unreliable). Transaction-scoped
    # advisory lock releases on commit.
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
        {"lock_key": f"scoring:{scope}:{scope_ref_id}:{link_type_id}:{ws}"},
    )

    base = select(ScoringRuleVersion).where(ScoringRuleVersion.scope == scope)
    base = base.where(
        ScoringRuleVersion.workspace_id.is_(None) if scope == "global"
        else ScoringRuleVersion.workspace_id == ws
    )
    base = base.where(
        ScoringRuleVersion.scope_ref_id.is_(None) if scope_ref_id is None
        else ScoringRuleVersion.scope_ref_id == scope_ref_id
    )
    base = base.where(
        ScoringRuleVersion.link_type_id.is_(None) if link_type_id is None
        else ScoringRuleVersion.link_type_id == link_type_id
    )
    rows = (await db.execute(base)).scalars().all()
    next_version = 1 + max((r.version for r in rows), default=0)
    for r in rows:
        if r.is_latest:
            r.is_latest = False

    row = ScoringRuleVersion(
        workspace_id=ws,
        scope=scope,
        scope_ref_id=scope_ref_id,
        link_type_id=link_type_id,
        version=next_version,
        is_latest=True,
        rules=_clean_rules(rules),
        bands=bands or dict(_DEFAULT_BANDS),
        note=note,
        created_by=created_by,
    )
    db.add(row)
    await db.flush()
    return row


def _clean_rules(rules: dict) -> dict:
    """Keep only well-formed {param: {outcome: int}} entries (drop blanks/nulls)."""
    out: dict = {}
    for param, outcomes in (rules or {}).items():
        if not isinstance(outcomes, dict):
            continue
        clean: dict = {}
        for outcome, pts in outcomes.items():
            if pts is None or pts == "":
                continue
            try:
                clean[outcome] = int(pts)
            except (TypeError, ValueError):
                continue
        if clean:
            out[param] = clean
    return out


async def list_versions(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    scope: str,
    scope_ref_id: uuid.UUID | None,
    link_type_id: uuid.UUID | None = None,
) -> list[ScoringRuleVersion]:
    _validate_scope(scope, scope_ref_id, link_type_id)
    ws = None if scope == "global" else workspace_id
    stmt = select(ScoringRuleVersion).where(ScoringRuleVersion.scope == scope)
    stmt = stmt.where(
        ScoringRuleVersion.workspace_id.is_(None) if scope == "global"
        else ScoringRuleVersion.workspace_id == ws
    )
    stmt = stmt.where(
        ScoringRuleVersion.scope_ref_id.is_(None) if scope_ref_id is None
        else ScoringRuleVersion.scope_ref_id == scope_ref_id
    )
    stmt = stmt.where(
        ScoringRuleVersion.link_type_id.is_(None) if link_type_id is None
        else ScoringRuleVersion.link_type_id == link_type_id
    )
    return list((await db.execute(stmt.order_by(ScoringRuleVersion.version.desc()))).scalars().all())
