"""Temp QA lab scoring lens (owner rule) — SEO-outcome focused.

The production QA score answers "how healthy is this link overall" and folds in
signals that matter at scale (canonical, content quality, link placement, our
render limits). The candidate-evaluation lab needs a SIMPLER, blunter question:
**is this a real, valuable backlink to the target?** So the lab re-derives the
verdict from the engine's findings with a deliberately narrow, SEO-material
rule set:

* If we could not actually READ the page (hard block / CAPTCHA / JS-only) →
  ``NEEDS_MANUAL_REVIEW`` with **no score** ("couldn't check — verify by hand").
  Never a misleading number.
* Page gone (404/410) → ``FAIL`` score 0 (the backlink is lost).
* Readable 200 but the link is absent → ``FAIL`` score 0 (missing).
* Link present but nofollow AND the page is noindex → ``FAIL`` score 0
  (passes no SEO value and won't be indexed).
* Otherwise score from 100 down for ONLY the deductions that change a link's
  real SEO value (nofollow, noindex, hidden, wrong target, sponsored/ugc,
  link-farm, spam neighborhood).

Explicitly EXCLUDED from the lab (owner call): canonical checks (CAN-*), the
JS-render note (it's our crawler limitation, not an SEO defect), thin content,
missing <title>, link placement/sidebar, and normalization-only matches.
"""

from __future__ import annotations

from app.crawler.types import CrawlArtifact, FetchError
from app.qa.enums import IssueLabel, OverallStatus
from app.qa.types import QAResult

# SEO-material deductions ONLY, keyed by issue label. (label, points, why).
_DEDUCTIONS: list[tuple[IssueLabel, int, str]] = [
    (IssueLabel.LINK_HIDDEN, 70, "The link is hidden (display:none / 0-size / off-screen) — it passes no value and looks manipulative."),
    (IssueLabel.WRONG_TARGET, 45, "Links to the target's domain but NOT the agreed URL."),
    (IssueLabel.TOO_MANY_OUTBOUND_LINKS, 20, "The page has an excessive number of outbound links (link-farm signal)."),
    (IssueLabel.LINK_SPONSORED, 25, "The link is rel=sponsored — search engines treat it as an ad, not editorial."),
    (IssueLabel.LINK_UGC, 20, "The link is rel=ugc (user-generated) — search engines discount it."),
]
# nofollow / noindex are scored together (with the both→0 rule) below.
_NOFOLLOW = {IssueLabel.LINK_NOFOLLOW, IssueLabel.PAGE_NOFOLLOW, IssueLabel.X_ROBOTS_NOFOLLOW}
_NOINDEX = {IssueLabel.PAGE_NOINDEX, IssueLabel.X_ROBOTS_NOINDEX}


def _readable(art: CrawlArtifact, result: QAResult) -> bool:
    """Did we actually read a real page — a 2xx HTML body directly, or via the
    headless browser? (A 4xx/5xx/blocked/captcha response is NOT 'read'.)"""
    det = art.detection
    direct = (
        art.fetch_error is FetchError.NONE
        and art.http_status is not None
        and 200 <= art.http_status < 300
        and art.is_html
        and not (det.captcha or det.cloudflare_challenge or det.waf_block or det.soft_404)
    )
    browser = art.found_in_rendered or (
        art.rendered and 200 <= (art.browser_http_status or 0) < 300
    )
    return bool(direct or browser)


