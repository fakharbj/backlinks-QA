"""Dynamic scoring engine models (Phase 8 — Features 17–19).

Two tables turn the implicit, severity-driven score into an explicit, fully
configurable, per-parameter score that can differ by link type and by project:

* ``scoring_parameters`` — the seeded **registry** of *what can be scored*: one
  row per scorable signal (link presence, rel, indexability, source DA band, …).
  A read-only catalog the UI renders as an editable grid. ``outcomes`` lists the
  discrete values a parameter can take; ``default_points`` is the baseline delta
  each outcome contributes (negative = penalty), used to seed the global v1.

* ``scoring_rule_versions`` — the **configured points** for one scope, versioned
  and frozen. One row per (scope, scope_ref, version). The resolver picks the
  most specific *latest* version (project → link_type → workspace → global). The
  ``rules`` JSONB holds ``{parameter_key: {outcome_key: points}}``; ``bands`` the
  PASS/WARNING/FAIL thresholds. ``crawl_results.scoring_rule_version_id`` records
  which version produced each stored verdict, so historical scores stay
  explainable and a re-score is auditable.

Scope encoding:
  global     → workspace_id NULL, scope_ref_id NULL   (system defaults)
  workspace  → workspace_id set,  scope_ref_id NULL
  project    → workspace_id set,  scope_ref_id = projects.id
  link_type  → workspace_id set,  scope_ref_id = link_types.id

"One latest version per (scope, scope_ref)" and sequential ``version`` numbers are
enforced transactionally in ``scoring_config_service`` (NULL scope_ref makes a DB
partial-unique index unreliable across the global/workspace scopes).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ScoringParameter(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Global registry of scorable parameters (seeded, not per-workspace)."""

    __tablename__ = "scoring_parameters"
    __table_args__ = (Index("ix_scoring_parameters_active", "is_active", "sort_order"),)

    key: Mapped[str] = mapped_column(String(60), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(String(300))
    category: Mapped[str] = mapped_column(String(40), nullable=False)  # link/indexing/source_domain/…
    value_kind: Mapped[str] = mapped_column(String(20), nullable=False)  # enum | boolean | band
    # [{"key": "missing", "label": "Link missing"}, …] — the rows shown in the grid.
    outcomes: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    # {"missing": -60, "found": 0, …} — baseline contribution per outcome.
    default_points: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=100, nullable=False)


class ScoringRuleVersion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A frozen, versioned set of configured points for one scope."""

    __tablename__ = "scoring_rule_versions"
    __table_args__ = (
        Index(
            "ix_scoring_rule_versions_resolve",
            "workspace_id",
            "scope",
            "scope_ref_id",
            "is_latest",
        ),
        Index("ix_scoring_rule_versions_global", "scope", "is_latest"),
    )

    # NULL for the system-global scope.
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    scope: Mapped[str] = mapped_column(String(20), nullable=False)  # global|workspace|project|link_type
    scope_ref_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_latest: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # {parameter_key: {outcome_key: points}} — sparse overrides; missing params
    # fall back to the global/registry default at resolution time.
    rules: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # {"fail_below": 30, "warn_below": 80} — PASS/WARNING/FAIL thresholds.
    bands: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{\"fail_below\": 30, \"warn_below\": 80}'::jsonb")
    )
    note: Mapped[str | None] = mapped_column(String(300))
    created_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
