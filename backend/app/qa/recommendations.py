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


# ── Score-breakdown explainability (enrich-on-read) ──────────────────────────
# "How to improve" text for METRIC-parameter steps (DA/AS/age/index/duplicate) —
# these aren't QA issues, so they have no IssueLabel recommendation of their own.
PARAM_REMEDIATION: dict[str, str] = {
    "da_band": "Prefer placements on higher-DA domains; run a DA/PA metrics check so the value is known.",
    "semrush_as_band": "Prefer placements on higher Authority Score domains; run an AS metrics check so the value is known.",  # noqa: E501
    "domain_age_band": "Older, established domains score better. Prefer aged domains for placements.",
    "external_index": "Get the source page indexed (internal links / sitemap / share it) and run an index check.",  # noqa: E501
    "duplicate": "Same source URL used more than once — place each link on a distinct page.",
}


def enrich_breakdown(steps: list[dict], issues: list | None = None) -> list[dict]:
    """Attach ``impact`` (points lost, ≥0), ``reason`` and ``recommendation`` to stored
    ScoreStep dicts and order them for humans: baseline first, then biggest deduction
    → smallest, then gains, cap last. Pure + tolerant of old rows lacking new keys;
    the stored JSONB is never mutated (copies only)."""
    by_code: dict[str, object] = {}
    for iss in issues or []:
        by_code.setdefault(getattr(iss, "code", ""), iss)

    def _rec(step: dict) -> str | None:
        src = step.get("source") or "severity"
        if src == "metric_signal":
            return PARAM_REMEDIATION.get(step.get("parameter_key") or "")
        if src == "cap":
            code = (step.get("code") or "").strip()
            return f"Fix the blocking issue ({code}) to lift the score ceiling." if code else None
        iss = by_code.get(step.get("code") or "")
        if iss is not None:
            rec = getattr(iss, "recommendation", None)
            if rec:
                return rec
            label = getattr(iss, "label", None)
            if label is not None:
                return RECOMMENDATIONS.get(label)
        # Fall back to the label registry via the stored note (label.value for issues).
        note = step.get("note") or ""
        try:
            return RECOMMENDATIONS.get(IssueLabel(note))
        except ValueError:
            return None

    out: list[dict] = []
    for s in steps or []:
        s2 = dict(s)
        delta = int(s2.get("delta") or 0)
        s2["impact"] = max(0, -delta)
        s2["reason"] = s2.get("outcome_label") or s2.get("note") or s2.get("code")
        rec = _rec(s2)
        if rec and delta < 0:
            s2["recommendation"] = rec
        out.append(s2)

    def _rank(s: dict) -> tuple[int, int]:
        if s.get("code") == "START":
            return (0, 0)
        if (s.get("source") or "") == "cap" or s.get("cap_applied") is not None:
            return (3, 0)
        d = int(s.get("delta") or 0)
        if d < 0:
            return (1, d)          # deductions: most negative (biggest loss) first
        return (2, -d)             # gains after deductions, biggest first
    out.sort(key=_rank)
    return out
