"""Sondes de santé pour Kubernetes.

- /healthz : liveness. Répond 200 dès que le process tourne.
- /readyz  : readiness. Exécute des checks de dépendances (DB, cache, broker) ;
  renvoie 503 tant qu'une dépendance n'est pas prête.
"""
from __future__ import annotations

import logging
from typing import Awaitable, Callable

from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

# Un check de readiness : coroutine -> bool (ou lève une exception).
ReadinessCheck = Callable[[], Awaitable[bool]]


def register_health(app, settings, readiness: list[tuple[str, ReadinessCheck]] | None = None) -> None:
    checks = readiness or []

    @app.get("/healthz", include_in_schema=False)
    async def _healthz():  # noqa: ANN202
        return JSONResponse({"status": "ok", "service": settings.service_name})

    @app.get("/readyz", include_in_schema=False)
    async def _readyz():  # noqa: ANN202
        results: dict[str, str] = {}
        ready = True
        for name, check in checks:
            try:
                ok = await check()
                results[name] = "ok" if ok else "down"
                ready = ready and ok
            except Exception as exc:  # pragma: no cover
                results[name] = f"error: {exc.__class__.__name__}"
                ready = False
        code = 200 if ready else 503
        return JSONResponse(
            {"status": "ready" if ready else "not-ready", "checks": results},
            status_code=code,
        )
