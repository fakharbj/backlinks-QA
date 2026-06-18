"""Workspace-scoped get-or-create helpers for vendors/campaigns.

Used by the import processor (which runs in a worker without an ``AuthContext``),
so they take ``workspace_id`` directly rather than a context object.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Campaign, Vendor


async def resolve_vendor(db: AsyncSession, workspace_id: uuid.UUID, name: str) -> uuid.UUID:
    vendor = (
        await db.execute(
            select(Vendor).where(Vendor.workspace_id == workspace_id, Vendor.name == name)
        )
    ).scalar_one_or_none()
    if vendor is None:
        vendor = Vendor(workspace_id=workspace_id, name=name)
        db.add(vendor)
        await db.flush()
    return vendor.id


async def resolve_campaign(
    db: AsyncSession, workspace_id: uuid.UUID, project_id: uuid.UUID, name: str
) -> uuid.UUID:
    campaign = (
        await db.execute(
            select(Campaign).where(
                Campaign.project_id == project_id, Campaign.name == name
            )
        )
    ).scalar_one_or_none()
    if campaign is None:
        campaign = Campaign(workspace_id=workspace_id, project_id=project_id, name=name)
        db.add(campaign)
        await db.flush()
    return campaign.id
