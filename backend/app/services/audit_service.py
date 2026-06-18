"""Audit trail writer (PRD §9.5). Every mutation/auth event flows through here."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import correlation_id
from app.models.audit import AuditLog
from app.models.enums import AuditAction


async def record(
    db: AsyncSession,
    *,
    action: AuditAction,
    actor_user_id: uuid.UUID | None = None,
    workspace_id: uuid.UUID | None = None,
    entity_type: str | None = None,
    entity_id: str | uuid.UUID | None = None,
    summary: str | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> AuditLog:
    log = AuditLog(
        action=action,
        actor_user_id=actor_user_id,
        workspace_id=workspace_id,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        summary=summary,
        before=before,
        after=after,
        ip_address=ip_address,
        user_agent=user_agent,
        correlation_id=correlation_id.get(),
    )
    db.add(log)
    return log
