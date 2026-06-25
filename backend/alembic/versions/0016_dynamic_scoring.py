"""Dynamic scoring engine — parameter registry + versioned rule sets (Phase 8 F17–19).

Additive + idempotent. Creates ``scoring_parameters`` (seeded global registry) and
``scoring_rule_versions`` (versioned per-scope point sets), seeds a system-global
**v1** whose points mirror the registry defaults, and adds
``crawl_results.scoring_rule_version_id`` so each stored verdict records the rule
set that produced it. The QA engine is NOT yet wired to these tables, so this
migration changes no scores on deploy.

Revision ID: 0016_dynamic_scoring
Revises: 0015_sub_sheet_tabs
Create Date: 2026-06-26
"""

from __future__ import annotations

import json

from alembic import op
from sqlalchemy import text

# Register models on Base.metadata.
import app.models  # noqa: F401,E402
from app.models.scoring import ScoringParameter, ScoringRuleVersion

revision = "0016_dynamic_scoring"
down_revision = "0015_sub_sheet_tabs"
branch_labels = None
depends_on = None


# ── Seed registry ───────────────────────────────────────────────────────────
# Each parameter: discrete outcomes + the baseline points each contributes
# (negative = penalty). Mirrors today's severity model for the QA signals;
# metric bands (DA / Semrush / age / external index) seed to 0 so nothing moves
# until an admin configures them. The global v1 rule set is built from these.
def _o(*pairs):
    return [{"key": k, "label": lbl} for k, lbl in pairs]


_PARAMETERS = [
    dict(
        key="link_presence", display_name="Link presence", category="link", value_kind="enum",
        description="Is the backlink present on the source page?",
        outcomes=_o(("found", "Found"), ("wrong_target", "Wrong target URL"), ("missing", "Missing")),
        default_points={"found": 0, "wrong_target": -25, "missing": -60}, sort_order=10,
    ),
    dict(
        key="link_rel", display_name="Link rel / followability", category="link", value_kind="enum",
        description="The rel attribute on the matched link.",
        outcomes=_o(("dofollow", "Dofollow"), ("nofollow", "Nofollow"), ("sponsored", "Sponsored"), ("ugc", "UGC")),
        default_points={"dofollow": 0, "nofollow": -25, "sponsored": -10, "ugc": -10}, sort_order=20,
    ),
    dict(
        key="link_visibility", display_name="Link visibility", category="link", value_kind="enum",
        description="Whether the link is visible or hidden (CSS/comment/iframe/noscript).",
        outcomes=_o(("visible", "Visible"), ("hidden", "Hidden")),
        default_points={"visible": 0, "hidden": -25}, sort_order=30,
    ),
    dict(
        key="link_placement", display_name="Link placement", category="link", value_kind="enum",
        description="Where on the page the link sits.",
        outcomes=_o(("in_content", "In content"), ("sidebar", "Sidebar"), ("footer", "Footer"), ("header", "Header"), ("nav", "Nav")),
        default_points={"in_content": 0, "sidebar": -3, "footer": -3, "header": -3, "nav": -3}, sort_order=40,
    ),
    dict(
        key="anchor_match", display_name="Anchor text", category="anchor", value_kind="enum",
        description="Whether the anchor matches the agreed anchor.",
        outcomes=_o(("match", "Matches"), ("changed", "Changed"), ("missing", "Not specified")),
        default_points={"match": 0, "changed": -10, "missing": 0}, sort_order=50,
    ),
    dict(
        key="source_http", display_name="Source page HTTP", category="source", value_kind="enum",
        description="HTTP outcome of the source page.",
        outcomes=_o(("ok", "200 OK"), ("redirect", "Redirected"), ("not_found", "404 / 410"), ("forbidden", "403 (review)"), ("server_error", "5xx")),
        default_points={"ok": 0, "redirect": -3, "not_found": -60, "forbidden": 0, "server_error": -60}, sort_order=60,
    ),
    dict(
        key="source_indexability", display_name="Source indexability", category="indexing", value_kind="enum",
        description="Can the source page be indexed (meta robots / X-Robots / robots.txt)?",
        outcomes=_o(("indexable", "Indexable"), ("noindex", "Noindex"), ("robots_blocked", "Robots blocked"), ("unknown", "Unknown")),
        default_points={"indexable": 0, "noindex": -60, "robots_blocked": -60, "unknown": 0}, sort_order=70,
    ),
    dict(
        key="canonical", display_name="Canonical", category="indexing", value_kind="enum",
        description="Canonical relationship of the source page.",
        outcomes=_o(("self", "Self / OK"), ("missing", "Missing"), ("mismatch", "Mismatch"), ("cross_domain", "Cross-domain")),
        default_points={"self": 0, "missing": -3, "mismatch": -25, "cross_domain": -60}, sort_order=80,
    ),
    dict(
        key="duplicate", display_name="Duplicate", category="integrity", value_kind="enum",
        description="Whether this backlink duplicates another.",
        outcomes=_o(("unique", "Unique"), ("duplicate", "Duplicate")),
        default_points={"unique": 0, "duplicate": 0}, sort_order=90,
    ),
    dict(
        key="external_index", display_name="External index status", category="indexing", value_kind="enum",
        description="Indexed in Google (serper/GSC) — off by default.",
        outcomes=_o(("indexed", "Indexed"), ("not_indexed", "Not indexed"), ("unknown", "Unknown")),
        default_points={"indexed": 0, "not_indexed": 0, "unknown": 0}, sort_order=100,
    ),
    dict(
        key="source_da_band", display_name="Source domain authority (Moz DA)", category="source_domain", value_kind="band",
        description="Moz Domain Authority band of the source domain — off by default.",
        outcomes=_o(("high", "High (60+)"), ("medium", "Medium (30–59)"), ("low", "Low (<30)"), ("unknown", "Unknown")),
        default_points={"high": 0, "medium": 0, "low": 0, "unknown": 0}, sort_order=110,
    ),
    dict(
        key="semrush_as_band", display_name="Semrush Authority Score", category="source_domain", value_kind="band",
        description="Semrush Authority Score band of the source domain — off by default.",
        outcomes=_o(("high", "High (50+)"), ("medium", "Medium (25–49)"), ("low", "Low (<25)"), ("unknown", "Unknown")),
        default_points={"high": 0, "medium": 0, "low": 0, "unknown": 0}, sort_order=120,
    ),
    dict(
        key="domain_age_band", display_name="Source domain age", category="source_domain", value_kind="band",
        description="Registration age band of the source domain — off by default.",
        outcomes=_o(("old", "Old (5y+)"), ("medium", "Medium (1–5y)"), ("new", "New (<1y)"), ("unknown", "Unknown")),
        default_points={"old": 0, "medium": 0, "new": 0, "unknown": 0}, sort_order=130,
    ),
]

