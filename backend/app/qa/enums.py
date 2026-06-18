"""QA-domain enumerations (framework-free).

These encode the canonical vocabularies from PRD §8.6 / §8.9: severities, issue
categories, the canonical issue-label set, the overall status, and supporting
classifications (rel type, indexability). The ORM imports these so the database
and the engine never disagree.
"""

from __future__ import annotations

import enum


class Severity(str, enum.Enum):
    """PRD §8.8 — drives both deduction and hard-cap of the score."""

    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"

    @property
    def deduction(self) -> int:
        return {"CRITICAL": 60, "HIGH": 25, "MEDIUM": 10, "LOW": 3, "INFO": 0}[self.value]

    @property
    def cap(self) -> int | None:
        """CRITICAL issues cap the score ceiling at 25 (PRD §8.8)."""
        return 25 if self.value == "CRITICAL" else None

    @property
    def rank(self) -> int:
        return {"CRITICAL": 5, "HIGH": 4, "MEDIUM": 3, "LOW": 2, "INFO": 1}[self.value]


class IssueCategory(str, enum.Enum):
    """The check families of PRD §8.6 (prefix of every check code)."""

    NET = "NET"          # network / transport
    HTTP = "HTTP"        # HTTP status
    RDR = "RDR"          # redirect QA
    LNK = "LNK"          # link presence
    ANC = "ANC"          # anchor text
    REL = "REL"          # rel attribute
    MR = "MR"            # meta robots
    XR = "XR"            # X-Robots-Tag
    CAN = "CAN"          # canonical
    RBT = "RBT"          # robots.txt
    IDX = "IDX"          # indexability (composite)
    CT = "CT"            # content-type
    PQ = "PQ"            # page quality
    BOT = "BOT"          # bot protection / access
    CHG = "CHG"          # change detection


class IssueLabel(str, enum.Enum):
    """Canonical issue-label set (PRD §8.9). Used for filtering & badges."""

    LINK_MISSING = "LINK_MISSING"
    LINK_FOUND = "LINK_FOUND"
    LINK_NOFOLLOW = "LINK_NOFOLLOW"
    LINK_SPONSORED = "LINK_SPONSORED"
    LINK_UGC = "LINK_UGC"
    LINK_HIDDEN = "LINK_HIDDEN"
    PAGE_NOINDEX = "PAGE_NOINDEX"
    PAGE_NOFOLLOW = "PAGE_NOFOLLOW"
    X_ROBOTS_NOINDEX = "X_ROBOTS_NOINDEX"
    X_ROBOTS_NOFOLLOW = "X_ROBOTS_NOFOLLOW"
    ROBOTS_BLOCKED = "ROBOTS_BLOCKED"
    CANONICAL_MISMATCH = "CANONICAL_MISMATCH"
    CANONICAL_CROSS_DOMAIN = "CANONICAL_CROSS_DOMAIN"
    SOURCE_404 = "SOURCE_404"
    SOURCE_403 = "SOURCE_403"
    SOURCE_5XX = "SOURCE_5XX"
    REDIRECT_CHAIN = "REDIRECT_CHAIN"
    REDIRECT_LOOP = "REDIRECT_LOOP"
    WRONG_TARGET = "WRONG_TARGET"
    ANCHOR_CHANGED = "ANCHOR_CHANGED"
    HTTP_ERROR = "HTTP_ERROR"
    SSL_ERROR = "SSL_ERROR"
    TIMEOUT = "TIMEOUT"
    DNS_ERROR = "DNS_ERROR"
    SOFT_404 = "SOFT_404"
    CAPTCHA_DETECTED = "CAPTCHA_DETECTED"
    JS_RENDER_REQUIRED = "JS_RENDER_REQUIRED"
    TOO_MANY_OUTBOUND_LINKS = "TOO_MANY_OUTBOUND_LINKS"
    INDEXABILITY_UNKNOWN = "INDEXABILITY_UNKNOWN"
    # informational / non-error labels
    NONE = "NONE"


class OverallStatus(str, enum.Enum):
    """PRD §8.9 — the verdict shown on every backlink. Also the record status."""

    PASS = "PASS"
    WARNING = "WARNING"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"
    NEEDS_MANUAL_REVIEW = "NEEDS_MANUAL_REVIEW"
    PENDING = "PENDING"  # never crawled yet


class RelType(str, enum.Enum):
    DOFOLLOW = "dofollow"
    NOFOLLOW = "nofollow"
    SPONSORED = "sponsored"
    UGC = "ugc"
    UNKNOWN = "unknown"


class Indexability(str, enum.Enum):
    INDEXABLE = "indexable"
    NOT_INDEXABLE = "not_indexable"
    UNKNOWN = "unknown"


class ExternalIndexStatus(str, enum.Enum):
    """Optional GSC/site: verification, kept separate from computed indexability."""

    INDEXED = "indexed"
    NOT_INDEXED = "not_indexed"
    UNKNOWN = "unknown"
    CANNOT_VERIFY = "cannot_verify"


class GradeBand(str, enum.Enum):
    PERFECT = "perfect"   # 100
    GOOD = "good"         # 80-99
    WARNING = "warning"   # 60-79
    RISKY = "risky"       # 30-59
    FAILED = "failed"     # 0-29

    @classmethod
    def from_score(cls, score: int) -> "GradeBand":
        if score >= 100:
            return cls.PERFECT
        if score >= 80:
            return cls.GOOD
        if score >= 60:
            return cls.WARNING
        if score >= 30:
            return cls.RISKY
        return cls.FAILED
