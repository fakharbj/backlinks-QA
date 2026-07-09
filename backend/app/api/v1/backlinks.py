"""Backlink grid, detail, mutation, override, and recheck endpoints."""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query, status
from starlette.responses import StreamingResponse

from app.core.deps import AuthContext, AuthCtx, DbSession, ReadSession, require
from app.core.rbac import Permission
from app.models.enums import AuditAction, Indexability, JobType, OverallStatus, RelType
from app.schemas.backlink import (
    AssignmentEventOut,
    BacklinkBulkEdit,
    BacklinkCreate,
    BacklinkDetail,
    BacklinkFilters,
    BacklinkOverride,
    BacklinkRow,
    BacklinkUpdate,
    BulkEditResponse,
    CrawlResultOut,
    FillMissingPlacementRequest,
    HistoryEventOut,
    IssueOut,
    RecheckRequest,
    RecheckResponse,
)
from app.schemas.common import KeysetPage, Message
from app.services import audit_service, backlink_service, crawl_service

router = APIRouter(prefix="/backlinks", tags=["backlinks"])


@router.get("", response_model=KeysetPage[BacklinkRow])
async def list_backlinks(
    ctx: AuthCtx,
    db: ReadSession,
    project_id: uuid.UUID | None = None,
    # Single value or comma-separated multi-select ("FAIL,WARNING"); "(blanks)" = NULL.
    status_filter: str | None = Query(default=None, alias="status"),
    issue_label: str | None = None,
    score_min: int | None = Query(default=None, ge=0, le=100),
    score_max: int | None = Query(default=None, ge=0, le=100),
    rel: str | None = None,
    indexability: Indexability | None = None,
    robots_status: str | None = None,
    canonical_status: str | None = None,
    vendor_id: uuid.UUID | None = None,
    campaign_id: uuid.UUID | None = None,
    tag: str | None = None,
    source_domain: str | None = None,
    assigned_user_id: uuid.UUID | None = None,
    assigned_user_label: str | None = None,
    link_type: str | None = None,
    duplicate_status: str | None = None,
    index_status: str | None = None,
    # KPI drill-down filters (open Backlinks from an analytics/dashboard box).
    http_status: str | None = None,
    broken: bool | None = None,
    http_class: str | None = None,
    link_missing: bool | None = None,
    spam_min: int | None = Query(default=None, ge=0, le=100),
    da_min: int | None = Query(default=None, ge=0, le=100),
    pa_min: int | None = Query(default=None, ge=0, le=100),
    as_min: int | None = Query(default=None, ge=0, le=100),
    orphaned: bool | None = None,
    no_placement: bool | None = None,
    no_user: bool | None = None,
    search: str | None = None,
    target: str | None = None,
    # ── Date-range filters (one pair per date type; inclusive end, see service) ──
    placement_from: date | None = None,
    placement_to: date | None = None,
    discovered_from: date | None = None,
    discovered_to: date | None = None,
    qa_from: date | None = None,
    qa_to: date | None = None,
    completed_from: date | None = None,
    completed_to: date | None = None,
    imported_from: date | None = None,
    imported_to: date | None = None,
    sheet_from: date | None = None,
    sheet_to: date | None = None,
    assigned_from: date | None = None,
    assigned_to: date | None = None,
    updated_from: date | None = None,
    updated_to: date | None = None,
    sort: str = Query(
        default="score",
        pattern=(
            "^(score|last_checked_at|created_at|source_domain|link_type|http_status"
            "|placement_date|discovered_at|qa_completed_at|assigned_at|updated_at)$"
        ),
    ),
    direction: str = Query(default="desc", pattern="^(asc|desc)$"),
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = None,
    with_total: bool = False,
) -> KeysetPage[BacklinkRow]:
    filters = BacklinkFilters(
        project_id=project_id, status=status_filter, issue_label=issue_label,
        score_min=score_min, score_max=score_max, rel=rel, indexability=indexability,
        robots_status=robots_status, canonical_status=canonical_status, vendor_id=vendor_id,
        campaign_id=campaign_id, tag=tag, source_domain=source_domain,
        assigned_user_id=assigned_user_id, assigned_user_label=assigned_user_label,
        link_type=link_type, duplicate_status=duplicate_status, index_status=index_status,
        http_status=http_status, broken=broken, http_class=http_class,
        link_missing=link_missing, spam_min=spam_min,
        da_min=da_min, pa_min=pa_min, as_min=as_min, orphaned=orphaned,
        no_placement=no_placement, no_user=no_user,
        search=search, target=target,
        placement_from=placement_from, placement_to=placement_to,
        discovered_from=discovered_from, discovered_to=discovered_to,
        qa_from=qa_from, qa_to=qa_to,
        completed_from=completed_from, completed_to=completed_to,
        imported_from=imported_from, imported_to=imported_to,
        sheet_from=sheet_from, sheet_to=sheet_to,
        assigned_from=assigned_from, assigned_to=assigned_to,
        updated_from=updated_from, updated_to=updated_to,
    )
    rows, next_cursor, has_more = await backlink_service.list_backlinks(
        db, ctx, filters, sort=sort, direction=direction, limit=limit, cursor=cursor
    )
    total = await backlink_service.count_backlinks(db, ctx, filters) if with_total else None
    target_counts = await backlink_service.targets_per_source(db, rows)
    domain_metrics = await backlink_service.domain_metrics_per_row(db, rows)
    items = []
    for r in rows:
        row = BacklinkRow.model_validate(r)
        row.targets_on_source = target_counts.get(r.id, 1)
        row.domain_da, row.domain_pa, row.domain_as, row.domain_spam = domain_metrics.get(
            r.id, (None, None, None, None)
        )
        items.append(row)
    return KeysetPage[BacklinkRow](
        items=items,
        next_cursor=next_cursor,
        has_more=has_more,
        total=total,
    )


