"""RDR-* — redirect-chain checks (PRD §8.6 C)."""

from __future__ import annotations

from typing import Iterable
from urllib.parse import urlsplit

from app.crawler.normalize import registrable_domain
from app.crawler.types import FetchError
from app.qa.checks._base import issue
from app.qa.enums import IssueCategory, IssueLabel, Severity
from app.qa.registry import check
from app.qa.types import CheckContext, Issue

CAT = IssueCategory.RDR


def _redirects(ctx: CheckContext) -> list:
    return [h for h in ctx.artifact.redirect_chain if h.location]


@check("RDR-03", CAT)
def redirect_loop(ctx: CheckContext) -> Iterable[Issue]:
    if ctx.artifact.fetch_error is FetchError.REDIRECT_LOOP:
        yield issue(code="RDR-03", label=IssueLabel.REDIRECT_LOOP, category=CAT,
                    severity=Severity.CRITICAL,
                    message="Redirect loop detected; the page is unreachable.",
                    evidence={"chain": [h.url for h in ctx.artifact.redirect_chain]})
    elif ctx.artifact.fetch_error is FetchError.TOO_MANY_REDIRECTS:
        yield issue(code="RDR-03b", label=IssueLabel.REDIRECT_CHAIN, category=CAT,
                    severity=Severity.HIGH,
                    message="Redirect chain exceeded the maximum allowed hops.",
                    evidence={"chain": [h.url for h in ctx.artifact.redirect_chain]})


@check("RDR-02", CAT)
def excessive_redirects(ctx: CheckContext) -> Iterable[Issue]:
    hops = _redirects(ctx)
    if len(hops) > ctx.policy.redirect_warn_threshold:
        yield issue(code="RDR-02", label=IssueLabel.REDIRECT_CHAIN, category=CAT,
                    severity=Severity.MEDIUM,
                    message=f"Redirect chain has {len(hops)} hops (> {ctx.policy.redirect_warn_threshold}).",  # noqa: E501
                    evidence={"hops": [{"url": h.url, "status": h.status} for h in hops]})


@check("RDR-05", CAT)
def https_downgrade(ctx: CheckContext) -> Iterable[Issue]:
    chain = ctx.artifact.redirect_chain
    for prev, nxt in zip(chain, chain[1:]):
        if prev.url.startswith("https://") and nxt.url.startswith("http://"):
            yield issue(code="RDR-05", label=IssueLabel.REDIRECT_CHAIN, category=CAT,
                        severity=Severity.HIGH,
                        message="Insecure HTTPS→HTTP downgrade in the redirect chain.",
                        evidence={"from": prev.url, "to": nxt.url})
            return


@check("RDR-04", CAT)
def https_upgrade(ctx: CheckContext) -> Iterable[Issue]:
    chain = ctx.artifact.redirect_chain
    for prev, nxt in zip(chain, chain[1:]):
        if prev.url.startswith("http://") and nxt.url.startswith("https://"):
            yield issue(code="RDR-04", label=IssueLabel.NONE, category=CAT,
                        severity=Severity.INFO,
                        message="HTTP→HTTPS upgrade (healthy).",
                        evidence={"from": prev.url, "to": nxt.url})
            return


@check("RDR-07", CAT)
def cross_domain_source(ctx: CheckContext) -> Iterable[Issue]:
    art = ctx.artifact
    if not _redirects(ctx) or not art.final_url:
        return
    start = art.redirect_chain[0].url
    start_dom = registrable_domain(urlsplit(start).hostname or "")
    final_dom = registrable_domain(urlsplit(art.final_url).hostname or "")
    if start_dom and final_dom and start_dom != final_dom:
        yield issue(code="RDR-07", label=IssueLabel.REDIRECT_CHAIN, category=CAT,
                    severity=Severity.HIGH,
                    message=f"Source page redirects cross-domain ({start_dom} → {final_dom}).",
                    recommendation="The source moved to another domain; verify the link still exists there.",  # noqa: E501
                    evidence={"from_domain": start_dom, "to_domain": final_dom})


@check("RDR-06", CAT)
def www_redirect(ctx: CheckContext) -> Iterable[Issue]:
    for prev, nxt in zip(ctx.artifact.redirect_chain, ctx.artifact.redirect_chain[1:]):
        ph, nh = urlsplit(prev.url).hostname or "", urlsplit(nxt.url).hostname or ""
        if ph.startswith("www.") != nh.startswith("www.") and ph.lstrip("www.") == nh.lstrip("www."):  # noqa: E501
            yield issue(code="RDR-06", label=IssueLabel.NONE, category=CAT, severity=Severity.INFO,
                        message="www/non-www canonicalization redirect present.",
                        evidence={"from": ph, "to": nh})
            return


@check("RDR-01", CAT)
def chain_recorded(ctx: CheckContext) -> Iterable[Issue]:
    hops = _redirects(ctx)
    has_temp = any(h.status in (302, 307) for h in hops)
    if has_temp:
        yield issue(code="RDR-11", label=IssueLabel.REDIRECT_CHAIN, category=CAT,
                    severity=Severity.MEDIUM,
                    message="Temporary (302/307) redirect on the source path; prefer a permanent (301/308) redirect for stable equity.",  # noqa: E501
                    evidence={"statuses": [h.status for h in hops]})
