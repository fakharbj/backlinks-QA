"""Source main-domain analytics endpoints (Phase 8, features 11/12; 0033).

List + detail read the stored aggregates (fast); recompute refreshes them. The
0033 increment adds rich whitelisted filtering, a set-based stats aggregate,
CSV/XLSX exports, a saved-filters store, and a whitelisted Rules engine.

Permissions (all existing rbac perms — no new ones added):
  * reads (list/stats/detail/rules-list/apply/saved-filters GET) — any authed user
  * exports — ``EXPORT_REPORTS`` (the report-download perm; viewers have it)
  * recompute / fetch-metrics — ``RUN_CRAWLS`` (unchanged)
  * rule + saved-filter mutations — ``MANAGE_WORKSPACE`` (same perm dynamic
    scoring uses in scoring.py — these are workspace-wide qualification config)
  * domain import staging — ``IMPORT_BACKLINKS`` (unchanged)
"""

from __future__ import annotations

import uuid
from datetime import date as _dt_date

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile, status
from pydantic import BaseModel, Field
from starlette.responses import StreamingResponse

from app.core.deps import AuthContext, AuthCtx, DbSession, ReadSession, require, require_role
from app.core.errors import ValidationAppError
from app.core.rbac import Permission, Role
from sqlalchemy import select
from app.models.enums import AuditAction
from app.schemas.source_domain import (
    SavedFilterOut,
    SavedFilterUpsert,
    SourceDomainDetailOut,
    SourceDomainListOut,
    SourceDomainOut,
    SourceDomainRuleCreate,
    SourceDomainRuleOut,
    SourceDomainRuleUpdate,
    SourceDomainStatsOut,
)
from app.services import audit_service, batch_review_service
from app.services import source_domain_rule_service as rule_svc
from app.services import source_domain_service as svc

router = APIRouter(prefix="/source-domains", tags=["source-domains"])

# The rich filter query params: the service's _RANGE_PARAMS keys plus the
# string filters (robots_band/market/country — comma list = multi-select).
_FILTER_PARAM_NAMES = [*svc._RANGE_PARAMS, *svc._STRING_FILTER_COLUMNS]


def _collect_filters(request: Request) -> dict:
    """Pull the whitelisted filter params off the query string into a plain dict.
    Only recognized keys are kept; everything else is ignored (never trusted)."""
    qp = request.query_params
    return {name: qp[name] for name in _FILTER_PARAM_NAMES if qp.get(name) not in (None, "")}


# ═══════════════════════════════════════════════════════════════════════════════
# List + stats + export (literal paths declared before /{domain_id})
# ═══════════════════════════════════════════════════════════════════════════════
@router.get("", response_model=SourceDomainListOut)
async def list_source_domains(
    request: Request, ctx: AuthCtx, db: ReadSession,
    sort: str = "backlinks", order: str = "desc", search: str | None = None,
    limit: int = 200, offset: int = 0, origin: str | None = None,
    project_id: uuid.UUID | None = None, opportunity: bool = False,
) -> SourceDomainListOut:
    result = await svc.list_domains(
        db, ctx, sort=sort, order=order, search=search, limit=limit, offset=offset,
        origin=origin, project_id=project_id, filters=_collect_filters(request),
        opportunity=opportunity,
    )
    return SourceDomainListOut(
        items=[SourceDomainOut(**r) for r in result["items"]], total=result["total"]
    )


@router.get("/stats", response_model=SourceDomainStatsOut)
async def source_domain_stats(
    request: Request, ctx: AuthCtx, db: ReadSession,
    search: str | None = None, origin: str | None = None,
    project_id: uuid.UUID | None = None,
) -> SourceDomainStatsOut:
    stats = await svc.source_domain_stats(
        db, ctx, search=search, origin=origin, project_id=project_id,
        filters=_collect_filters(request),
    )
    return SourceDomainStatsOut(**stats)


