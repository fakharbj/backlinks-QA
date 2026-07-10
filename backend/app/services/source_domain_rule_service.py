"""Source-domain qualification rules engine (0033).

A rule's ``definition`` is a whitelisted condition tree:

    {"match": "all"|"any",
     "conditions": [{"field": <whitelisted>, "op": ">="|"<="|">"|"<"|"=="|"between",
                     "value": <num>, "value2"?: <num>, "value_str"?: <str>}]}

Whitelisted fields are the SAME metric/pct set the Source-Domains list filters use
(``source_domain_service._NUMERIC_FILTER_COLUMNS``) plus the string fields:
``origin`` and the Phase 10 ``robots_band``/``market``/``country``. The
definition is validated against the whitelist BOTH on write and at apply-time, and
translated into the very same column comparisons the list builder uses — user
input is never interpolated into SQL.
"""

from __future__ import annotations

import uuid

from sqlalchemy import ColumnElement, and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import AuthContext
from app.core.errors import ConflictError, NotFoundError, ValidationAppError
from app.models.source_domain import SourceDomain
from app.models.source_domain_rule import SourceDomainRule
from app.schemas.source_domain import SourceDomainRuleCreate, SourceDomainRuleUpdate
from app.services import source_domain_service as sd_svc

# Whitelisted numeric fields = the same set the list filters expose.
_NUMERIC_FIELDS = set(sd_svc._NUMERIC_FILTER_COLUMNS)
# String fields ('==' only): origin plus the Phase 10 string filters
# (robots_band / market / country) — same lockstep source as the list.
_STRING_FIELDS = {"origin"} | set(sd_svc._STRING_FILTER_COLUMNS)
_STRING_COLUMNS: dict[str, ColumnElement] = {
    "origin": SourceDomain.origin,
    **sd_svc._STRING_FILTER_COLUMNS,
}
_ALL_FIELDS = _NUMERIC_FIELDS | _STRING_FIELDS
_MATCH = {"all", "any"}
_OPS = sd_svc._OPS


def _validate_definition(definition: dict) -> dict:
    """Validate + normalize a rule definition against the whitelist. Raises on any
    unknown field/op or malformed condition. Returns a clean dict to store."""
    if not isinstance(definition, dict):
        raise ValidationAppError("Rule definition must be an object")
    match = str(definition.get("match", "all")).lower()
    if match not in _MATCH:
        raise ValidationAppError("Rule 'match' must be 'all' or 'any'")
    raw_conditions = definition.get("conditions") or []
    if not isinstance(raw_conditions, list) or not raw_conditions:
        raise ValidationAppError("A rule needs at least one condition")

    clean: list[dict] = []
    for c in raw_conditions:
        if not isinstance(c, dict):
            raise ValidationAppError("Each condition must be an object")
        field = str(c.get("field", "")).strip()
        op = str(c.get("op", "")).strip()
        if field not in _ALL_FIELDS:
            raise ValidationAppError(f"Unknown or non-whitelisted field: {field!r}")
        if op not in _OPS:
            raise ValidationAppError(f"Unsupported operator: {op!r}")

        entry: dict = {"field": field, "op": op}
        if field in _STRING_FIELDS:
            if op != "==":
                raise ValidationAppError(f"Field {field!r} only supports '=='")
            val = str(c.get("value_str") or c.get("value") or "").strip()
            if field == "origin" and val not in ("derived", "imported"):
                raise ValidationAppError("origin must be 'derived' or 'imported'")
            if field == "robots_band" and val not in sd_svc.ROBOTS_BANDS:
                raise ValidationAppError(
                    "robots_band must be one of: " + ", ".join(sd_svc.ROBOTS_BANDS)
                )
            if field in ("market", "country") and not val:
                raise ValidationAppError(f"Condition on {field!r} needs a value")
            # Cap free-text labels at the column width (market/country VARCHAR(80)).
            entry["value_str"] = val[:80]
        else:
            val = sd_svc._num(c.get("value"))
            if val is None:
                raise ValidationAppError(f"Condition on {field!r} needs a numeric value")
            entry["value"] = val
            if op == "between":
                val2 = sd_svc._num(c.get("value2"))
                if val2 is None:
                    raise ValidationAppError("'between' needs value and value2")
                entry["value2"] = val2
        clean.append(entry)
    return {"match": match, "conditions": clean}


