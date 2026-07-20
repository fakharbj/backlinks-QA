"""QA engine entrypoint — ``evaluate(artifact, policy) -> QAResult``.

Orchestrates: run the check registry → compute composite followability/indexability
→ score deterministically → classify status → aggregate recommendations. Pure and
deterministic: the same artifact always yields the same verdict (Arch §4).
"""

from __future__ import annotations

from app.crawler.types import CrawlArtifact, FetchError
from app.qa.classification import classify
from app.qa.composite import compute_followability, compute_indexability
from app.qa.enums import (
    GradeBand,
    Indexability,
    IssueCategory,
    IssueLabel,
    OverallStatus,
    RelType,
    Severity,
)
from app.qa.recommendations import recommend
from app.qa.registry import load_checks, run_all
from app.qa.scoring import score_issues
from app.qa.scoring_rules import ResolvedRuleset
from app.qa.types import CheckContext, Issue, QAPolicy, QAResult

# Populate the registry once at import time.
load_checks()


def evaluate(
    artifact: CrawlArtifact,
    policy: QAPolicy | None = None,
    ruleset: ResolvedRuleset | None = None,
    signals: dict[str, str] | None = None,
) -> QAResult:
    """Render a verdict for one crawl.

    ``ruleset`` is the resolved (project→link_type→workspace→global) scoring rule
    set; when None the engine uses the legacy severity model and 30/80 bands, so
    behaviour is identical to pre-Phase-8. ``signals`` carries metric-parameter
    values (DA/Semrush/age/index/duplicate bands) the worker derived from the DB.
    """
    policy = policy or QAPolicy(
        treat_sponsored_as_follow=artifact.request.treat_sponsored_as_follow,
        trailing_slash_policy=artifact.request.trailing_slash_policy,
    )
    ctx = CheckContext(artifact=artifact, policy=policy)

    issues = run_all(ctx)

    followable = compute_followability(artifact, policy)
    indexable = compute_indexability(artifact, policy)

    # Surface an explicit INDEXABILITY_UNKNOWN issue when uncertainty is due to
    # bot protection (so the verdict becomes REVIEW, not a false negative).
    det = artifact.detection
    if indexable is Indexability.UNKNOWN and (
        det.captcha or det.cloudflare_challenge or det.waf_block
    ):
        issues.append(
            Issue(
                code="IDX-03",
                label=IssueLabel.INDEXABILITY_UNKNOWN,
                category=IssueCategory.IDX,
                severity=Severity.INFO,
                message="Indexability could not be determined (bot protection); manual review required.",  # noqa: E501
                recommendation=recommend(IssueLabel.INDEXABILITY_UNKNOWN),
            )
        )

    score, breakdown = score_issues(issues, ruleset=ruleset, signals=signals)
    status = classify(artifact, issues, score, bands=ruleset.bands if ruleset else None)
    grade = GradeBand.from_score(score)
    recommendations = _aggregate_recommendations(issues)
    top = _top_issue(issues)

    # "Unverified": we never actually READ the page (hard IP block, CAPTCHA/WAF
    # the browser couldn't clear, JS-only shell, robots-disallowed-and-unread)
    # AND the link was never confirmed. The score is then not evidence-based —
    # flag it so the UI can show "Not scored — couldn't check" (owner rule:
    # never auto-score what we couldn't see).
    read_direct = (
        artifact.fetch_error is FetchError.NONE
        and artifact.http_status is not None
        and 200 <= artifact.http_status < 300
        and artifact.is_html
        and not (
            artifact.detection.captcha
            or artifact.detection.cloudflare_challenge
            or artifact.detection.waf_block
        )
    )
    read_browser = artifact.found_in_rendered or (
        artifact.rendered and 200 <= (artifact.browser_http_status or 0) < 300
    )
    unverified = (
        status is OverallStatus.NEEDS_MANUAL_REVIEW
        and not artifact.link_found
        and not (read_direct or read_browser)
    )

    return QAResult(
        status=status,
        score=score,
        unverified=unverified,
        grade_band=grade,
        is_followable=followable,
        is_indexable=indexable,
        issues=issues,
        recommendations=recommendations,
        score_breakdown=breakdown,
        link_found=artifact.link_found,
        found_in_raw=artifact.found_in_raw,
        found_in_rendered=artifact.found_in_rendered,
        current_rel=_current_rel(artifact),
        current_anchor=(artifact.primary_link.effective_anchor if artifact.primary_link else None),
        http_status=artifact.http_status,
        final_url=artifact.final_url,
        canonical_status=_canonical_status(artifact, issues),
        robots_status=_robots_status(artifact),
        top_issue=top,
        scoring_rule_version_id=ruleset.version_id if ruleset else None,
    )


def _aggregate_recommendations(issues: list[Issue]) -> list[str]:
    """De-duplicate, severity-order recommendations for reports (PRD §8.17)."""
    seen: dict[str, Severity] = {}
    for iss in issues:
        if iss.recommendation:
            cur = seen.get(iss.recommendation)
            if cur is None or iss.severity.rank > cur.rank:
                seen[iss.recommendation] = iss.severity
    return [text for text, _ in sorted(seen.items(), key=lambda kv: -kv[1].rank)]


def _top_issue(issues: list[Issue]) -> Issue | None:
    actionable = [i for i in issues if i.severity is not Severity.INFO]
    if not actionable:
        return None
    return max(actionable, key=lambda i: i.severity.rank)


def _current_rel(artifact: CrawlArtifact) -> RelType | None:
    link = artifact.primary_link
    if link is None:
        return None
    rel = set(link.rel)
    if "nofollow" in rel:
        return RelType.NOFOLLOW
    if "sponsored" in rel:
        return RelType.SPONSORED
    if "ugc" in rel:
        return RelType.UGC
    return RelType.DOFOLLOW


def _canonical_status(artifact: CrawlArtifact, issues: list[Issue]) -> str | None:
    codes = {i.code for i in issues}
    if "CAN-04" in codes:
        return "cross_domain"
    if "CAN-03" in codes or "CAN-09" in codes or "CAN-10" in codes:
        return "mismatch"
    if "CAN-02" in codes:
        return "missing"
    if artifact.canonical_url:
        return "self"
    return None


def _robots_status(artifact: CrawlArtifact) -> str:
    if artifact.robots.source_allowed is False:
        return "blocked"
    if artifact.robots.source_allowed is True:
        return "allowed"
    return "unknown"
