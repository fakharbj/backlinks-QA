"""FastAPI application factory.

Wires middleware, exception handlers, the versioned router, health probes and the
Prometheus endpoint. Stateless: any replica can serve any request.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import sentry_sdk
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text
from starlette.responses import PlainTextResponse, Response

from app import __version__
from app.api.v1 import api_router
from app.core.config import settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.core.middleware import CorrelationIdMiddleware
from app.core.redis import close_redis, get_redis
from app.db.session import dispose_engines, engine

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging()
    if settings.SENTRY_DSN:
        sentry_sdk.init(dsn=settings.SENTRY_DSN, environment=settings.ENVIRONMENT,
                        traces_sample_rate=0.1)
    log.info("api_starting", version=__version__, env=settings.ENVIRONMENT)
    yield
    await close_redis()
    await dispose_engines()
    log.info("api_stopped")


def create_app() -> FastAPI:
    configure_logging()
    app = FastAPI(
        title="LinkSentinel API",
        version=__version__,
        description="Enterprise backlink QA, monitoring, validation, reporting & alerting.",
        docs_url="/docs" if settings.DOCS_ENABLED else None,
        redoc_url="/redoc" if settings.DOCS_ENABLED else None,
        openapi_url="/openapi.json" if settings.DOCS_ENABLED else None,
        lifespan=lifespan,
    )

    # Middleware (outermost first).
    app.add_middleware(CorrelationIdMiddleware)
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Correlation-Id", "X-Response-Time-Ms"],
    )

    register_exception_handlers(app)
    app.include_router(api_router, prefix=settings.API_V1_PREFIX)

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict:
        return {"status": "ok", "version": __version__}

    @app.get("/readyz", include_in_schema=False)
    async def readyz() -> Response:
        """Deep readiness: DB + Redis reachable."""
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            await get_redis().ping()
        except Exception as exc:  # noqa: BLE001
            log.warning("readiness_failed", error=str(exc))
            return PlainTextResponse("not ready", status_code=503)
        return PlainTextResponse("ready", status_code=200)

    if settings.PROMETHEUS_ENABLED:
        @app.get("/metrics", include_in_schema=False)
        async def metrics() -> Response:
            return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return app


app = create_app()
