"""Versioned API router aggregation."""

from fastapi import APIRouter

from app.api.v1 import (
    alerts,
    analytics,
    auth,
    backlinks,
    batches,
    competitors,
    conflicts,
    crawl,
    dashboard,
    emails,
    employees,
    gmail,
    imports,
    index,
    link_types,
    performance,
    project_settings,
    projects,
    reports,
    scoring,
    settings,
    sheets,
    source_domains,
    team,
    workforce,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(projects.router)
api_router.include_router(project_settings.router)
api_router.include_router(backlinks.router)
api_router.include_router(batches.router)
api_router.include_router(competitors.router)
api_router.include_router(conflicts.router)
api_router.include_router(emails.router)
api_router.include_router(employees.router)
api_router.include_router(gmail.router)
api_router.include_router(link_types.router)
api_router.include_router(imports.router)
api_router.include_router(crawl.router)
api_router.include_router(dashboard.router)
api_router.include_router(analytics.router)
api_router.include_router(index.router)
api_router.include_router(performance.router)
api_router.include_router(reports.router)
api_router.include_router(scoring.router)
api_router.include_router(alerts.router)
api_router.include_router(settings.router)
api_router.include_router(sheets.router)
api_router.include_router(source_domains.router)
api_router.include_router(team.router)
api_router.include_router(workforce.router)