@router.get("/export")
async def export_backlinks(
    ctx: AuthCtx,
    db: ReadSession,
    project_id: uuid.UUID | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    issue_label: str | None = None,
    score_min: int | None = Query(default=None, ge=0, le=100),
    score_max: int | None = Query(default=None, ge=0, le=100),
    rel: str | None = None,
    indexability: Indexability | None = None,
    robots_status: str | None = None,
    canonical_status: str | None = None,
    vendor_id: uuid.UUID | None = None,
    campaign_id: uuid.UUID | None = None,
    tag: str | None = None,
    source_domain: str | None = None,
    assigned_user_id: uuid.UUID | None = None,
    assigned_user_label: str | None = None,
    link_type: str | None = None,
    duplicate_status: str | None = None,
    index_status: str | None = None,
    http_status: str | None = None,
    broken: bool | None = None,
    http_class: str | None = None,
    link_missing: bool | None = None,
    spam_min: int | None = Query(default=None, ge=0, le=100),
    da_min: int | None = Query(default=None, ge=0, le=100),
    pa_min: int | None = Query(default=None, ge=0, le=100),
    as_min: int | None = Query(default=None, ge=0, le=100),
    orphaned: bool | None = None,
    no_placement: bool | None = None,
    no_user: bool | None = None,
    search: str | None = None,
    target: str | None = None,
    placement_from: date | None = None, placement_to: date | None = None,
    discovered_from: date | None = None, discovered_to: date | None = None,
    qa_from: date | None = None, qa_to: date | None = None,
    completed_from: date | None = None, completed_to: date | None = None,
    imported_from: date | None = None, imported_to: date | None = None,
    sheet_from: date | None = None, sheet_to: date | None = None,
    assigned_from: date | None = None, assigned_to: date | None = None,
    updated_from: date | None = None, updated_to: date | None = None,
    sort: str = Query(default="score"),
    direction: str = Query(default="desc", pattern="^(asc|desc)$"),
    fmt: str = Query(default="csv", alias="format", pattern="^(csv|xlsx)$"),
) -> StreamingResponse:
    """Export the FULL filtered backlink set (not the 200-row page) as CSV/XLSX —
    same filters as the grid. Available to anyone who can view the grid."""
    from app.services import source_domain_service

    filters = BacklinkFilters(
        project_id=project_id, status=status_filter, issue_label=issue_label,
        score_min=score_min, score_max=score_max, rel=rel, indexability=indexability,
        robots_status=robots_status, canonical_status=canonical_status, vendor_id=vendor_id,
        campaign_id=campaign_id, tag=tag, source_domain=source_domain,
        assigned_user_id=assigned_user_id, assigned_user_label=assigned_user_label,
        link_type=link_type, duplicate_status=duplicate_status, index_status=index_status,
        http_status=http_status, broken=broken, http_class=http_class,
        link_missing=link_missing, spam_min=spam_min,
        da_min=da_min, pa_min=pa_min, as_min=as_min, orphaned=orphaned,
        no_placement=no_placement, no_user=no_user,
        search=search, target=target,
        placement_from=placement_from, placement_to=placement_to,
        discovered_from=discovered_from, discovered_to=discovered_to,
        qa_from=qa_from, qa_to=qa_to,
        completed_from=completed_from, completed_to=completed_to,
        imported_from=imported_from, imported_to=imported_to,
        sheet_from=sheet_from, sheet_to=sheet_to,
        assigned_from=assigned_from, assigned_to=assigned_to,
        updated_from=updated_from, updated_to=updated_to,
    )
    headers, rows, truncated = await backlink_service.export_rows(
        db, ctx, filters, sort=sort, direction=direction
    )
    if fmt == "xlsx":
        data = source_domain_service.build_xlsx(headers, rows, title="Backlinks")
        media, ext = (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx",
        )
    else:
        data = source_domain_service.build_csv(headers, rows)
        media, ext = "text/csv; charset=utf-8", "csv"
    resp = StreamingResponse(
        iter([data]), media_type=media,
        headers={"Content-Disposition": f'attachment; filename="backlinks.{ext}"'},
    )
    if truncated:
        resp.headers["X-Export-Truncated"] = str(backlink_service.EXPORT_ROW_CAP)
    return resp


