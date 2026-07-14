"""HTTP-* — HTTP status checks (PRD §8.6 B)."""

from __future__ import annotations

from typing import Iterable

from app.crawler.types import FetchError
from app.qa.checks._base import issue
from app.qa.enums import IssueCategory, IssueLabel, Severity
from app.qa.registry import check
from app.qa.types import CheckContext, Issue

CAT = IssueCategory.HTTP


def _final_status(ctx: CheckContext) -> int | None:
    return ctx.artifact.http_status


@check("HTTP-4xx-5xx", CAT)
def status_errors(ctx: CheckContext) -> Iterable[Issue]:
    art = ctx.artifact
    if art.fetch_error not in (FetchError.NONE, FetchError.TOO_LARGE):
        return  # transport never produced a status → NET-*/RDR-* own it
    status = _final_status(ctx)
    if status is None:
        return
    ev = {"http_status": status, "final_url": art.final_url}

    # BROWSER-VERIFIED override (Enterprise accuracy): the raw request was
    # blocked (403/429/…), but the headless browser loaded the page AND found
    # the link. That means the page is live for real users and the block only
    # applies to automated requests — say exactly that, with no penalty,
    # instead of a scary raw status code.
    if (
        400 <= status < 500
        and art.found_in_rendered
        and art.matched_links
    ):
        yield issue(
            code="HTTP-BROWSER-OK", label=IssueLabel.NONE, category=CAT,
            severity=Severity.INFO,
            message=(
                f"The site blocks automated requests (HTTP {status}) but the page opens "
                f"normally in a real browser — we verified the link in a rendered browser "
                f"session"
                + (f" (browser saw HTTP {art.browser_http_status})." if art.browser_http_status else ".")
            ),
            evidence={**ev, "browser_http_status": art.browser_http_status,
                      "verified_via": "headless_browser"},
        )
        return

    if status == 404:
        yield issue(code="HTTP-404", label=IssueLabel.SOURCE_404, category=CAT,
                    severity=Severity.CRITICAL,
                    message="Source page returns 404 Not Found; the backlink is lost.", evidence=ev)
    elif status == 410:
        yield issue(code="HTTP-410", label=IssueLabel.SOURCE_404, category=CAT,
                    severity=Severity.CRITICAL,
                    message="Source page returns 410 Gone; permanently removed.", evidence=ev)
    elif status == 403:
        if art.rendered and (art.browser_http_status or 0) >= 400:
            # We tried BOTH an automated request and a real headless browser from
            # our servers — the site blocks our network entirely (IP-level bot
            # protection). The page very likely still opens for real visitors.
            yield issue(code="HTTP-403", label=IssueLabel.SOURCE_403, category=CAT,
                        severity=Severity.HIGH,
                        message=(
                            "The site blocks our checker's network entirely: an automated "
                            f"request AND a real browser from our servers both got HTTP {status} "
                            "(IP-level bot protection). The page most likely still opens fine "
                            "for real visitors — open it once in your own browser to confirm."
                        ),
                        evidence={**ev, "browser_http_status": art.browser_http_status,
                                  "browser_also_blocked": True})
        else:
            yield issue(code="HTTP-403", label=IssueLabel.SOURCE_403, category=CAT,
                        severity=Severity.HIGH,
                        message="Source page returns 403 Forbidden (often WAF/bot rules).", evidence=ev)
    elif status == 401:
        yield issue(code="HTTP-401", label=IssueLabel.HTTP_ERROR, category=CAT,
                    severity=Severity.HIGH,
                    message="Source page returns 401 Unauthorized; login-gated and not publicly indexable.",  # noqa: E501
                    evidence=ev)
    elif status == 400:
        yield issue(code="HTTP-400", label=IssueLabel.HTTP_ERROR, category=CAT,
                    severity=Severity.HIGH,
                    message="Source page returns 400 Bad Request.", evidence=ev)
    elif status == 429:
        yield issue(code="HTTP-429", label=IssueLabel.HTTP_ERROR, category=CAT,
                    severity=Severity.MEDIUM,
                    message="We were rate-limited (429). Backing off and rechecking.", evidence=ev)
    elif status in (500, 502):
        yield issue(code=f"HTTP-{status}", label=IssueLabel.SOURCE_5XX, category=CAT,
                    severity=Severity.CRITICAL,
                    message=f"Source page returns {status} server error.", evidence=ev)
    elif status in (503, 504):
        yield issue(code=f"HTTP-{status}", label=IssueLabel.SOURCE_5XX, category=CAT,
                    severity=Severity.HIGH,
                    message=f"Source page returns {status}; often transient. Rechecking on schedule.",  # noqa: E501
                    evidence=ev)
    elif 500 <= status < 600:
        yield issue(code="HTTP-5XX", label=IssueLabel.SOURCE_5XX, category=CAT,
                    severity=Severity.HIGH,
                    message=f"Source page returns server error {status}.", evidence=ev)
    elif 400 <= status < 500:
        yield issue(code="HTTP-4XX", label=IssueLabel.HTTP_ERROR, category=CAT,
                    severity=Severity.HIGH,
                    message=f"Source page returns client error {status}.", evidence=ev)
