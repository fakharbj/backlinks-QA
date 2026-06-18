"""LinkSentinel — Backlink QA & Monitoring platform (backend).

A modular monolith: a single FastAPI codebase with clean domain boundaries and
two framework-free libraries — ``app.crawler`` and ``app.qa`` — that are reused
by both the synchronous API (single live recheck) and the Celery worker fleet
(bulk crawling at 1M+ scale). See docs/02-system-architecture.md.
"""

__version__ = "1.0.0"
