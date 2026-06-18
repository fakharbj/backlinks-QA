"""NET-* — network / transport checks (PRD §8.6 A)."""

from __future__ import annotations

from typing import Iterable

from app.crawler.types import FetchError
from app.qa.checks._base import issue
from app.qa.enums import IssueCategory, IssueLabel, Severity
from app.qa.registry import check
from app.qa.types import CheckContext, Issue

CAT = IssueCategory.NET


@check("NET-01", CAT)
def dns_failure(ctx: CheckContext) -> Iterable[Issue]:
    if ctx.artifact.fetch_error is FetchError.DNS:
        yield issue(
            code="NET-01",
            label=IssueLabel.DNS_ERROR,
            category=CAT,
            severity=Severity.CRITICAL,
            message="DNS resolution failed — the domain may be expired or parked.",
            evidence={"detail": ctx.artifact.fetch_error_detail},
        )


@check("NET-02", CAT)
def connection_timeout(ctx: CheckContext) -> Iterable[Issue]:
    if ctx.artifact.fetch_error is FetchError.TIMEOUT:
        # HIGH→UNKNOWN: the classifier downgrades a no-prior-data timeout to UNKNOWN.
        yield issue(
            code="NET-02",
            label=IssueLabel.TIMEOUT,
            category=CAT,
            severity=Severity.HIGH,
            message="Connection/read timed out after retries; host slow or unreachable.",
            evidence={"detail": ctx.artifact.fetch_error_detail},
        )


@check("NET-03", CAT)
def ssl_error(ctx: CheckContext) -> Iterable[Issue]:
    if ctx.artifact.fetch_error is FetchError.SSL:
        yield issue(
            code="NET-03",
            label=IssueLabel.SSL_ERROR,
            category=CAT,
            severity=Severity.CRITICAL,
            message="SSL/TLS handshake or certificate error; users and crawlers can't reach the page.",  # noqa: E501
            evidence={"detail": ctx.artifact.fetch_error_detail},
        )


@check("NET-05", CAT)
def connection_reset(ctx: CheckContext) -> Iterable[Issue]:
    if ctx.artifact.fetch_error is FetchError.CONNECTION:
        yield issue(
            code="NET-05",
            label=IssueLabel.HTTP_ERROR,
            category=CAT,
            severity=Severity.HIGH,
            message="Connection reset or refused — possible firewall/WAF. Verify manually.",
            evidence={"detail": ctx.artifact.fetch_error_detail},
        )


@check("NET-06", CAT)
def unknown_network_error(ctx: CheckContext) -> Iterable[Issue]:
    err = ctx.artifact.fetch_error
    if err is FetchError.UNKNOWN:
        yield issue(
            code="NET-06",
            label=IssueLabel.HTTP_ERROR,
            category=CAT,
            severity=Severity.MEDIUM,
            message="Unknown network error; will auto-retry on schedule.",
            evidence={"detail": ctx.artifact.fetch_error_detail},
        )
    elif err is FetchError.TOO_LARGE:
        yield issue(
            code="NET-06",
            label=IssueLabel.HTTP_ERROR,
            category=CAT,
            severity=Severity.MEDIUM,
            message="Response exceeded the maximum allowed size and was truncated.",
            evidence={"detail": ctx.artifact.fetch_error_detail},
        )


@check("NET-07", CAT)
def ssrf_blocked(ctx: CheckContext) -> Iterable[Issue]:
    if ctx.artifact.fetch_error is FetchError.BLOCKED_SSRF:
        yield issue(
            code="NET-07",
            label=IssueLabel.HTTP_ERROR,
            category=CAT,
            severity=Severity.HIGH,
            message="Crawl blocked: the URL resolved to a private/reserved address (SSRF guard).",  # noqa: E501
            recommendation="Verify the source URL is a public web page.",
            evidence={"detail": ctx.artifact.fetch_error_detail},
        )
