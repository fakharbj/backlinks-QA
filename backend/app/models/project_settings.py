"""Project settings + main domains (Phase 8, feature 2).

``ProjectSettings`` is a 1:1 companion to a project carrying QA policy (the
sponsored/index expectations + score bands). ``ProjectDomain`` holds the project's
one-or-more **main domains** (the site(s) it builds links to); exactly one is
``is_primary`` (enforced by a partial unique index). The link-matching authority
rewire that *uses* these domains is a later, separately-confirmed step — these
tables only store + expose them for now.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, Index, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


def _default_thresholds() -> dict:
    return {"fail_below": 30, "warn_below": 80}


class ProjectSettings(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "project_settings"
    __table_args__ = (
        UniqueConstraint("project_id", name="uq_project_settings_project"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    scoring_profile: Mapped[str] = mapped_column(
        String(20), default="inherit_global", nullable=False
    )  # inherit_global | custom
    index_expected: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    treat_sponsored_as_follow: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    status_thresholds: Mapped[dict] = mapped_column(JSONB, default=_default_thresholds)
    extra: Mapped[dict] = mapped_column(JSONB, default=dict)


class ProjectDomain(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "project_domains"
    __table_args__ = (
        UniqueConstraint("project_id", "domain", name="uq_project_domains_project_domain"),
        Index("ix_project_domains_workspace_domain", "workspace_id", "domain"),
        # At most one primary domain per project.
        Index(
            "uq_project_domains_one_primary", "project_id",
            unique=True, postgresql_where=text("is_primary"),
        ),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    domain: Mapped[str] = mapped_column(String(255), nullable=False)  # registrable, lowercased
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