@router.post("", response_model=BacklinkRow, status_code=status.HTTP_201_CREATED)
async def create_backlink(
    payload: BacklinkCreate, db: DbSession,
    ctx: AuthContext = Depends(require(Permission.EDIT_BACKLINKS)),
) -> BacklinkRow:
    bl = await backlink_service.create_backlink(db, ctx, payload)
    await db.commit()
    # Reload so server-default/onupdate columns (created_at/updated_at, …) are
    # populated before serialization — avoids a lazy load during model_validate.
    await db.refresh(bl)
    return BacklinkRow.model_validate(bl)


@router.get("/{backlink_id}", response_model=BacklinkDetail)
async def get_backlink(backlink_id: uuid.UUID, ctx: AuthCtx, db: ReadSession) -> BacklinkDetail:
    bl, issues, latest, history = await backlink_service.get_detail(db, ctx, backlink_id)
    detail = BacklinkDetail.model_validate(bl)
    detail.domain_da, detail.domain_pa, detail.domain_as, detail.domain_spam = (
        await backlink_service.domain_metrics_per_row(db, [bl])
    ).get(bl.id, (None, None, None, None))
    detail.issues = [
        IssueOut(code=i.code, label=i.label, category=i.category.value, severity=i.severity.value,
                 message=i.message, recommendation=i.recommendation, evidence=i.evidence)
        for i in issues
    ]
    if latest is not None:
        detail.recommendations = latest.recommendations or []
        detail.score_breakdown = latest.score_breakdown or []
        detail.latest_result = CrawlResultOut(
            id=latest.id, crawled_at=latest.crawled_at, crawl_mode=latest.crawl_mode.value,
            http_status=latest.http_status, final_url=latest.final_url,
            content_type=latest.content_type, redirect_chain=latest.redirect_chain or [],
            meta_robots=latest.meta_robots, x_robots_tag=latest.x_robots_tag,
            canonical_url=latest.canonical_url, anchor_text=latest.anchor_text,
            rel_values=latest.rel_values or [], status=latest.status.value, score=latest.score,
            is_followable=latest.is_followable,
            is_indexable=latest.is_indexable.value if latest.is_indexable else None,
            score_breakdown=latest.score_breakdown or [], word_count=latest.word_count,
            outbound_link_count=latest.outbound_link_count,
            published_date=(latest.page_signals or {}).get("published_date"),
            modified_date=(latest.page_signals or {}).get("modified_date"),
            date_source=(latest.page_signals or {}).get("date_source"),
            raw_html_key=latest.raw_html_key, rendered_html_key=latest.rendered_html_key,
            matched_href=latest.matched_href,
            scoring_rule_version_id=latest.scoring_rule_version_id,
        )
    detail.history = [
        HistoryEventOut(event_type=h.event_type.value,
                        severity=h.severity.value if h.severity else None, field=h.field,
                        old_value=h.old_value, new_value=h.new_value, score_delta=h.score_delta,
                        created_at=h.created_at)
        for h in history
    ]
    return detail


