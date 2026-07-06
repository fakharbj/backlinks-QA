"""Dynamic scoring: the resolved rule set + the issue→parameter registry.

Framework-free (no DB/Pydantic) so the QA engine stays pure and unit-testable.
A ``ResolvedRuleset`` is produced by ``services.scoring_config_service.resolve``
(which has the DB session) and handed to ``evaluate()``; the engine never touches
the database.

How scoring stays backward-compatible
-------------------------------------
Each QA ``Issue`` is mapped to a configurable ``(parameter, outcome)`` via the
registry below. At scoring time the delta for an issue is:

    rules[parameter][outcome]   if the resolved rule set overrides it,
    -issue.severity.deduction   otherwise (today's behaviour).

So the seeded global **v1** (empty ``rules``) reproduces today's scores exactly,
and any issue whose code/label is *not* in the registry simply falls back to its
severity — an unmapped code can never raise or change a score. Metric parameters
(DA / Semrush / age / external index / duplicate) are not issues; they are scored
from ``signals`` the worker derives, and contribute 0 unless explicitly configured.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from app.qa.enums import IssueLabel

# ── Issue → (parameter_key, outcome) registry ────────────────────────────────
# Mapped by IssueLabel (groups the underlying check codes); only confident,
# unambiguous mappings are listed. Everything else falls back to Severity.
_LABEL_MAP: dict[IssueLabel, tuple[str, str]] = {
    IssueLabel.LINK_FOUND: ("link_presence", "found"),
    IssueLabel.LINK_MISSING: ("link_presence", "missing"),
    IssueLabel.WRONG_TARGET: ("link_presence", "wrong_target"),
    IssueLabel.LINK_NOFOLLOW: ("link_rel", "nofollow"),
    IssueLabel.PAGE_NOFOLLOW: ("link_rel", "nofollow"),
    IssueLabel.X_ROBOTS_NOFOLLOW: ("link_rel", "nofollow"),
    IssueLabel.LINK_SPONSORED: ("link_rel", "sponsored"),
    IssueLabel.LINK_UGC: ("link_rel", "ugc"),
    IssueLabel.LINK_HIDDEN: ("link_visibility", "hidden"),
    IssueLabel.ANCHOR_CHANGED: ("anchor_match", "changed"),
    IssueLabel.PAGE_NOINDEX: ("source_indexability", "noindex"),
    IssueLabel.X_ROBOTS_NOINDEX: ("source_indexability", "noindex"),
    IssueLabel.ROBOTS_BLOCKED: ("source_indexability", "robots_blocked"),
    IssueLabel.CANONICAL_CROSS_DOMAIN: ("canonical", "cross_domain"),
    IssueLabel.CANONICAL_MISMATCH: ("canonical", "mismatch"),
    IssueLabel.SOURCE_404: ("source_http", "not_found"),
    IssueLabel.SOURCE_403: ("source_http", "forbidden"),
    IssueLabel.SOURCE_5XX: ("source_http", "server_error"),
    IssueLabel.SOFT_404: ("source_http", "not_found"),
}

# A few mapped by code where the label is NONE but the concern is unambiguous.
# HTTP-301/302 map redirects to their own tunable (parameter+outcome exist in the
# 0016 registry); without this they fell back to plain Severity and could not be
# tuned independently. Only mappings whose (parameter, outcome) exist are added.
_CODE_MAP: dict[str, tuple[str, str]] = {
    "CAN-02": ("canonical", "missing"),  # canonical tag missing (label NONE)
    "HTTP-301": ("source_http", "redirect"),  # permanent redirect (tunable)
    "HTTP-302": ("source_http", "redirect"),  # temporary redirect (tunable)
}

# Placement regions LNK-17 can report (label NONE → mapped from evidence).
_PLACEMENT_REGIONS = {"footer", "sidebar", "header", "nav"}

# Parameters scored from worker-derived signals rather than QA issues.
METRIC_PARAMS = (
    "source_da_band",
    "semrush_as_band",
    "domain_age_band",
    "external_index",
    "duplicate",
)


def metric_bands(
    da: int | None,
    semrush_as: int | None,
    age_days: int | None,
    *,
    da_high: int,
    da_medium: int,
    as_high: int,
    as_medium: int,
    age_old_days: int,
    age_medium_days: int,
) -> dict[str, str]:
    """Pure band computation for the DA / Semrush-AS / domain-age scoring signals.

    Emits a signal ONLY when the underlying metric is present — a missing metric
    contributes no key (so an absent metric never moves the score, even if a rule
    set assigns points to the "unknown" outcome). Cutoffs are passed in (from
    ``settings``) so the engine stays framework-free and unit-testable."""
    out: dict[str, str] = {}
    if da is not None:
        out["source_da_band"] = "high" if da >= da_high else "medium" if da >= da_medium else "low"
    if semrush_as is not None:
        out["semrush_as_band"] = (
            "high" if semrush_as >= as_high else "medium" if semrush_as >= as_medium else "low"
        )
    if age_days is not None:
        out["domain_age_band"] = (
            "old" if age_days >= age_old_days
            else "medium" if age_days >= age_medium_days
            else "new"
        )
    return out


def param_outcome_for(issue) -> tuple[str, str] | None:
    """Resolve an ``Issue`` to its configurable ``(parameter, outcome)`` or None."""
    if issue.code in _CODE_MAP:
        return _CODE_MAP[issue.code]
    if issue.code == "LNK-17":  # placement: outcome is the region from evidence
        region = (issue.evidence or {}).get("region")
        if region in _PLACEMENT_REGIONS:
            return ("link_placement", region)
        return None
    return _LABEL_MAP.get(issue.label)


@dataclass(slots=True)
class ResolvedRuleset:
    """The scoring rule set in effect for one backlink, already resolved by scope."""

    version_id: uuid.UUID | None = None
    scope: str = "global"
    rules: dict = field(default_factory=dict)  # {parameter_key: {outcome: points}}
    bands: dict = field(default_factory=lambda: {"fail_below": 30, "warn_below": 80})

    def points(self, parameter: str, outcome: str) -> int | None:
        """The configured points override for a ``(parameter, outcome)`` or None."""
        block = self.rules.get(parameter)
        if not block:
            return None
        value = block.get(outcome)
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @property
    def fail_below(self) -> int:
        try:
            return int(self.bands.get("fail_below", 30))
        except (TypeError, ValueError):
            return 30

    @property
    def warn_below(self) -> int:
        try:
            return int(self.bands.get("warn_below", 80))
        except (TypeError, ValueError):
            return 80


# ── Static human labels for breakdown transparency ───────────────────────────
# Mirror the seeded parameters/outcomes from migration 0016 so the pure scorer can
# annotate each ScoreStep with readable names WITHOUT a DB round-trip. If a key is
# absent (e.g. a newer parameter) the scorer falls back to the raw key — never
# raising — so this staying slightly behind the DB registry is safe.
PARAM_LABELS: dict[str, str] = {
    "link_presence": "Link presence",
    "link_rel": "Link rel / followability",
    "link_visibility": "Link visibility",
    "link_placement": "Link placement",
    "anchor_match": "Anchor text",
    "source_http": "Source page HTTP",
    "source_indexability": "Source indexability",
    "canonical": "Canonical",
    "duplicate": "Duplicate",
    "external_index": "External index status",
    "source_da_band": "Source domain authority (Moz DA)",
    "semrush_as_band": "Semrush Authority Score",
    "domain_age_band": "Source domain age",
}

OUTCOME_LABELS: dict[tuple[str, str], str] = {
    ("link_presence", "found"): "Found",
    ("link_presence", "wrong_target"): "Wrong target URL",
    ("link_presence", "missing"): "Missing",
    ("link_rel", "dofollow"): "Dofollow",
    ("link_rel", "nofollow"): "Nofollow",
    ("link_rel", "sponsored"): "Sponsored",
    ("link_rel", "ugc"): "UGC",
    ("link_visibility", "visible"): "Visible",
    ("link_visibility", "hidden"): "Hidden",
    ("link_placement", "in_content"): "In content",
    ("link_placement", "sidebar"): "Sidebar",
    ("link_placement", "footer"): "Footer",
    ("link_placement", "header"): "Header",
    ("link_placement", "nav"): "Nav",
    ("anchor_match", "match"): "Matches",
    ("anchor_match", "changed"): "Changed",
    ("anchor_match", "missing"): "Not specified",
    ("source_http", "ok"): "200 OK",
    ("source_http", "redirect"): "Redirected",
    ("source_http", "not_found"): "404 / 410",
    ("source_http", "forbidden"): "403 (review)",
    ("source_http", "server_error"): "5xx",
    ("source_indexability", "indexable"): "Indexable",
    ("source_indexability", "noindex"): "Noindex",
    ("source_indexability", "robots_blocked"): "Robots blocked",
    ("source_indexability", "unknown"): "Unknown",
    ("canonical", "self"): "Self / OK",
    ("canonical", "missing"): "Missing",
    ("canonical", "mismatch"): "Mismatch",
    ("canonical", "cross_domain"): "Cross-domain",
    ("duplicate", "unique"): "Unique",
    ("duplicate", "duplicate"): "Duplicate",
    ("external_index", "indexed"): "Indexed",
    ("external_index", "not_indexed"): "Not indexed",
    ("external_index", "unknown"): "Unknown",
    ("source_da_band", "high"): "High (60+)",
    ("source_da_band", "medium"): "Medium (30–59)",
    ("source_da_band", "low"): "Low (<30)",
    ("source_da_band", "unknown"): "Unknown",
    ("semrush_as_band", "high"): "High (50+)",
    ("semrush_as_band", "medium"): "Medium (25–49)",
    ("semrush_as_band", "low"): "Low (<25)",
    ("semrush_as_band", "unknown"): "Unknown",
    ("domain_age_band", "old"): "Old (5y+)",
    ("domain_age_band", "medium"): "Medium (1–5y)",
    ("domain_age_band", "new"): "New (<1y)",
    ("domain_age_band", "unknown"): "Unknown",
}


def param_label(parameter: str) -> str:
    """Human name for a parameter key (falls back to the raw key)."""
    return PARAM_LABELS.get(parameter, parameter)


def outcome_label(parameter: str, outcome: str) -> str:
    """Human name for a (parameter, outcome) pair (falls back to the raw outcome)."""
    return OUTCOME_LABELS.get((parameter, outcome), outcome)


# The implicit default: empty overrides + standard bands → exactly today's scoring.
DEFAULT_RULESET = ResolvedRuleset()
