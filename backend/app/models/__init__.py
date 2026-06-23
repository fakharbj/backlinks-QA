"""ORM models. Importing this package registers every table on ``Base.metadata``."""

from app.models.alerts import AlertRule, Notification  # noqa: F401
from app.models.audit import AuditLog  # noqa: F401
from app.models.backlink import BacklinkRecord  # noqa: F401
from app.models.crawl import BacklinkIssue, BacklinkHistory, CrawlJob, CrawlResult  # noqa: F401,E501
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
from app.models.project import Campaign, Project, ProjectMember, Vendor  # noqa: F401
from app.models.report import Report  # noqa: F401
from app.models.settings import Setting  # noqa: F401
from app.models.sheets import SheetSource  # noqa: F401
from app.models.user import (  # noqa: F401
    PasswordResetToken,
    RefreshToken,
    User,
    Workspace,
    WorkspaceMember,
)
