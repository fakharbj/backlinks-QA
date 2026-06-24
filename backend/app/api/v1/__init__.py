"""Versioned API router aggregation."""

from fastapi import APIRouter

from app.api.v1 import (
    alerts,
    analytics,
    auth,
    backlinks,
    crawl,
    dashboard,
    imports,
    index,
    projects,
    reports,
    settings,
    sheets,
    team,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(projects.router)
api_router.include_router(backlinks.router)
api_router.include_router(imports.router)
api_router.include_router(crawl.router)
api_router.include_router(dashboard.router)
api_router.include_router(analytics.router)
api_router.include_router(index.router)
api_router.include_router(reports.router)
api_router.include_router(alerts.router)
api_router.include_router(settings.router)
api_router.include_router(sheets.router)
api_router.include_router(team.router)
