"""Link-type catalog (Phase 8 — prerequisite for per-link-type scoring).

A workspace-scoped catalog of backlink types (Web 2.0, Profile, Guest Post, Blog
Comment, Forum, …). It is the single catalog shared by ``backlink_records``
(``link_type_id``), the dynamic scoring rules (link_type scope), alert scopes, and
competitor categorisation. Managed manually; seeded from existing free-text
``backlink_records.link_type`` and (later) from sheet sub-sheet/tab names.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class LinkType(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "link_types"
    __table_args__ = (
        UniqueConstraint("workspace_id", "slug", name="uq_link_types_ws_slug"),
        Index("ix_link_types_workspace", "workspace_id"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), nullable=False)
    color: Mapped[str | None] = mapped_column(String(20))
    description: Mapped[str | None] = mapped_column(String(300))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    # Alias/redirect layer (Phase 10): set (with deleted_at) when this type was
    # merged into another — resolve_or_create follows the chain, so old sheet tab
    # names keep resolving to the surviving master instead of re-creating the dup.
    merged_into_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("link_types.id", ondelete="SET NULL")
    )
