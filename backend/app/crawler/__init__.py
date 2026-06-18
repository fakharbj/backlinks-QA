"""LinkSentinel crawler — a framework-free library.

Same code path for one link (live API recheck) or a million (worker fleet). The
public surface is intentionally small:

    from app.crawler import CrawlEngine, CrawlRequest, normalize_url

No FastAPI / Celery / SQLAlchemy imports here — only stdlib + httpx + lxml +
(optionally) Playwright. The engine produces a ``CrawlArtifact`` that the
``app.qa`` engine consumes.
"""

from app.crawler.types import (  # noqa: F401
    CrawlArtifact,
    CrawlRequest,
    FetchError,
    ParsedLink,
    RedirectHop,
    RobotsResult,
)
from app.crawler.normalize import NormalizedUrl, normalize_url, registrable_domain  # noqa: F401,E501
from app.crawler.engine import CrawlEngine, CrawlConfig, crawl_one  # noqa: F401