def _definition_to_clauses(definition: dict) -> ColumnElement:
    """Translate a validated definition into ONE combined WHERE clause using the
    same whitelisted columns as the list builder."""
    validated = _validate_definition(definition)  # re-validate at apply time
    parts: list[ColumnElement] = []
    for c in validated["conditions"]:
        field = c["field"]
        op = c["op"]
        if field in _STRING_FIELDS:
            col = _STRING_COLUMNS[field]
            if field in ("market", "country"):
                # Case-insensitive, matching the list filter's behavior.
                parts.append(func.lower(col) == c["value_str"].lower())
            else:
                parts.append(col == c["value_str"])
        else:
            col = sd_svc._NUMERIC_FILTER_COLUMNS[field]
            parts.append(sd_svc._cmp(col, op, c.get("value"), c.get("value2")))
    if validated["match"] == "any":
        return or_(*parts)
    return and_(*parts)


def _to_dict(rule: SourceDomainRule, *, match_count: int | None = None) -> dict:
    return {
        "id": rule.id,
        "workspace_id": rule.workspace_id,
        "project_id": rule.project_id,
        "name": rule.name,
        "description": rule.description,
        "definition": rule.definition or {},
        "is_shared": rule.is_shared,
        "created_by": rule.created_by,
        "updated_by": rule.updated_by,
        "created_at": rule.created_at,
        "updated_at": rule.updated_at,
        "match_count": match_count,
    }


async def _get_rule(db: AsyncSession, ctx: AuthContext, rule_id: uuid.UUID) -> SourceDomainRule:
    rule = await db.get(SourceDomainRule, rule_id)
    if rule is None or rule.workspace_id != ctx.workspace_id:
        raise NotFoundError("Rule not found")
    if rule.project_id is not None:
        ctx.assert_project(rule.project_id)
    return rule


async def list_rules(
    db: AsyncSession, ctx: AuthContext, *, project_id: uuid.UUID | None = None
) -> list[dict]:
    stmt = select(SourceDomainRule).where(SourceDomainRule.workspace_id == ctx.workspace_id)
    if project_id is not None:
        ctx.assert_project(project_id)
        # Project view = that project's rules + workspace-wide rules.
        stmt = stmt.where(
            or_(
                SourceDomainRule.project_id == project_id,
                SourceDomainRule.project_id.is_(None),
            )
        )
    # Project-scoped principals only ever see their allowed projects' rules
    # (plus workspace-wide). Admins (allowed_project_ids is None) see all.
    if ctx.allowed_project_ids is not None:
        allowed = ctx.allowed_project_ids or set()
        stmt = stmt.where(
            or_(
                SourceDomainRule.project_id.is_(None),
                SourceDomainRule.project_id.in_(allowed or {uuid.uuid4()}),
            )
        )
    stmt = stmt.order_by(SourceDomainRule.name.asc())
    return [_to_dict(r) for r in (await db.execute(stmt)).scalars().all()]


async def create_rule(db: AsyncSession, ctx: AuthContext, payload: SourceDomainRuleCreate) -> dict:
    if payload.project_id is not None:
        ctx.assert_project(payload.project_id)
    definition = _validate_definition(payload.definition.model_dump())
    rule = SourceDomainRule(
        workspace_id=ctx.workspace_id,
        project_id=payload.project_id,
        name=payload.name.strip(),
        description=(payload.description or None),
        definition=definition,
        is_shared=payload.is_shared,
        created_by=ctx.user.id,
        updated_by=ctx.user.id,
    )
    db.add(rule)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise ConflictError("A rule with that name already exists in this scope") from exc
    # Load server-generated timestamps within the async context so _to_dict's
    # attribute access does not trigger a sync lazy load (MissingGreenlet).
    await db.refresh(rule)
    return _to_dict(rule)


