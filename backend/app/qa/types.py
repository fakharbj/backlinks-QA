"""QA value objects: ``Issue``, ``ScoreStep``, ``QAResult``, ``CheckContext``, ``QAPolicy``.

All framework-free dataclasses. ``Issue`` is the atom every check emits; ``QAResult``
is the explainable verdict the rest of the system persists and renders.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.crawler.types import CrawlArtifact
from app.qa.enums import (
    GradeBand,
    Indexability,
    IssueCategory,
    IssueLabel,
    OverallStatus,
    RelType,
    Severity,
)


@dataclass(slots=True)
class Issue:
    code: str                      # e.g. "HTTP-404"
    label: IssueLabel
    category: IssueCategory
    severity: Severity
    message: str
    recommendation: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "label": self.label.value,
            "category": self.category.value,
            "severity": self.severity.value,
            "message": self.message,
            "recommendation": self.recommendation,
            "evidence": self.evidence,
        }


@dataclass(slots=True)
class ScoreStep:
    code: str
    severity: Severity
    delta: int = 0
    cap_applied: int | None = None
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity.value,
            "delta": self.delta,
            "cap_applied": self.cap_applied,
            "note": self.note,
        }


@dataclass(slots=True)
class QAResult:
    status: OverallStatus
    score: int
    grade_band: GradeBand
    is_followable: bool | None
    is_indexable: Indexability
    issues: list[Issue] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    score_breakdown: list[ScoreStep] = field(default_factory=list)

    # Denormalised observed fields (for the grid / record update).
    link_found: bool = False
    found_in_raw: bool = False
    found_in_rendered: bool = False
    current_rel: RelType | None = None
    current_anchor: str | None = None
    http_status: int | None = None
    final_url: str | None = None
    canonical_status: str | None = None
    robots_status: str | None = None
    top_issue: Issue | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "score": self.score,
            "grade_band": self.grade_band.value,
            "is_followable": self.is_followable,
            "is_indexable": self.is_indexable.value,
            "issues": [i.to_dict() for i in self.issues],
            "recommendations": self.recommendations,
            "score_breakdown": [s.to_dict() for s in self.score_breakdown],
            "link_found": self.link_found,
            "found_in_raw": self.found_in_raw,
            "found_in_rendered": self.found_in_rendered,
            "current_rel": self.current_rel.value if self.current_rel else None,
            "current_anchor": self.current_anchor,
            "http_status": self.http_status,
            "final_url": self.final_url,
            "canonical_status": self.canonical_status,
            "robots_status": self.robots_status,
        }


@dataclass(slots=True)
class QAPolicy:
    """Tunables + expectations that influence severities (PRD §8.6 policy hooks)."""

    treat_sponsored_as_follow: bool = True
    index_expected: bool = True
    thin_content_words: int = 250
    excessive_outbound_links: int = 100
    redirect_warn_threshold: int = 3
    trailing_slash_policy: str = "lenient"

    @classmethod
    def from_settings(cls, *, treat_sponsored_as_follow: bool | None = None) -> "QAPolicy":
        from app.core.config import settings

        return cls(
            treat_sponsored_as_follow=(
                settings.QA_TREAT_SPONSORED_AS_FOLLOW
                if treat_sponsored_as_follow is None
                else treat_sponsored_as_follow
            ),
            thin_content_words=settings.QA_THIN_CONTENT_WORDS,
            excessive_outbound_links=settings.QA_EXCESSIVE_OUTBOUND_LINKS,
            redirect_warn_threshold=settings.CRAWL_REDIRECT_WARN_THRESHOLD,
            trailing_slash_policy=settings.QA_TRAILING_SLASH_POLICY,
        )


@dataclass(slots=True)
class CheckContext:
    """Everything a check function may read. Pure inputs → deterministic issues."""

    artifact: CrawlArtifact
    policy: QAPolicy

    @property
    def request(self):
        return self.artifact.request

    @property
    def expected_rel(self) -> RelType:
        try:
            return RelType(self.request.expected_rel)
        except ValueError:
            return RelType.DOFOLLOW
