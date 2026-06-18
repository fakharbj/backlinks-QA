"""Idempotent demo seed data for local and staging environments.

Run with:
    python -m app.db.seed
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from sqlalchemy import select

from app.core.security import hash_password
from app.crawler.normalize import normalize_url
from app.db.session import session_scope
from app.models.backlink import BacklinkRecord
from app.models.enums import OverallStatus, RelType
from app.models.project import Campaign, Project, Vendor
from app.models.user import User, Workspace, WorkspaceMember
from app.core.rbac import Role


async def seed() -> None:
    async with session_scope() as db:
        user = (
            await db.execute(select(User).where(User.email == "admin@linksentinel.local"))
        ).scalar_one_or_none()
        if user is None:
            user = User(
                email="admin@linksentinel.local",
                full_name="SEO Ops Admin",
                password_hash=hash_password("ChangeMe123!"),
            )
            db.add(user)
            await db.flush()

        workspace = (
            await db.execute(select(Workspace).where(Workspace.slug == "acme-link-ops"))
        ).scalar_one_or_none()
        if workspace is None:
            workspace = Workspace(name="Acme Link Ops", slug="acme-link-ops")
            db.add(workspace)
            await db.flush()

        member = (
            await db.execute(
                select(WorkspaceMember).where(
                    WorkspaceMember.user_id == user.id,
                    WorkspaceMember.workspace_id == workspace.id,
                )
            )
        ).scalar_one_or_none()
        if member is None:
            db.add(WorkspaceMember(user_id=user.id, workspace_id=workspace.id, role=Role.ADMIN))

        project = (
            await db.execute(
                select(Project).where(
                    Project.workspace_id == workspace.id,
                    Project.slug == "acme-backlinks",
                )
            )
        ).scalar_one_or_none()
        if project is None:
            project = Project(
                workspace_id=workspace.id,
                name="Acme Backlinks",
                slug="acme-backlinks",
                client_name="Acme Co",
                target_domain="acme.test",
                target_urls=["https://acme.test/seo", "https://acme.test/pricing"],
                tags=["demo", "q3"],
            )
            db.add(project)
            await db.flush()

        vendor = await _vendor(db, workspace.id, "EditorialHub")
        campaign = await _campaign(db, workspace.id, project.id, "Q3 Outreach")

        samples = [
            (
                "https://example.com/best-seo-tools",
                "https://acme.test/seo",
                "Acme SEO",
                RelType.DOFOLLOW,
                OverallStatus.PENDING,
                None,
            ),
            (
                "https://publisher.test/acme-review",
                "https://acme.test/pricing",
                "pricing guide",
                RelType.DOFOLLOW,
                OverallStatus.WARNING,
                72,
            ),
            (
                "https://old-blog.test/resources",
                "https://acme.test/seo",
                "Acme resources",
                RelType.NOFOLLOW,
                OverallStatus.FAIL,
                24,
            ),
        ]
        for source, target, anchor, rel, status, score in samples:
            await _backlink(
                db,
                workspace_id=workspace.id,
                project_id=project.id,
                vendor_id=vendor.id,
                campaign_id=campaign.id,
                source=source,
                target=target,
                anchor=anchor,
                rel=rel,
                status=status,
                score=score,
            )


async def _vendor(db, workspace_id, name: str) -> Vendor:
    vendor = (
        await db.execute(
            select(Vendor).where(Vendor.workspace_id == workspace_id, Vendor.name == name)
        )
    ).scalar_one_or_none()
    if vendor is None:
        vendor = Vendor(workspace_id=workspace_id, name=name, website="https://editorialhub.test")
        db.add(vendor)
        await db.flush()
    return vendor


async def _campaign(db, workspace_id, project_id, name: str) -> Campaign:
    campaign = (
        await db.execute(
            select(Campaign).where(Campaign.project_id == project_id, Campaign.name == name)
        )
    ).scalar_one_or_none()
    if campaign is None:
        campaign = Campaign(workspace_id=workspace_id, project_id=project_id, name=name)
        db.add(campaign)
        await db.flush()
    return campaign


async def _backlink(
    db,
    *,
    workspace_id,
    project_id,
    vendor_id,
    campaign_id,
    source: str,
    target: str,
    anchor: str,
    rel: RelType,
    status: OverallStatus,
    score: int | None,
) -> None:
    src = normalize_url(source)
    tgt = normalize_url(target)
    exists = (
        await db.execute(
            select(BacklinkRecord.id).where(
                BacklinkRecord.project_id == project_id,
                BacklinkRecord.source_url_normalized == src.normalized,
                BacklinkRecord.target_url_normalized == tgt.normalized,
            )
        )
    ).scalar_one_or_none()
    if exists is not None:
        return
    db.add(
        BacklinkRecord(
            workspace_id=workspace_id,
            project_id=project_id,
            vendor_id=vendor_id,
            campaign_id=campaign_id,
            source_page_url=source,
            target_url=target,
            expected_target_url=target,
            expected_anchor_text=anchor,
            expected_rel=rel,
            client_name="Acme Co",
            tags=["demo"],
            source_url_normalized=src.normalized,
            target_url_normalized=tgt.normalized,
            source_domain=src.registrable_domain,
            target_domain=tgt.registrable_domain,
            status=status,
            score=score,
            next_check_at=datetime.now(timezone.utc),
        )
    )


if __name__ == "__main__":
    asyncio.run(seed())
