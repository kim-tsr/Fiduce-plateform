"""Fabrique d'application : assemble les briques transverses sur un FastAPI."""
from __future__ import annotations

from fastapi import FastAPI

from .health import register_health
from .logging import setup_logging
from .metrics import register_metrics
from .middleware import ObservabilityMiddleware
from .telemetry import instrument_fastapi, instrument_httpx, setup_tracing


def build_app(settings, *, lifespan=None, readiness=None) -> FastAPI:
    """Crée un FastAPI prêt pour la prod (logs JSON, traces, métriques, santé).

    Chaque service fournit son propre `lifespan` (init/arrêt de ses dépendances)
    et la liste de ses `readiness` checks.
    """
    setup_logging(settings)
    setup_tracing(settings)

    app = FastAPI(
        title=settings.service_name,
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/docs",
        openapi_url="/openapi.json",
    )

    app.add_middleware(ObservabilityMiddleware, settings=settings)
    instrument_fastapi(app)
    instrument_httpx()

    register_metrics(app, settings)
    register_health(app, settings, readiness)
    return app
