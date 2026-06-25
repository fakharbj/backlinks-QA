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
_CODE_MAP: dict[str, tuple[str, str]] = {
    "CAN-02": ("canonical", "missing"),  # canonical tag missing (label NONE)
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


# The implicit default: empty overrides + standard bands → exactly today's scoring.
DEFAULT_RULESET = ResolvedRuleset()
