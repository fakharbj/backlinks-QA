"""XR-* — X-Robots-Tag header checks (PRD §8.6 H).

Headers and meta combine; the most-restrictive wins (handled here + in composite).
"""

from __future__ import annotations

from typing import Iterable

from app.qa.checks._base import issue
from app.qa.enums import IssueCategory, IssueLabel, Severity
from app.qa.registry import check
from app.qa.types import CheckContext, Issue

CAT = IssueCategory.XR


@check("XR-eval", CAT)
def x_robots(ctx: CheckContext) -> Iterable[Issue]:
    xr = ctx.artifact.x_robots
    if not xr.raw:
        return
    index_expected = ctx.policy.index_expected
    ev = {"x_robots_tag": xr.raw}

    if xr.none:
        yield issue(code="XR-03", label=IssueLabel.X_ROBOTS_NOINDEX, category=CAT,
                    severity=Severity.CRITICAL,
                    message="X-Robots-Tag 'none' (noindex,nofollow) at the header level.", evidence=ev)
        return

    if xr.noindex:
        yield issue(code="XR-01", label=IssueLabel.X_ROBOTS_NOINDEX, category=CAT,
                    severity=Severity.CRITICAL if index_expected else Severity.MEDIUM,
                    message="X-Robots-Tag header sets noindex.", evidence=ev)
    if xr.nofollow:
        yield issue(code="XR-02", label=IssueLabel.X_ROBOTS_NOFOLLOW, category=CAT,
                    severity=Severity.HIGH,
                    message="X-Robots-Tag header sets nofollow — no link passes equity.", evidence=ev)

    gb = xr.ua_specific.get("googlebot", "")
    if "noindex" in gb or "none" in gb:
        yield issue(code="XR-04", label=IssueLabel.X_ROBOTS_NOINDEX, category=CAT,
                    severity=Severity.CRITICAL if index_expected else Severity.MEDIUM,
                    message="Googlebot-specific X-Robots-Tag sets noindex.", evidence={"googlebot": gb})

    if xr.conflicting:
        yield issue(code="XR-05", label=IssueLabel.NONE, category=CAT, severity=Severity.MEDIUM,
                    message="Conflicting X-Robots-Tag values; most restrictive applies.",
                    recommendation="Ask the publisher to fix the conflicting header.", evidence=ev)