def _export_response(fmt: str, headers: list[str], rows: list[list], base: str) -> StreamingResponse:
    fmt = (fmt or "csv").lower()
    if fmt == "xlsx":
        data = svc.build_xlsx(headers, rows, title=base)
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ext = "xlsx"
    elif fmt == "csv":
        data = svc.build_csv(headers, rows)
        media = "text/csv; charset=utf-8"
        ext = "csv"
    else:
        raise ValidationAppError("format must be csv or xlsx")
    # ASCII-safe Content-Disposition (HTTP headers are latin-1 only).
    safe = base.encode("ascii", "ignore").decode("ascii").strip("_-. ") or "source-domains"
    return StreamingResponse(
        iter([data]), media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{safe}.{ext}"'},
    )


@router.get("/export")
async def export_source_domains(
    request: Request, db: ReadSession,
    ctx: AuthContext = Depends(require(Permission.EXPORT_REPORTS)),
    format: str = "csv", sort: str = "backlinks", order: str = "desc",
    search: str | None = None, origin: str | None = None,
    project_id: uuid.UUID | None = None,
) -> StreamingResponse:
    headers, rows = await svc.export_rows(
        db, ctx, search=search, origin=origin, project_id=project_id,
        filters=_collect_filters(request), sort=sort, order=order,
    )
    return _export_response(format, headers, rows, "source-domains")


# ═══════════════════════════════════════════════════════════════════════════════
# Saved filters (per-workspace Setting)
# ═══════════════════════════════════════════════════════════════════════════════
@router.get("/saved-filters", response_model=list[SavedFilterOut])
async def list_saved_filters(ctx: AuthCtx, db: ReadSession) -> list[SavedFilterOut]:
    return [SavedFilterOut(**f) for f in await svc.list_saved_filters(db, ctx)]


@router.put("/saved-filters", response_model=list[SavedFilterOut])
async def upsert_saved_filter(
    payload: SavedFilterUpsert, db: DbSession,
    ctx: AuthContext = Depends(require(Permission.MANAGE_WORKSPACE)),
) -> list[SavedFilterOut]:
    saved = await svc.upsert_saved_filter(db, ctx, payload.name, payload.params)
    await db.commit()
    return [SavedFilterOut(**f) for f in saved]


@router.delete("/saved-filters", response_model=list[SavedFilterOut])
async def delete_saved_filter(
    name: str, db: DbSession,
    ctx: AuthContext = Depends(require(Permission.MANAGE_WORKSPACE)),
) -> list[SavedFilterOut]:
    saved = await svc.delete_saved_filter(db, ctx, name)
    await db.commit()
    return [SavedFilterOut(**f) for f in saved]


# ═══════════════════════════════════════════════════════════════════════════════
# Rules engine
# ═══════════════════════════════════════════════════════════════════════════════
@router.get("/rules", response_model=list[SourceDomainRuleOut])
async def list_rules(
    ctx: AuthCtx, db: ReadSession, project_id: uuid.UUID | None = None
) -> list[SourceDomainRuleOut]:
    return [SourceDomainRuleOut(**r) for r in await rule_svc.list_rules(db, ctx, project_id=project_id)]


@router.post("/rules", response_model=SourceDomainRuleOut, status_code=status.HTTP_201_CREATED)
async def create_rule(
    payload: SourceDomainRuleCreate, db: DbSession,
    ctx: AuthContext = Depends(require(Permission.MANAGE_WORKSPACE)),
) -> SourceDomainRuleOut:
    rule = await rule_svc.create_rule(db, ctx, payload)
    await audit_service.record(
        db, action=AuditAction.CREATE, actor_user_id=ctx.user.id, workspace_id=ctx.workspace_id,
        entity_type="source_domain_rule", entity_id=rule["id"],
        summary=f"Created source-domain rule '{rule['name']}'",
    )
    await db.commit()
    return SourceDomainRuleOut(**rule)


