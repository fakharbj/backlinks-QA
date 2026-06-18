"""Composite SEO reasoning (PRD §8.7): ``is_followable_link`` and ``is_indexable``.

These two booleans are the platform's core judgement. They deliberately return
**UNKNOWN** (not False) when the answer can't be determined (CAPTCHA/WAF/JS
inconclusive) so the link is routed to manual review rather than a false FAIL.
"""

from __future__ import annotations

from app.crawler.types import CrawlArtifact, FetchError
from app.qa.enums import Indexability
from app.qa.types import QAPolicy

_TRANSIENT = (FetchError.TIMEOUT, FetchError.CONNECTION, FetchError.UNKNOWN)


def _is_unknown(artifact: CrawlArtifact) -> bool:
    det = artifact.detection
    if det.captcha or det.cloudflare_challenge or det.waf_block:
        return True
    return artifact.fetch_error in _TRANSIENT


def compute_followability(artifact: CrawlArtifact, policy: QAPolicy) -> bool | None:
    """True/False, or None when undeterminable (→ manual review)."""
    if _is_unknown(artifact):
        return None

    # Page unreachable / error → the link can't pass value.
    if artifact.fetch_error is not FetchError.NONE:
        return False
    if artifact.http_status is None or not (200 <= artifact.http_status < 300):
        return False
    if not artifact.is_html:
        return False
    if artifact.detection.soft_404 or artifact.detection.empty_page or artifact.detection.parked:
        return False

    # Source must be crawlable.
    if artifact.robots.source_allowed is False:
        return False
    # Page-level nofollow kills following of every link.
    if artifact.meta_robots.nofollow or artifact.x_robots.nofollow:
        return False

    link = artifact.primary_link
    if link is None:
        return False  # link absent → not followable
    rel = set(link.rel)
    if "nofollow" in rel:
        return False
    if not policy.treat_sponsored_as_follow and (rel & {"sponsored", "ugc"}):
        return False
    # Hidden links pass little/no value.
    if link.in_comment or link.in_iframe or link.css_hidden:
        return False
    return True


def compute_indexability(artifact: CrawlArtifact, policy: QAPolicy) -> Indexability:
    if _is_unknown(artifact):
        return Indexability.UNKNOWN

    if artifact.fetch_error is not FetchError.NONE:
        return Indexability.NOT_INDEXABLE
    if artifact.http_status is None or not (200 <= artifact.http_status < 300):
        return Indexability.NOT_INDEXABLE
    if not artifact.is_html:
        return Indexability.NOT_INDEXABLE

    blockers = (
        artifact.robots.source_allowed is False,
        artifact.meta_robots.noindex,
        artifact.x_robots.noindex,
        artifact.detection.soft_404,
        artifact.detection.empty_page,
        artifact.detection.parked,
        _canonical_cross_domain(artifact),
    )
    if any(blockers):
        return Indexability.NOT_INDEXABLE
    return Indexability.INDEXABLE


def _canonical_cross_domain(artifact: CrawlArtifact) -> bool:
    from urllib.parse import urlsplit

    from app.crawler.normalize import normalize_url, registrable_domain

    if not artifact.canonical_resolved or not artifact.final_url:
        return False
    final_norm = normalize_url(artifact.final_url).normalized
    src = registrable_domain(urlsplit(final_norm).hostname or "")
    can = registrable_domain(urlsplit(artifact.canonical_resolved).hostname or "")
    return bool(src and can and src != can)
