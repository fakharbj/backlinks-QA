"""REL-* — rel-attribute checks (PRD §8.6 F).

Policy hook: ``treat_sponsored_as_follow`` controls whether sponsored/ugc are INFO
(paid campaigns) or HIGH (editorial campaigns).
"""

from __future__ import annotations

from typing import Iterable

from app.qa.checks._base import issue
from app.qa.enums import IssueCategory, IssueLabel, RelType, Severity
from app.qa.registry import check
from app.qa.types import CheckContext, Issue

CAT = IssueCategory.REL


@check("REL-eval", CAT)
def rel_evaluation(ctx: CheckContext) -> Iterable[Issue]:
    link = ctx.artifact.primary_link
    if link is None:
        return
    rel = set(link.rel)
    follow_expected = ctx.expected_rel in (RelType.DOFOLLOW,) or (
        ctx.expected_rel in (RelType.SPONSORED, RelType.UGC) and ctx.policy.treat_sponsored_as_follow
    )

    if "nofollow" in rel and follow_expected:
        yield issue(code="REL-02", label=IssueLabel.LINK_NOFOLLOW, category=CAT,
                    severity=Severity.HIGH,
                    message="Link is rel=nofollow but a followable link was expected.",
                    evidence={"rel": sorted(rel), "expected": ctx.expected_rel.value})

    if "sponsored" in rel:
        sev = Severity.INFO if ctx.policy.treat_sponsored_as_follow else Severity.HIGH
        yield issue(code="REL-03", label=IssueLabel.LINK_SPONSORED, category=CAT, severity=sev,
                    message="Link is rel=sponsored.",
                    evidence={"rel": sorted(rel), "policy_follow": ctx.policy.treat_sponsored_as_follow})  # noqa: E501

    if "ugc" in rel:
        sev = Severity.INFO if ctx.policy.treat_sponsored_as_follow else Severity.MEDIUM
        yield issue(code="REL-04", label=IssueLabel.LINK_UGC, category=CAT, severity=sev,
                    message="Link is rel=ugc (user-generated content).",
                    evidence={"rel": sorted(rel)})