@router.get("/{backlink_id}/duplicates", response_model=list[BacklinkRow])
async def backlink_duplicates(
    backlink_id: uuid.UUID, ctx: AuthCtx, db: ReadSession
) -> list[BacklinkRow]:
    rows = await backlink_service.list_duplicate_occurrences(db, ctx, backlink_id)
    return [BacklinkRow.model_validate(r) for r in rows]


@router.get("/{backlink_id}/assignment-history", response_model=list[AssignmentEventOut])
async def backlink_assignment_history(
    backlink_id: uuid.UUID, ctx: AuthCtx, db: ReadSession
) -> list[AssignmentEventOut]:
    events = await backlink_service.list_assignment_history(db, ctx, backlink_id)
    return [
        AssignmentEventOut(
            old_user_label=e.old_user_label, new_user_label=e.new_user_label,
            source=e.source, changed_at=e.changed_at,
        )
        for e in events
    ]


@router.patch("/{backlink_id}", response_model=BacklinkRow)
async def update_backlink(
    backlink_id: uuid.UUID, payload: BacklinkUpdate, db: DbSession,
    ctx: AuthContext = Depends(require(Permission.EDIT_BACKLINKS)),
) -> BacklinkRow:
    bl = await backlink_service.update_backlink(db, ctx, backlink_id, payload)
    await audit_service.record(
        db, action=AuditAction.UPDATE, actor_user_id=ctx.user.id, workspace_id=ctx.workspace_id,
        entity_type="backlink", entity_id=backlink_id, summary="Edited backlink",
    )
    await db.commit()
    await db.refresh(bl)  # reload updated_at (onupdate) + any expired cols
    return BacklinkRow.model_validate(bl)


@router.post("/{backlink_id}/override", response_model=BacklinkRow)
async def override_backlink(
    backlink_id: uuid.UUID, payload: BacklinkOverride, db: DbSession,
    ctx: AuthContext = Depends(require(Permission.OVERRIDE_VERDICT)),
) -> BacklinkRow:
    bl = await backlink_service.override_verdict(db, ctx, backlink_id, payload.status, payload.note)
    await audit_service.record(
        db, action=AuditAction.OVERRIDE, actor_user_id=ctx.user.id, workspace_id=ctx.workspace_id,
        entity_type="backlink", entity_id=backlink_id,
        summary=f"Manual override → {payload.status.value}", after={"note": payload.note},
    )
    await db.commit()
    await db.refresh(bl)  # reload updated_at (onupdate) + any expired cols
    return BacklinkRow.model_validate(bl)


@router.delete("/{backlink_id}", response_model=Message)
async def delete_backlink(
    backlink_id: uuid.UUID, db: DbSession,
    ctx: AuthContext = Depends(require(Permission.EDIT_BACKLINKS)),
) -> Message:
    source_url = await backlink_service.delete_backlink(db, ctx, backlink_id)
    await audit_service.record(
        db, action=AuditAction.DELETE, actor_user_id=ctx.user.id, workspace_id=ctx.workspace_id,
        entity_type="backlink", entity_id=backlink_id,
        summary=f"Deleted backlink {source_url[:120]}",
    )
    await db.commit()
    return Message(message="Backlink deleted")


@router.post("/{backlink_id}/recheck", response_model=RecheckResponse)
async def recheck_one(
    backlink_id: uuid.UUID, db: DbSession,
    ctx: AuthContext = Depends(require(Permission.RUN_CRAWLS)),
) -> RecheckResponse:
    await backlink_service.get_backlink(db, ctx, backlink_id)  # scope check
    job = await crawl_service.create_job(
        db, ctx, ids=[backlink_id], project_id=None, job_type=JobType.SINGLE
    )
    await audit_service.record(
        db, action=AuditAction.RECHECK, actor_user_id=ctx.user.id, workspace_id=ctx.workspace_id,
        entity_type="backlink", entity_id=backlink_id, summary="Manual recheck",
    )
    await db.commit()

    from app.workers.dispatch import enqueue_backlinks

    enqueue_backlinks([backlink_id], job_id=job.id, priority=True)
    return RecheckResponse(job_id=job.id, queued=1)


