"""PQ-* — page-quality signals (PRD §8.6 M). Secondary; rarely hard-fails."""

from __future__ import annotations

from typing import Iterable

from app.crawler.types import FetchError
from app.qa.checks._base import issue
from app.qa.enums import IssueCategory, IssueLabel, Severity
from app.qa.registry import check
from app.qa.types import CheckContext, Issue

CAT = IssueCategory.PQ


def _has_page(ctx: CheckContext) -> bool:
    art = ctx.artifact
    return (
        art.fetch_error is FetchError.NONE
        and art.http_status is not None
        and 200 <= art.http_status < 300
        and art.is_html
        and not art.detection.soft_404
    )


@check("PQ-01", CAT)
def title_missing(ctx: CheckContext) -> Iterable[Issue]:
    if _has_page(ctx) and not (ctx.artifact.signals.title or "").strip():
        yield issue(code="PQ-01", label=IssueLabel.NONE, category=CAT, severity=Severity.LOW,
                    message="Page has no <title> (quality signal).")


@check("PQ-03", CAT)
def thin_content(ctx: CheckContext) -> Iterable[Issue]:
    if not _has_page(ctx):
        return
    wc = ctx.artifact.signals.word_count
    if wc < ctx.policy.thin_content_words:
        yield issue(code="PQ-03", label=IssueLabel.NONE, category=CAT, severity=Severity.LOW,
                    message=f"Thin content ({wc} words < {ctx.policy.thin_content_words}); host page carries less value.",  # noqa: E501
                    evidence={"word_count": wc})


@check("PQ-04", CAT)
def excessive_outbound(ctx: CheckContext) -> Iterable[Issue]:
    if not _has_page(ctx):
        return
    n = ctx.artifact.signals.outbound_link_count
    if n > ctx.policy.excessive_outbound_links:
        yield issue(code="PQ-04", label=IssueLabel.TOO_MANY_OUTBOUND_LINKS, category=CAT,
                    severity=Severity.MEDIUM,
                    message=f"Excessive outbound links ({n} > {ctx.policy.excessive_outbound_links}); link-farm signal.",  # noqa: E501
                    evidence={"outbound_links": n})


# Regions that count as "on the page proper" (not header/nav/footer/sidebar ads).
_IN_SCOPE_REGIONS = frozenset({"content", "anchor", "link_context"})


def _spam_hit_region(hit: object) -> str:
    """Region of a hit, tolerating both the new dict shape and the legacy plain
    string shape (older persisted rows). Legacy strings carry no region → treat
    as 'content' so historical behavior (always in-scope) is preserved."""
    if isinstance(hit, dict):
        return hit.get("region") or "content"
    return "content"


def _spam_hit_keyword(hit: object) -> str:
    return hit.get("keyword", "") if isinstance(hit, dict) else str(hit)


@check("PQ-06", CAT)
def spam_neighborhood(ctx: CheckContext) -> Iterable[Issue]:
    if not _has_page(ctx) or not ctx.policy.spam_enabled:
        return
    hits = ctx.artifact.signals.spam_keyword_hits or []
    if not hits:
        return

    in_scope = [h for h in hits if _spam_hit_region(h) in _IN_SCOPE_REGIONS]
    keywords = [_spam_hit_keyword(h) for h in hits][:8]
    matches = [h for h in hits if isinstance(h, dict)][:8]

    # Gate: MEDIUM only when enough in-scope hits exist (or scope="page", where
    # any region counts). Boilerplate-only hits downgrade to LOW rather than a
    # silent −10; if scope="content" and the min isn't met, still surface LOW so
    # the reviewer sees the neighborhood signal without the penalty weight.
    if ctx.policy.spam_scope == "page":
        qualifies = len(hits) >= ctx.policy.spam_min_hits
    else:
        qualifies = len(in_scope) >= ctx.policy.spam_min_hits

    severity = Severity.MEDIUM if qualifies else Severity.LOW
    scope_note = "content" if in_scope else "boilerplate"
    if not qualifies:
        message = (
            "Spam keywords appear only in page boilerplate (nav/footer/sidebar); "
            "flagged for review, not penalised as main-content spam."
        )
    else:
        message = "Page contains adult/gambling/pharma/spam keywords (risky neighborhood)."

    yield issue(code="PQ-06", label=IssueLabel.NONE, category=CAT, severity=severity,
                message=message,
                recommendation="Review host suitability for the client's brand.",
                evidence={"keywords": keywords, "matches": matches, "scope": scope_note})
