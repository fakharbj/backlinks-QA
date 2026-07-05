"""Company branding lookups.

Branding is a plain workspace Setting (key="branding", value={"company_name",
"company_domain", "logo_data_uri"}) written from the Team/Settings UI via the
Admin-only ``PUT /settings`` upsert. Two readers live here: the tenant-scoped
``get_branding`` (sheet sync uses ``company_domain`` for auto-provisioned user
emails) and the deliberately public ``public_branding`` for the login screen —
which must NEVER expose ``company_domain`` (it would leak the email format for
every auto-created account).
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.settings import Setting
from app.models.user import Workspace

BRANDING_KEY = "branding"


async def get_branding(db: AsyncSession, workspace_id: uuid.UUID) -> dict:
    """Full branding dict for one workspace ({} when unset)."""
    setting = (
        await db.execute(
            select(Setting).where(
                Setting.workspace_id == workspace_id, Setting.key == BRANDING_KEY
            )
        )
    ).scalar_one_or_none()
    return setting.value or {} if setting is not None else {}


async def public_branding(db: AsyncSession) -> dict:
    """Login-screen branding — safe subset only, no auth required.

    Single-tenant install in practice: pick the oldest branding setting, and
    fall back to the first active workspace's name when none is configured.
    ``company_domain`` is intentionally omitted (don't advertise the email
    format of auto-provisioned accounts to anonymous visitors).
    """
    setting = (
        await db.execute(
            select(Setting)
            .where(Setting.key == BRANDING_KEY)
            .order_by(Setting.created_at.asc())
            .limit(1)
        )
    ).scalar_one_or_none()
    value = (setting.value or {}) if setting is not None else {}
    company_name = value.get("company_name") or None
    if not company_name:
        company_name = (
            await db.execute(
                select(Workspace.name)
                .where(Workspace.is_active.is_(True))
                .order_by(Workspace.created_at.asc())
                .limit(1)
            )
        ).scalar_one_or_none()
    return {
        "company_name": company_name,
        "logo_data_uri": value.get("logo_data_uri") or None,
    }