@router.patch("/rules/{rule_id}", response_model=SourceDomainRuleOut)
async def update_rule(
    rule_id: uuid.UUID, payload: SourceDomainRuleUpdate, db: DbSession,
    ctx: AuthContext = Depends(require(Permission.MANAGE_WORKSPACE)),
) -> SourceDomainRuleOut:
    rule = await rule_svc.update_rule(db, ctx, rule_id, payload)
    await audit_service.record(
        db, action=AuditAction.UPDATE, actor_user_id=ctx.user.id, workspace_id=ctx.workspace_id,
        entity_type="source_domain_rule", entity_id=rule_id,
        summary=f"Updated source-domain rule '{rule['name']}'",
    )
    await db.commit()
    return SourceDomainRuleOut(**rule)


@router.delete("/rules/{rule_id}")
async def delete_rule(
    rule_id: uuid.UUID, db: DbSession,
    ctx: AuthContext = Depends(require(Permission.MANAGE_WORKSPACE)),
) -> dict:
    await rule_svc.delete_rule(db, ctx, rule_id)
    await audit_service.record(
        db, action=AuditAction.DELETE, actor_user_id=ctx.user.id, workspace_id=ctx.workspace_id,
        entity_type="source_domain_rule", entity_id=rule_id, summary="Deleted source-domain rule",
    )
    await db.commit()
    return {"message": "Rule deleted"}


@router.get("/rules/{rule_id}/apply")
async def apply_rule(
    rule_id: uuid.UUID, ctx: AuthCtx, db: ReadSession,
    limit: int = 200, offset: int = 0,
) -> dict:
    result = await rule_svc.apply_rule(db, ctx, rule_id, limit=limit, offset=offset)
    return {
        "items": [SourceDomainOut(**r).model_dump() for r in result["items"]],
        "total": result["total"],
        "match_count": result["match_count"],
    }


@router.get("/rules/{rule_id}/export")
async def export_rule_matches(
    rule_id: uuid.UUID, db: ReadSession,
    ctx: AuthContext = Depends(require(Permission.EXPORT_REPORTS)),
    format: str = "csv",
) -> StreamingResponse:
    headers, rows = await rule_svc.export_rule_matches(db, ctx, rule_id)
    return _export_response(format, headers, rows, "rule-matches")


# ═══════════════════════════════════════════════════════════════════════════════
# Import staging + project view + recompute + fetch-metrics (existing)
# ═══════════════════════════════════════════════════════════════════════════════
class DomainImportRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2_000_000)
    label: str | None = Field(default=None, max_length=200)


@router.post("/import", status_code=status.HTTP_202_ACCEPTED)
async def import_source_domains(
    payload: DomainImportRequest, db: DbSession,
    ctx: AuthContext = Depends(require(Permission.IMPORT_BACKLINKS)),
) -> dict:
    """Stage a pasted list of domains/URLs into a review batch (0029). Each
    domain is reviewable (check DA/PA/Spam/AS/age) and joins the Source Domains
    catalog only when approved in the Batches desk."""
    batch = await batch_review_service.stage_domain_import(
        db, ctx, text_block=payload.text, label=payload.label
    )
    await audit_service.record(
        db, action=AuditAction.IMPORT, actor_user_id=ctx.user.id, workspace_id=ctx.workspace_id,
        entity_type="batch", entity_id=batch.id,
        summary=f"Staged domain import for review (#B-{batch.seq})",
    )
    await db.commit()
    c = batch.counters or {}
    return {
        "batch_id": str(batch.id),
        "seq": batch.seq,
        "total": int((batch.totals or {}).get("total", 0)),
        "new": int(c.get("new", 0)),
        "existing": int(c.get("existing", 0)),
        "duplicate": int(c.get("duplicate", 0)),
        "message": f"Review batch #B-{batch.seq} created — approve domains to add them to the catalog",
    }


