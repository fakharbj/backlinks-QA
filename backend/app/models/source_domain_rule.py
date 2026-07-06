"""Saved source-domain qualification rules (0033).

A rule is a named, shareable definition (stored as JSONB) describing the
thresholds/conditions that qualify a source domain (e.g. DA/PA/spam/AS bands).
Rules are workspace-scoped; ``project_id`` NULL means the rule applies across the
whole workspace, otherwise it is scoped to a single project. ``is_shared`` marks
a rule visible to the whole workspace vs. private to its author.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class SourceDomainRule(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "source_domain_rules"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "project_id", "name",
            name="uq_source_domain_rules_ws_proj_name",
        ),
        Index("ix_source_domain_rules_ws", "workspace_id", "project_id"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    # NULL = workspace-wide; otherwise scoped to a single project.
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500))
    definition: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    is_shared: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
