"""ORM models. Importing this package registers every table on ``Base.metadata``."""

from app.models.alerts import AlertRule, Notification  # noqa: F401
from app.models.audit import AuditLog  # noqa: F401
from app.models.backlink import BacklinkRecord  # noqa: F401
from app.models.batch import Batch, BatchItem, BatchLog  # noqa: F401
from app.models.canonical_url import CanonicalUrl  # noqa: F401
from app.models.competitor import (  # noqa: F401
    CompetitorBacklink,
    CompetitorDomainDecision,
    CompetitorSheet,
    CompetitorSourceDomain,
)
from app.models.conflict import (  # noqa: F401
    BacklinkConflict,
    BacklinkConflictAction,
    BacklinkConflictMember,
)
from app.models.crawl import BacklinkIssue, BacklinkHistory, CrawlJob, CrawlResult  # noqa: F401,E501
from app.models.employee import EmployeeCode, UserEmployeeMapping  # noqa: F401
from app.models.gmail_account import GmailAccount, GmailAssignment  # noqa: F401
from app.models.enums import (  # noqa: F401
    HistoryEventType,
    ImportStatus,
    JobStatus,
    JobType,
    NotificationChannel,
    NotificationStatus,
    ProjectStatus,
    ReportFormat,
    ReportStatus,
    ReportType,
)
from app.models.imports import Import, ImportRow  # noqa: F401
from app.models.index_check import IndexCheck  # noqa: F401
from app.models.link_identity import AssignmentHistory, LinkIdentity  # noqa: F401
from app.models.link_type import LinkType  # noqa: F401
from app.models.metric_history import MetricCheckHistory  # noqa: F401
from app.models.project import Campaign, Project, ProjectMember, Vendor  # noqa: F401
from app.models.project_settings import ProjectDomain, ProjectSettings  # noqa: F401
from app.models.qa_attempt import QAAttempt  # noqa: F401
from app.models.recommendation import DomainRecommendation  # noqa: F401
from app.models.report import Report  # noqa: F401
from app.models.scoring import ScoringParameter, ScoringRuleVersion  # noqa: F401
from app.models.source_domain import SourceDomain  # noqa: F401
from app.models.source_domain_rule import SourceDomainRule  # noqa: F401
from app.models.settings import Setting  # noqa: F401
from app.models.sheet_tab import GoogleSheetTab  # noqa: F401
from app.models.sheets import SheetSource  # noqa: F401
from app.models.workforce import (  # noqa: F401
    LeaveRequest,
    LinkTypeProductivity,
    TaskAssignment,
    TeamLeadAssignment,
    UserProductivityOverride,
    WorkingDay,
)
from app.models.user import (  # noqa: F401
    PasswordResetToken,
    RefreshToken,
    User,
    Workspace,
    WorkspaceMember,
)
