"""Middleware transverse : corrélation, métriques et logs d'accès."""
from __future__ import annotations

import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.types import ASGIApp

from .logging import request_id_var, tenant_id_var, user_id_var
from .metrics import HTTP_IN_FLIGHT, HTTP_LATENCY, HTTP_REQUESTS

access_logger = logging.getLogger("fiduce.access")


def _route_template(request: Request) -> str:
    route = request.scope.get("route")
    if route is not None and getattr(route, "path", None):
        return route.path
    return request.url.path


class ObservabilityMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, *, settings) -> None:
        super().__init__(app)
        self.service = settings.service_name

    async def dispatch(self, request: Request, call_next):  # noqa: ANN201
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        tenant = request.headers.get("x-tenant-id", "-")
        user = request.headers.get("x-user-id", "-")
        rid_tok = request_id_var.set(request_id)
        ten_tok = tenant_id_var.set(tenant)
        usr_tok = user_id_var.set(user)

        HTTP_IN_FLIGHT.labels(self.service).inc()
        start = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["x-request-id"] = request_id
            return response
        finally:
            elapsed = time.perf_counter() - start
            route = _route_template(request)
            HTTP_IN_FLIGHT.labels(self.service).dec()
            HTTP_REQUESTS.labels(self.service, request.method, route, str(status)).inc()
            HTTP_LATENCY.labels(self.service, request.method, route).observe(elapsed)
            if route not in ("/healthz", "/readyz", "/metrics"):
                access_logger.info(
                    "request",
                    extra={
                        "extra_fields": {
                            "method": request.method,
                            "route": route,
                            "path": request.url.path,
                            "status": status,
                            "duration_ms": round(elapsed * 1000, 2),
                        }
                    },
                )
            request_id_var.reset(rid_tok)
            tenant_id_var.reset(ten_tok)
            user_id_var.reset(usr_tok)