_INSERT_PARAM = text(
    """
    INSERT INTO scoring_parameters
        (id, key, display_name, description, category, value_kind,
         outcomes, default_points, is_active, sort_order, created_at, updated_at)
    VALUES
        (gen_random_uuid(), :key, :display_name, :description, :category, :value_kind,
         :outcomes ::jsonb, :default_points ::jsonb, true, :sort_order, now(), now())
    ON CONFLICT (key) DO NOTHING
    """
)


def upgrade() -> None:
    bind = op.get_bind()
    ScoringParameter.__table__.create(bind=bind, checkfirst=True)
    ScoringRuleVersion.__table__.create(bind=bind, checkfirst=True)

    # crawl_results is RANGE-partitioned; ALTER on the parent cascades to partitions.
    op.execute(
        "ALTER TABLE crawl_results ADD COLUMN IF NOT EXISTS scoring_rule_version_id uuid"
    )

    # Seed the parameter registry (idempotent on key).
    for p in _PARAMETERS:
        bind.execute(
            _INSERT_PARAM,
            {
                **p,
                "outcomes": json.dumps(p["outcomes"]),
                "default_points": json.dumps(p["default_points"]),
            },
        )

    # Seed the system-global v1 from the registry defaults (only if none exists).
    global_rules = {p["key"]: p["default_points"] for p in _PARAMETERS}
    bind.execute(
        text(
            """
            INSERT INTO scoring_rule_versions
                (id, workspace_id, scope, scope_ref_id, version, is_latest, rules, bands,
                 note, created_by, activated_at, created_at, updated_at)
            SELECT gen_random_uuid(), NULL, 'global', NULL, 1, true,
                   :rules ::jsonb,
                   '{"fail_below": 30, "warn_below": 80}'::jsonb,
                   'Seeded defaults (mirror the standard QA scoring).', NULL, now(), now(), now()
            WHERE NOT EXISTS (SELECT 1 FROM scoring_rule_versions WHERE scope = 'global')
            """
        ),
        {"rules": json.dumps(global_rules)},
    )


def downgrade() -> None:
    op.execute("ALTER TABLE crawl_results DROP COLUMN IF EXISTS scoring_rule_version_id")
    op.execute("DROP TABLE IF EXISTS scoring_rule_versions CASCADE")
    op.execute("DROP TABLE IF EXISTS scoring_parameters CASCADE")
