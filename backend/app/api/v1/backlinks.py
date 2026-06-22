"""Backlink grid, detail, mutation, override, and recheck endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status

from app.core.deps import AuthContext, AuthCtx, DbSession, ReadSession, require
from app.core.rbac import Permission
from app.models.enums import AuditAction, Indexability, JobType, OverallStatus, RelType
from app.schemas.backlink import (
    BacklinkCreate,
    BacklinkDetail,
    BacklinkFilters,
    BacklinkOverride,
    BacklinkRow,
    BacklinkUpdate,
    CrawlResultOut,
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
    status_filter: OverallStatus | None = Query(default=None, alias="status"),
    issue_label: str | None = None,
    score_min: int | None = Query(default=None, ge=0, le=100),
    score_max: int | None = Query(default=None, ge=0, le=100),
    rel: RelType | None = None,
    indexability: Indexability | None = None,
    robots_status: str | None = None,
    canonical_status: str | None = None,
    vendor_id: uuid.UUID | None = None,
    campaign_id: uuid.UUID | None = None,
    tag: str | None = None,
    source_domain: str | None = None,
    assigned_user_id: uuid.UUID | None = None,
    search: str | None = None,
    sort: str = Query(default="score", pattern="^(score|last_checked_at|created_at)$"),
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = None,
    with_total: bool = False,
) -> KeysetPage[BacklinkRow]:
    filters = BacklinkFilters(
        project_id=project_id, status=status_filter, issue_label=issue_label,
        score_min=score_min, score_max=score_max, rel=rel, indexability=indexability,
        robots_status=robots_status, canonical_status=canonical_status, vendor_id=vendor_id,
        campaign_id=campaign_id, tag=tag, source_domain=source_domain,
        assigned_user_id=assigned_user_id, search=search,
    )
    rows, next_cursor, has_more = await backlink_service.list_backlinks(
        db, ctx, filters, sort=sort, limit=limit, cursor=cursor
    )
    total = await backlink_service.count_backlinks(db, ctx, filters) if with_total else None
    return KeysetPage[BacklinkRow](
        items=[BacklinkRow.model_validate(r) for r in rows],
        next_cursor=next_cursor,
        has_more=has_more,
        total=total,
    )


@router.post("", response_model=BacklinkRow, status_code=status.HTTP_201_CREATED)
async def create_backlink(
    payload: BacklinkCreate, db: DbSession,
    ctx: AuthContext = Depends(require(Permission.EDIT_BACKLINKS)),
) -> BacklinkRow:
    bl = await backlink_service.create_backlink(db, ctx, payload)
    await db.commit()
    return BacklinkRow.model_validate(bl)


@router.get("/{backlink_id}", response_model=BacklinkDetail)
async def get_backlink(backlink_id: uuid.UUID, ctx: AuthCtx, db: ReadSession) -> BacklinkDetail:
    bl, issues, latest, history = await backlink_service.get_detail(db, ctx, backlink_id)
    detail = BacklinkDetail.model_validate(bl)
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
        )
    detail.history = [
        HistoryEventOut(event_type=h.event_type.value,
                        severity=h.severity.value if h.severity else None, field=h.field,
                        old_value=h.old_value, new_value=h.new_value, score_delta=h.score_delta,
                        created_at=h.created_at)
        for h in history
    ]
    return detail


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
    return BacklinkRow.model_validate(bl)


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
    await audit_service.record(
        db, action=AuditAction.RECHECK, actor_user_id=ctx.user.id, workspace_id=ctx.workspace_id,
        entity_type="crawl_job", entity_id=job.id, summary=f"Bulk recheck ({len(ids)} links)",
    )
    await db.commit()

    from app.workers.dispatch import enqueue_backlinks

    enqueue_backlinks(ids, job_id=job.id, priority=payload.priority)
    return RecheckResponse(job_id=job.id, queued=len(ids))
