"""Check registry.

Each check is a pure function ``(CheckContext) -> Iterable[Issue]`` registered with
``@check``. The engine runs the full registry in a stable order and aggregates the
emitted issues. Checks are independent and defensive — a check that doesn't apply
to the current artifact simply yields nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable

from app.qa.enums import IssueCategory
from app.qa.types import CheckContext, Issue

CheckFn = Callable[[CheckContext], Iterable[Issue]]


@dataclass(slots=True)
class RegisteredCheck:
    code: str
    category: IssueCategory
    fn: CheckFn
    order: int


CHECK_REGISTRY: list[RegisteredCheck] = []

# Category execution order mirrors the crawl pipeline (transport → page → content).
_CATEGORY_ORDER = {
    IssueCategory.NET: 0,
    IssueCategory.HTTP: 1,
    IssueCategory.RDR: 2,
    IssueCategory.BOT: 3,
    IssueCategory.CT: 4,
    IssueCategory.RBT: 5,
    IssueCategory.LNK: 6,
    IssueCategory.ANC: 7,
    IssueCategory.REL: 8,
    IssueCategory.MR: 9,
    IssueCategory.XR: 10,
    IssueCategory.CAN: 11,
    IssueCategory.PQ: 12,
    IssueCategory.IDX: 13,
}


def check(code: str, category: IssueCategory):
    """Register a check function under ``code`` within ``category``."""

    def _decorator(fn: CheckFn) -> CheckFn:
        CHECK_REGISTRY.append(
            RegisteredCheck(
                code=code,
                category=category,
                fn=fn,
                order=_CATEGORY_ORDER.get(category, 99),
            )
        )
        return fn

    return _decorator


def run_all(ctx: CheckContext) -> list[Issue]:
    """Execute every registered check; never let one check's bug fail the batch."""
    issues: list[Issue] = []
    for registered in sorted(CHECK_REGISTRY, key=lambda r: (r.order, r.code)):
        try:
            produced = registered.fn(ctx)
        except Exception as exc:  # noqa: BLE001 - isolation: a buggy check can't nuke a verdict
            from app.core.logging import get_logger

            get_logger("qa").warning("check_failed", code=registered.code, error=repr(exc))
            continue
        if produced:
            issues.extend(produced)
    return issues


def load_checks() -> None:
    """Import every check module so their ``@check`` decorators run (idempotent)."""
    from app.qa.checks import (  # noqa: F401
        anchor,
        bot_protection,
        canonical,
        content_type,
        http_status,
        links,
        meta_robots,
        network,
        page_quality,
        redirects,
        rel,
        robots_txt,
        x_robots,
    )
