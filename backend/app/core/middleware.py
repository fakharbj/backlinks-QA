"""HTTP middleware: correlation id propagation + structured access logging."""

from __future__ import annotations

import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import correlation_id, get_logger

log = get_logger("http")


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[override]
        cid = request.headers.get("X-Correlation-Id") or uuid.uuid4().hex
        token = correlation_id.set(cid)
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            elapsed = (time.perf_counter() - start) * 1000
            log.error(
                "request_failed",
                method=request.method,
                path=request.url.path,
                duration_ms=round(elapsed, 2),
            )
            raise
        finally:
            correlation_id.reset(token)

        elapsed = (time.perf_counter() - start) * 1000
        response.headers["X-Correlation-Id"] = cid
        response.headers["X-Response-Time-Ms"] = f"{elapsed:.2f}"
        # Skip noisy health/metrics in the access log.
        if request.url.path not in ("/healthz", "/readyz", "/metrics"):
            log.info(
                "request",
                method=request.method,
                path=request.url.path,
                status=response.status_code,
                duration_ms=round(elapsed, 2),
            )
        return response
