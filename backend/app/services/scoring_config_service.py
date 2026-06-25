"""Resolve + manage versioned scoring rule sets (Phase 8 F17–19).

``resolve()`` is the hot path used by the crawl worker: given a backlink's
workspace / project / link-type it returns the most-specific *latest*
``ResolvedRuleset`` to hand to the QA engine. Precedence (most specific wins):

    project  →  link_type  →  workspace  →  global

If nothing is configured it falls back to ``DEFAULT_RULESET`` (empty overrides +
standard 30/80 bands), i.e. today's behaviour. The seeded system-global v1 is the
backstop so a resolution always succeeds.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.scoring import ScoringParameter, ScoringRuleVersion
from app.qa.scoring_rules import DEFAULT_RULESET, ResolvedRuleset


def _to_ruleset(row: ScoringRuleVersion) -> ResolvedRuleset:
    return ResolvedRuleset(
        version_id=row.id,
        scope=row.scope,
        rules=dict(row.rules or {}),
        bands=dict(row.bands or {}),
    )


async def _latest(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID | None,
    scope: str,
    scope_ref_id: uuid.UUID | None,
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
    return (await db.execute(stmt.limit(1))).scalars().first()


async def resolve(
    db: AsyncSession,
    workspace_id: uuid.UUID | None,
    project_id: uuid.UUID | None = None,
    link_type_id: uuid.UUID | None = None,
) -> ResolvedRuleset:
    """Most-specific latest rule set for a backlink (project→link_type→workspace→global)."""
    if project_id is not None:
        row = await _latest(db, workspace_id=workspace_id, scope="project", scope_ref_id=project_id)
        if row is not None:
            return _to_ruleset(row)
    if link_type_id is not None:
        row = await _latest(
            db, workspace_id=workspace_id, scope="link_type", scope_ref_id=link_type_id
        )
        if row is not None:
            return _to_ruleset(row)
    if workspace_id is not None:
        row = await _latest(db, workspace_id=workspace_id, scope="workspace", scope_ref_id=None)
        if row is not None:
            return _to_ruleset(row)
    row = await _latest(db, workspace_id=None, scope="global", scope_ref_id=None)
    if row is not None:
        return _to_ruleset(row)
    return DEFAULT_RULESET


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
