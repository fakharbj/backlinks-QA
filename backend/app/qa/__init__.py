"""LinkSentinel QA engine — a framework-free library.

Consumes a ``CrawlArtifact`` (from ``app.crawler``) and produces a ``QAResult``
(issues + composite booleans + deterministic score + status + recommendations).
Contains **no** FastAPI/Celery/SQLAlchemy imports so it can be unit-tested in
isolation and reused by both the API (single live recheck) and the worker fleet.
"""

from app.qa.engine import evaluate  # noqa: F401
from app.qa.enums import IssueCategory, IssueLabel, OverallStatus, Severity  # noqa: F401
from app.qa.types import Issue, QAResult  # noqa: F401