async def update_rule(
    db: AsyncSession, ctx: AuthContext, rule_id: uuid.UUID, payload: SourceDomainRuleUpdate
) -> dict:
    rule = await _get_rule(db, ctx, rule_id)
    if payload.name is not None:
        rule.name = payload.name.strip()
    if payload.description is not None:
        rule.description = payload.description or None
    if payload.is_shared is not None:
        rule.is_shared = payload.is_shared
    if payload.definition is not None:
        rule.definition = _validate_definition(payload.definition.model_dump())
    rule.updated_by = ctx.user.id
    try:
        await db.flush()
    except IntegrityError as exc:
        raise ConflictError("A rule with that name already exists in this scope") from exc
    # Reload so the onupdate/updated_at server value is populated in-context
    # (avoids a sync lazy load in _to_dict → MissingGreenlet).
    await db.refresh(rule)
    return _to_dict(rule)


async def delete_rule(db: AsyncSession, ctx: AuthContext, rule_id: uuid.UUID) -> None:
    rule = await _get_rule(db, ctx, rule_id)
    await db.delete(rule)
    await db.flush()


async def count_matches(db: AsyncSession, ctx: AuthContext, rule: SourceDomainRule) -> int:
    clause = _definition_to_clauses(rule.definition or {})
    return int(
        (
            await db.execute(
                select(func.count())
                .select_from(SourceDomain)
                .where(SourceDomain.workspace_id == ctx.workspace_id, clause)
            )
        ).scalar_one()
    )


async def apply_rule(
    db: AsyncSession, ctx: AuthContext, rule_id: uuid.UUID, *,
    limit: int = 200, offset: int = 0,
) -> dict:
    """Return the domains matching a rule (paginated) + total match count."""
    rule = await _get_rule(db, ctx, rule_id)
    clause = _definition_to_clauses(rule.definition or {})
    where = [SourceDomain.workspace_id == ctx.workspace_id, clause]
    if rule.project_id is not None:
        keys = await sd_svc._project_used_domain_keys(db, ctx, rule.project_id)
        if not keys:
            return {"items": [], "total": 0, "match_count": 0}
        where.append(SourceDomain.domain_key.in_(keys))

    limit = max(1, min(int(limit), 2000))
    offset = max(0, int(offset))
    total = int(
        (
            await db.execute(select(func.count()).select_from(SourceDomain).where(*where))
        ).scalar_one()
    )
    stmt = (
        select(SourceDomain)
        .where(*where)
        .order_by(SourceDomain.backlink_count.desc(), SourceDomain.domain_key.asc())
        .limit(limit)
        .offset(offset)
    )
    items = [sd_svc._to_dict(sd) for sd in (await db.execute(stmt)).scalars().all()]
    return {"items": items, "total": total, "match_count": total}


async def export_rule_matches(
    db: AsyncSession, ctx: AuthContext, rule_id: uuid.UUID
) -> tuple[list[str], list[list]]:
    """(headers, rows) for the domains a rule matches — reuses the list export
    column set."""
    rule = await _get_rule(db, ctx, rule_id)
    clause = _definition_to_clauses(rule.definition or {})
    where = [SourceDomain.workspace_id == ctx.workspace_id, clause]
    if rule.project_id is not None:
        keys = await sd_svc._project_used_domain_keys(db, ctx, rule.project_id)
        if not keys:
            return [label for label, _ in sd_svc._EXPORT_COLUMNS], []
        where.append(SourceDomain.domain_key.in_(keys))
    stmt = (
        select(SourceDomain)
        .where(*where)
        .order_by(SourceDomain.backlink_count.desc(), SourceDomain.domain_key.asc())
        .limit(2000)
    )
    domains = [sd_svc._to_dict(sd) for sd in (await db.execute(stmt)).scalars().all()]
    headers = [label for label, _ in sd_svc._EXPORT_COLUMNS]
    rows = [[d.get(key) for _, key in sd_svc._EXPORT_COLUMNS] for d in domains]
    return headers, rows