def lab_verdict(art: CrawlArtifact, result: QAResult) -> dict:
    """Return the lab's SEO-focused verdict for one candidate link.

    ``{status, score (int|None), link_found (bool), indexable (bool|None),
    followable (bool|None), reasons: [{severity, text}], summary}``.
    """
    labels = {i.label for i in result.issues if i.label is not IssueLabel.NONE}
    reasons: list[dict] = []

    def out(status: OverallStatus, score, summary: str) -> dict:
        return {
            "status": status.value,
            "score": score,
            "link_found": bool(result.link_found),
            "indexable": None if score is None else (not (labels & _NOINDEX)),
            "followable": None if score is None else (not (labels & _NOFOLLOW)),
            "reasons": reasons,
            "summary": summary,
        }

    # 1) Page gone → the backlink is lost. Confident FAIL, 0.
    if art.http_status in (404, 410):
        reasons.append({"severity": "critical",
                        "text": f"Source page returns HTTP {art.http_status} — the page is gone, so the backlink is lost."})
        return out(OverallStatus.FAIL, 0, "Page not found — the backlink is lost.")

    # 1b) The page redirected to a LOGIN / sign-in wall → it isn't publicly
    #     accessible, so search engines can't see the link either. Clear FAIL 0.
    final = (art.final_url or "").lower()
    if not result.link_found and any(
        seg in final for seg in ("/signin", "/sign-in", "/login", "/m/signin", "/auth/login", "accounts/login")
    ):
        reasons.append({"severity": "critical",
                        "text": f"The page redirects to a login/sign-in wall ({art.final_url}) — it isn't publicly "
                                "accessible, so search engines can't see or credit the link."})
        return out(OverallStatus.FAIL, 0, "Redirects to a login page — not publicly accessible.")

    # 2) Couldn't read the page (block / captcha / JS-only). No evidence → no
    #    score. NEVER "link missing", never a number.
    if not _readable(art, result) or (not result.link_found and art.js_render_suspected):
        why = "This page couldn't be read automatically"
        if art.http_status and art.http_status >= 400:
            why = f"The page blocked our checker (HTTP {art.http_status}) — even a real browser from our servers couldn't load it"
        elif art.detection.captcha or art.detection.cloudflare_challenge or art.detection.waf_block:
            why = "The page is behind a CAPTCHA / bot-challenge our checker couldn't clear"
        elif art.js_render_suspected:
            why = "The page builds its content with JavaScript, so links added in the body may not be visible to our checker"
        reasons.append({"severity": "info",
                        "text": f"{why}. Open the URL in your own browser to confirm the link by hand."})
        return out(OverallStatus.NEEDS_MANUAL_REVIEW, None, "Couldn't check automatically — verify by hand.")

    # ── From here the page WAS read. ────────────────────────────────────────
    # 3) Link absent on a readable page → confident FAIL, 0. Say plainly HOW we
    #    read it, so "not found" is trustworthy (esp. after a full JS render).
    if not result.link_found:
        rendered_full = art.rendered and 200 <= (art.browser_http_status or art.http_status or 0) < 300
        how = (
            "We fully loaded the page in a real browser (including its JavaScript)"
            if rendered_full else "The page loaded (HTTP 200)"
        )
        final = art.final_url or art.request.source_url
        redirected = final and final.rstrip("/") != art.request.source_url.rstrip("/")
        if IssueLabel.WRONG_TARGET in labels:
            reasons.append({"severity": "critical",
                            "text": f"{how}. A link to the target's domain exists, but it points to a different URL, not the agreed target."})
            return out(OverallStatus.FAIL, 0, "Wrong target URL — the agreed link is not on the page.")
        reasons.append({"severity": "critical",
                        "text": f"{how}"
                                + (f" (it redirected to {final})" if redirected else "")
                                + ", but the backlink to the target is not on it."})
        return out(OverallStatus.FAIL, 0, "Link not found on the page.")

    # 4) Link is present. Score by SEO value.
    nofollow = bool(labels & _NOFOLLOW) or result.is_followable is False
    noindex = bool(labels & _NOINDEX)
    if nofollow and noindex:
        reasons.append({"severity": "critical",
                        "text": "The link is nofollow AND the page is set to noindex — it passes no ranking value and the page won't be indexed."})
        return out(OverallStatus.FAIL, 0, "Nofollow + noindex — the link passes no SEO value.")

    score = 100
    if nofollow:
        score -= 55
        reasons.append({"severity": "high",
                        "text": "The link is nofollow — it passes little/no ranking value to the target."})
    if noindex:
        score -= 55
        reasons.append({"severity": "high",
                        "text": "The page is set to noindex — search engines won't index it, so the backlink isn't counted."})
    for lbl, pts, why in _DEDUCTIONS:
        if lbl in labels:
            score -= pts
            reasons.append({"severity": "high" if pts >= 40 else "medium", "text": why})

    score = max(0, min(100, score))
    if not reasons:
        reasons.append({"severity": "info", "text": "Link found, dofollow, on an indexable page — a clean backlink."})

    if score >= 80:
        status = OverallStatus.PASS
        summary = "Clean, valuable backlink."
    elif score >= 40:
        status = OverallStatus.WARNING
        summary = "Link is there but with SEO caveats — see reasons."
    else:
        status = OverallStatus.FAIL
        summary = "Link is there but passes little SEO value."
    return out(status, score, summary)