@router.post("/import-file", status_code=status.HTTP_202_ACCEPTED)
async def import_source_domains_file(
    db: DbSession,
    file: UploadFile = File(...),
    label: str | None = Form(default=None),
    ctx: AuthContext = Depends(require(Permission.IMPORT_BACKLINKS)),
) -> dict:
    """Stage a CSV/XLSX of market domains into a review batch — the file-upload
    twin of POST /import. The domain column is auto-detected by header
    (domain/url/website/site/source) with the first column as the fallback; every
    other pipeline step (in-file dedup, catalog-presence check, metric checks,
    approve → Opportunity/catalog) is identical to the paste path."""
    from app.services import import_parse

    raw = await file.read()
    name = (file.filename or "").lower()
    if name.endswith((".xlsx", ".xls")):
        headers, rows = import_parse.parse_xlsx(raw)
    else:
        headers, rows = import_parse.parse_csv(raw)
    if not rows:
        raise ValidationAppError("The file has no data rows.")
    wanted = ("domain", "url", "website", "site", "source")
    col = next(
        (h for h in headers if any(w in (h or "").strip().lower() for w in wanted)),
        headers[0] if headers else None,
    )
    if col is None:
        raise ValidationAppError("Couldn't find a domain column in the file.")
    text_block = "\n".join(str(r.get(col) or "").strip() for r in rows if str(r.get(col) or "").strip())
    if not text_block:
        raise ValidationAppError(f'The "{col}" column is empty.')
    batch = await batch_review_service.stage_domain_import(
        db, ctx, text_block=text_block, label=label or (file.filename or "Domain file"),
    )
    await audit_service.record(
        db, action=AuditAction.IMPORT, actor_user_id=ctx.user.id, workspace_id=ctx.workspace_id,
        entity_type="batch", entity_id=batch.id,
        summary=f"Staged domain import from file {file.filename} (#B-{batch.seq})",
    )
    await db.commit()
    c = batch.counters or {}
    return {
        "batch_id": str(batch.id),
        "seq": batch.seq,
        "column_used": col,
        "total": int((batch.totals or {}).get("total", 0)),
        "new": int(c.get("new", 0)),
        "existing": int(c.get("existing", 0)),
        "duplicate": int(c.get("duplicate", 0)),
        "message": f"Review batch #B-{batch.seq} created from {file.filename}",
    }


