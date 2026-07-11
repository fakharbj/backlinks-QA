"""Domain recommendations (Phase 10 P4).

One row per (workspace, project, domain, person): the suggestion the engine (or
an admin, ``source='manual'``) made, plus what the person did with it —
suggested → viewed → accepted | skipped. Keyed by ``domain_key`` (NOT a FK to
``source_domains``) so rows survive the catalog recompute's delete/rebuild, same
reasoning as ``competitor_domain_decisions``.
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import Date, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class DomainRecommendation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "domain_recommendations"
    __table_args__ = (
        # Uniqueness lives in a coalesce-based unique INDEX (created in migration
        # 0046) because project_id / recommended_to are nullable.
        Index("ix_domain_reco_person", "workspace_id", "recommended_to", "status"),
        Index("ix_domain_reco_project", "workspace_id", "project_id"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    domain_key: Mapped[str] = mapped_column(String(255), nullable=False)
    assignment_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    recommended_to: Mapped[str | None] = mapped_column(String(200))  # user label
    link_type_name: Mapped[str | None] = mapped_column(String(80))
    source: Mapped[str] = mapped_column(String(10), default="auto", nullable=False)  # auto|manual
    status: Mapped[str] = mapped_column(String(12), default="suggested", nullable=False)
    reason: Mapped[str | None] = mapped_column(String(300))
    priority: Mapped[str | None] = mapped_column(String(10))
    due_date: Mapped[date | None] = mapped_column(Date)
    note: Mapped[str | None] = mapped_column(String(300))
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