@router.post("/recheck", response_model=RecheckResponse)
async def recheck_bulk(
    payload: RecheckRequest, db: DbSession,
    ctx: AuthContext = Depends(require(Permission.RUN_CRAWLS)),
) -> RecheckResponse:
    ids = await crawl_service.select_recheck_ids(db, ctx, payload)
    if not ids:
        return RecheckResponse(job_id=uuid.uuid4(), queued=0)
    job_type = JobType.SINGLE if len(ids) == 1 else JobType.BULK
    job = await crawl_service.create_job(
        db, ctx, ids=ids, project_id=payload.project_id, job_type=job_type
    )
    # Register the run in the operations batch history (fail-open).
    from app.services import batch_service

    label = f"QA check {len(ids)} links"
    if payload.only_pending:
        label = f"QA check {len(ids)} pending links"
    elif payload.filters is not None:
        label = f"QA check {len(ids)} filtered links"
    if payload.older_than_days:
        label += f" (older than {payload.older_than_days} days)"
    batch_id = await batch_service.start(
        "recheck", ctx.workspace_id, project_id=payload.project_id,
        label=label, started_by=ctx.user.id, total=len(ids),
    )
    if batch_id is not None:
        job.batch_id = batch_id
    await audit_service.record(
        db, action=AuditAction.RECHECK, actor_user_id=ctx.user.id, workspace_id=ctx.workspace_id,
        entity_type="crawl_job", entity_id=job.id, summary=f"Bulk recheck ({len(ids)} links)",
    )
    await db.commit()

    from app.workers.dispatch import enqueue_backlinks

    enqueue_backlinks(ids, job_id=job.id, priority=payload.priority)
    return RecheckResponse(job_id=job.id, queued=len(ids))


@router.post("/bulk-edit", response_model=BulkEditResponse)
async def bulk_edit_backlinks(
    payload: BacklinkBulkEdit, db: DbSession,
    ctx: AuthContext = Depends(require(Permission.EDIT_BACKLINKS)),
) -> BulkEditResponse:
    """Assign a user and/or set a placement date on many selected links at once."""
    count = await backlink_service.bulk_edit(
        db, ctx, payload.ids, set_user=payload.set_user,
        assigned_user_label=payload.assigned_user_label,
        set_placement=payload.set_placement, placement_date=payload.placement_date,
    )
    bits = []
    if payload.set_user:
        bits.append(f"user → {payload.assigned_user_label or '(unassigned)'}")
    if payload.set_placement:
        bits.append(f"placement → {payload.placement_date.isoformat() if payload.placement_date else '(cleared)'}")
    await audit_service.record(
        db, action=AuditAction.UPDATE, actor_user_id=ctx.user.id, workspace_id=ctx.workspace_id,
        entity_type="backlink", entity_id=None,
        summary=f"Bulk edit {count} link(s): {', '.join(bits)}",
    )
    await db.commit()
    return BulkEditResponse(updated=count)


@router.post("/fill-missing-placement", response_model=BulkEditResponse)
async def fill_missing_placement(
    payload: FillMissingPlacementRequest, db: DbSession,
    ctx: AuthContext = Depends(require(Permission.EDIT_BACKLINKS)),
) -> BulkEditResponse:
    """Back-fill placement date = import date for links that have none (scoped to
    the given ids or the current grid filters)."""
    count = await backlink_service.fill_missing_placement(
        db, ctx, filters=payload.filters, ids=payload.ids
    )
    await audit_service.record(
        db, action=AuditAction.UPDATE, actor_user_id=ctx.user.id, workspace_id=ctx.workspace_id,
        entity_type="backlink", entity_id=None,
        summary=f"Back-filled placement date from import date for {count} link(s)",
    )
    await db.commit()
    return BulkEditResponse(updated=count)
