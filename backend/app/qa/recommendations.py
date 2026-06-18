"""Deterministic recommendation templates (PRD §8.17).

A single source of truth mapping issue labels to client-defensible, actionable
guidance. Checks pass specifics through ``message``; this gives the standing
recommendation text, de-duplicated and severity-ordered for reports.
"""

from __future__ import annotations

from app.qa.enums import IssueLabel

RECOMMENDATIONS: dict[IssueLabel, str] = {
    IssueLabel.LINK_MISSING: "Ask the publisher to restore the agreed backlink.",
    IssueLabel.LINK_NOFOLLOW: "Request removal of rel=nofollow per the agreement so the link passes equity.",  # noqa: E501
    IssueLabel.LINK_SPONSORED: "Link is marked rel=sponsored. Expected for paid placements; if an editorial link was agreed, request the change.",  # noqa: E501
    IssueLabel.LINK_UGC: "Link is marked rel=ugc (comment/user-generated). Confirm the placement type matches the agreement.",  # noqa: E501
    IssueLabel.LINK_HIDDEN: "Link is hidden (CSS/comment/iframe/noscript) and passes little or no value. Request a visible, in-content placement.",  # noqa: E501
    IssueLabel.PAGE_NOINDEX: "Page is noindex, so it won't pass SEO value long-term. Request an indexable placement.",  # noqa: E501
    IssueLabel.PAGE_NOFOLLOW: "Page-level nofollow stops crawlers following any link. Request its removal.",
    IssueLabel.X_ROBOTS_NOINDEX: "X-Robots-Tag header sets noindex; the page won't be indexed. Request removal of the header directive.",  # noqa: E501
    IssueLabel.X_ROBOTS_NOFOLLOW: "X-Robots-Tag header sets nofollow; links pass no equity. Request removal.",
    IssueLabel.ROBOTS_BLOCKED: "Search engines can't crawl this page (robots.txt disallow). Request an unblock.",
    IssueLabel.CANONICAL_MISMATCH: "Equity consolidates to the canonical URL. Ensure the canonical page also hosts/credits the link.",  # noqa: E501
    IssueLabel.CANONICAL_CROSS_DOMAIN: "Canonical points to another domain, so equity leaves this site entirely. Escalate with the publisher.",  # noqa: E501
    IssueLabel.SOURCE_404: "Backlink is lost unless the page is restored. Ask the publisher to restore the URL or 301 it to an equivalent page.",  # noqa: E501
    IssueLabel.SOURCE_403: "Access is blocked (often WAF/bot rules). Verify manually; the page may still be live for real users.",  # noqa: E501
    IssueLabel.SOURCE_5XX: "Server error on the source page. Recheck; if persistent, treat the link as down and escalate.",  # noqa: E501
    IssueLabel.REDIRECT_CHAIN: "Verify the final destination still hosts the link and reduce the number of redirect hops.",  # noqa: E501
    IssueLabel.REDIRECT_LOOP: "Redirect loop makes the page unreachable. Ask the publisher to fix the loop.",
    IssueLabel.WRONG_TARGET: "Link points to a URL other than the agreed target. Request a correction.",
    IssueLabel.ANCHOR_CHANGED: "Anchor text differs from the agreement. Request the original anchor if it is contractual.",  # noqa: E501
    IssueLabel.HTTP_ERROR: "Inspect the HTTP status and verify the page's availability.",
    IssueLabel.SSL_ERROR: "TLS/HTTPS is broken; users and crawlers can't reach the page. Ask the publisher to fix HTTPS.",  # noqa: E501
    IssueLabel.TIMEOUT: "Host was slow/unreachable. Recheck later; if persistent, treat the link as down.",
    IssueLabel.DNS_ERROR: "Domain did not resolve — it may be expired or parked. Confirm domain status; the link is effectively lost.",  # noqa: E501
    IssueLabel.SOFT_404: "Page returns 200 but is effectively a 'not found'/parked page. Treat as lost and seek a replacement placement.",  # noqa: E501
    IssueLabel.CAPTCHA_DETECTED: "Page is behind CAPTCHA/bot protection. We do not bypass it — manual verification is required.",  # noqa: E501
    IssueLabel.JS_RENDER_REQUIRED: "Link is only present after JavaScript rendering. Search engines may under-credit it; request a server-rendered link.",  # noqa: E501
    IssueLabel.TOO_MANY_OUTBOUND_LINKS: "Page has an excessive number of outbound links (link-farm signal). Review host quality.",  # noqa: E501
    IssueLabel.INDEXABILITY_UNKNOWN: "Indexability could not be determined automatically. Manual verification required.",  # noqa: E501
}


def recommend(label: IssueLabel) -> str | None:
    return RECOMMENDATIONS.get(label)