@router.get("/project-view")
async def project_view(
    project_id: uuid.UUID, ctx: AuthCtx, db: ReadSession, limit: int = 500, offset: int = 0
) -> dict:
    """Domains used by this project vs domains known globally but not used here.
    Counts are true totals; ``limit``/``offset`` page the rows for load-more."""
    return await svc.project_view(
        db, ctx, project_id, limit=min(max(limit, 1), 1000), offset=max(offset, 0)
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Recommendations (Phase 10 P4) — literal paths, declared before /{domain_id}
# ═══════════════════════════════════════════════════════════════════════════════
class RecommendActionIn(BaseModel):
    domain_key: str = Field(min_length=1, max_length=255)
    status: str = Field(pattern="^(viewed|accepted|skipped)$")
    project_id: uuid.UUID | None = None
    assignment_id: uuid.UUID | None = None
    recommended_to: str | None = Field(default=None, max_length=200)
    note: str | None = Field(default=None, max_length=300)
    # Skip workflow: WHY it was skipped (required by the UI for skips) + the
    # link type the reason refers to when it's a link-type problem.
    reason: str | None = Field(default=None, max_length=300)
    link_type_name: str | None = Field(default=None, max_length=80)


class RecommendManualIn(BaseModel):
    domain_key: str = Field(min_length=1, max_length=255)
    user_label: str = Field(min_length=1, max_length=200)
    project_id: uuid.UUID | None = None
    assignment_id: uuid.UUID | None = None
    link_type_name: str | None = Field(default=None, max_length=80)
    priority: str | None = Field(default=None, pattern="^(high|medium|low)$")
    due_date: _dt_date | None = None
    reason: str | None = Field(default=None, max_length=300)
    note: str | None = Field(default=None, max_length=300)


@router.get("/recommend")
async def recommend_browse(
    ctx: AuthCtx, db: ReadSession, project_id: uuid.UUID,
    link_types: str | None = None, limit: int = 20,
) -> dict:
    """The recommendation engine without a task: best unused, unblocked domains
    for a project, optionally biased to link types (comma list)."""
    from app.services import recommendation_service

    lts = [p.strip() for p in (link_types or "").split(",") if p.strip()]
    return await recommendation_service.suggest_for_scope(
        db, ctx, project_id=project_id, link_types=lts, limit=min(max(limit, 1), 50)
    )


@router.get("/recommendations")
async def list_domain_recommendations(
    ctx: AuthCtx, db: ReadSession,
    user_label: str | None = None, project_id: uuid.UUID | None = None,
    status_filter: str | None = None, source: str | None = None,
    limit: int = 100, offset: int = 0,
) -> list[dict]:
    """Recommendation rows (auto + manual) with their view/accept/skip state.
    Viewer-scoped to their own labels."""
    from app.services import recommendation_service

    return await recommendation_service.list_recommendations(
        db, ctx, user_label=user_label, project_id=project_id,
        status=status_filter, source=source, limit=limit, offset=offset,
    )


@router.get("/recommendations/export")
async def export_domain_recommendations(
    db: ReadSession, ctx: AuthContext = Depends(require(Permission.EXPORT_REPORTS)),
    user_label: str | None = None, project_id: uuid.UUID | None = None,
    status_filter: str | None = None, source: str | None = None,
) -> StreamingResponse:
    from app.services import recommendation_service

    rows = await recommendation_service.list_recommendations(
        db, ctx, user_label=user_label, project_id=project_id,
        status=status_filter, source=source, limit=500,
    )
    headers = ["Domain", "Person", "Project", "Link type", "Source", "Status",
               "Priority", "Due", "Reason", "Note", "Updated"]
    data = [
        [r["domain_key"], r["recommended_to"], r["project_id"], r["link_type_name"],
         r["source"], r["status"], r["priority"], r["due_date"], r["reason"],
         r["note"], r["updated_at"]]
        for r in rows
    ]
    return _export_response("csv", headers, data, "domain-recommendations")


@router.post("/recommendations/action")
async def act_on_recommendation(
    payload: RecommendActionIn, ctx: AuthCtx, db: DbSession
) -> dict:
    """The person acted on a suggestion: viewed / accepted / skipped."""
    from app.services import recommendation_service

    row = await recommendation_service.record_action(
        db, ctx, domain_key=payload.domain_key, status=payload.status,
        project_id=payload.project_id, assignment_id=payload.assignment_id,
        recommended_to=payload.recommended_to, note=payload.note,
        reason=payload.reason, link_type_name=payload.link_type_name,
    )
    await db.commit()
    return {"ok": True, "status": row.status}


# ── Skip reasons (editable in Settings; used by the task-skip workflow) ───────
_DEFAULT_SKIP_REASONS = [
    "Website is unavailable",
    "Website is temporarily down",
    "Incorrect source domain",
    "No suitable page found",
    "Link type is not available",
    "Duplicate task",
    "Other",
]


@router.get("/skip-reasons")
async def get_skip_reasons(ctx: AuthCtx, db: ReadSession) -> dict:
    """The predefined skip reasons every user picks from (admin-editable)."""
    from app.models.settings import Setting

    row = (
        await db.execute(
            select(Setting).where(
                Setting.workspace_id == ctx.workspace_id, Setting.key == "skip_reasons"
            )
        )
    ).scalar_one_or_none()
    reasons = row.value if row is not None and isinstance(row.value, list) else _DEFAULT_SKIP_REASONS
    return {"reasons": reasons, "defaults": _DEFAULT_SKIP_REASONS}


class SkipReasonsIn(BaseModel):
    reasons: list[str] = Field(min_length=1, max_length=30)


@router.put("/skip-reasons")
async def put_skip_reasons(
    payload: SkipReasonsIn, db: DbSession,
    ctx: AuthContext = Depends(require_role(Role.ADMIN)),
) -> dict:
    """Replace the predefined skip-reason list (admin, audited). Keep an
    "Other" entry — the UI requires a typed explanation for it."""
    from app.models.settings import Setting

    reasons = [r.strip()[:120] for r in payload.reasons if r.strip()]
    if not any(r.lower() == "other" for r in reasons):
        reasons.append("Other")
    row = (
        await db.execute(
            select(Setting).where(
                Setting.workspace_id == ctx.workspace_id, Setting.key == "skip_reasons"
            )
        )
    ).scalar_one_or_none()
    if row is None:
        db.add(Setting(workspace_id=ctx.workspace_id, key="skip_reasons", value=reasons))
    else:
        row.value = reasons
    await audit_service.record(
        db, action=AuditAction.UPDATE, actor_user_id=ctx.user.id, workspace_id=ctx.workspace_id,
        entity_type="skip_reasons", entity_id=ctx.workspace_id,
        summary="Task-skip reasons updated", after={"reasons": reasons},
    )
    await db.commit()
    return {"reasons": reasons}


@router.post("/recommendations", status_code=status.HTTP_201_CREATED)
async def create_manual_recommendation(
    payload: RecommendManualIn, db: DbSession,
    ctx: AuthContext = Depends(require(Permission.ASSIGN_MEMBERS)),
) -> dict:
    """Admin hand-picks a domain for a person (labeled MANUAL, audited)."""
    from app.services import recommendation_service

    row = await recommendation_service.recommend_manual(
        db, ctx, domain_key=payload.domain_key, user_label=payload.user_label,
        project_id=payload.project_id, assignment_id=payload.assignment_id,
        link_type_name=payload.link_type_name, priority=payload.priority,
        due_date=payload.due_date, reason=payload.reason, note=payload.note,
    )
    await audit_service.record(
        db, action=AuditAction.CREATE, actor_user_id=ctx.user.id, workspace_id=ctx.workspace_id,
        entity_type="domain_recommendation", entity_id=row.id,
        summary=f"Recommended {payload.domain_key} to {payload.user_label}",
    )
    await db.commit()
    return {"ok": True, "id": str(row.id)}


@router.get("/{domain_id}", response_model=SourceDomainDetailOut)
async def source_domain_detail(
    domain_id: uuid.UUID, ctx: AuthCtx, db: ReadSession
) -> SourceDomainDetailOut:
    return SourceDomainDetailOut(**await svc.detail(db, ctx, domain_id))


@router.post("/recompute", response_model=SourceDomainListOut)
async def recompute_source_domains(
    db: DbSession, ctx: AuthContext = Depends(require(Permission.RUN_CRAWLS))
) -> SourceDomainListOut:
    await svc.recompute(db, ctx.workspace_id)
    await db.commit()
    result = await svc.list_domains(db, ctx)
    return SourceDomainListOut(
        items=[SourceDomainOut(**r) for r in result["items"]], total=result["total"]
    )


@router.post("/fetch-metrics", response_model=SourceDomainListOut)
async def fetch_source_domain_metrics(
    db: DbSession, force: bool = False, providers: str | None = None,
    ctx: AuthContext = Depends(require(Permission.RUN_CRAWLS)),
) -> SourceDomainListOut:
    """Fetch metrics for stale domains (batch-capped per call): DA/PA via Moz,
    AS via Semrush. ``providers`` is a comma list (``moz,semrush``) scoping the
    fetch; omit for all providers."""
    wanted = {p.strip() for p in (providers or "").split(",") if p.strip() in ("moz", "semrush")}
    await svc.fetch_metrics(db, ctx, force=force, providers=wanted or None)
    await db.commit()
    result = await svc.list_domains(db, ctx)
    return SourceDomainListOut(
        items=[SourceDomainOut(**r) for r in result["items"]], total=result["total"]
    )
