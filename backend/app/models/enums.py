"""System-level enumerations used by the ORM and API.

QA-domain enums (Severity, OverallStatus, IssueLabel, …) live in ``app.qa.enums``
and are re-exported here so callers have a single import site.
"""

from __future__ import annotations

import enum

# Re-export QA enums for convenience / single import site.
from app.qa.enums import (  # noqa: F401
    ExternalIndexStatus,
    GradeBand,
    Indexability,
    IssueCategory,
    IssueLabel,
    OverallStatus,
    RelType,
    Severity,
)


class ProjectStatus(str, enum.Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    ARCHIVED = "archived"


class ScheduleInterval(str, enum.Enum):
    MANUAL = "manual"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class JobType(str, enum.Enum):
    SINGLE = "single"          # one manual recheck
    BULK = "bulk"              # bulk/scheduled batch
    IMPORT = "import"          # crawl triggered by an import
    SCHEDULED = "scheduled"    # beat-driven recheck


class JobStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    PARTIAL = "partial"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CrawlMode(str, enum.Enum):
    RAW = "raw"
    RENDERED = "rendered"


class ImportSource(str, enum.Enum):
    CSV = "csv"
    XLSX = "xlsx"
    MANUAL = "manual"
    PASTE = "paste"
    GOOGLE_SHEETS = "google_sheets"
    API = "api"


class ImportStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    PARTIAL = "partial"
    COMPLETED = "completed"
    FAILED = "failed"


class ImportRowStatus(str, enum.Enum):
    PENDING = "pending"
    VALID = "valid"
    IMPORTED = "imported"
    DUPLICATE = "duplicate"
    ERROR = "error"


class ReportType(str, enum.Enum):
    CLIENT = "client"
    CAMPAIGN = "campaign"
    VENDOR = "vendor"
    FAILED_LINKS = "failed_links"
    MONTHLY_QA = "monthly_qa"
    CHANGE_HISTORY = "change_history"
    # Pivot/summary reports (Phase 8) — grouped rows instead of one row per link.
    SOURCE_DOMAIN_SUMMARY = "source_domain_summary"
    LINK_TYPE_SUMMARY = "link_type_summary"
    USER_PERFORMANCE = "user_performance"


class ReportFormat(str, enum.Enum):
    CSV = "csv"
    XLSX = "xlsx"
    PDF = "pdf"


class ReportStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class NotificationChannel(str, enum.Enum):
    IN_APP = "in_app"
    EMAIL = "email"
    SLACK = "slack"
    WEBHOOK = "webhook"


class NotificationStatus(str, enum.Enum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    READ = "read"


class HistoryEventType(str, enum.Enum):
    """Typed change-detection events (PRD §8.10)."""

    LINK_REMOVED = "link_removed"
    LINK_ADDED = "link_added"
    REL_CHANGED = "rel_changed"
    ANCHOR_CHANGED = "anchor_changed"
    INDEX_TO_NOINDEX = "index_to_noindex"
    NOINDEX_TO_INDEX = "noindex_to_index"
    CANONICAL_CHANGED = "canonical_changed"
    STATUS_CODE_CHANGED = "status_code_changed"
    REDIRECT_TARGET_CHANGED = "redirect_target_changed"
    ROBOTS_CHANGED = "robots_changed"
    XROBOTS_CHANGED = "xrobots_changed"
    BECAME_BLOCKED = "became_blocked"
    BECAME_ACCESSIBLE = "became_accessible"
    SCORE_CHANGED = "score_changed"
    ISSUE_COUNT_CHANGED = "issue_count_changed"
    TARGET_CHANGED = "target_changed"
    FIRST_CRAWL = "first_crawl"


class AuditAction(str, enum.Enum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    LOGIN = "login"
    LOGIN_FAILED = "login_failed"
    LOGOUT = "logout"
    OVERRIDE = "override"
    EXPORT = "export"
    IMPORT = "import"
    RECHECK = "recheck"
