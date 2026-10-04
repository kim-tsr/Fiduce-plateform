"""Métriques Prometheus exposées sur /metrics."""
from __future__ import annotations

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from starlette.responses import Response

HTTP_REQUESTS = Counter(
    "http_requests_total",
    "Nombre total de requêtes HTTP",
    ["service", "method", "route", "status"],
)
HTTP_LATENCY = Histogram(
    "http_request_duration_seconds",
    "Latence des requêtes HTTP",
    ["service", "method", "route"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)
HTTP_IN_FLIGHT = Gauge(
    "http_requests_in_flight",
    "Requêtes HTTP en cours",
    ["service"],
)

# Métriques métier réutilisables par les services / le worker.
JOBS_PROCESSED = Counter(
    "fiduce_jobs_processed_total",
    "Jobs asynchrones traités",
    ["service", "kind", "result"],
)
JOB_DURATION = Histogram(
    "fiduce_job_duration_seconds",
    "Durée de traitement d'un job asynchrone",
    ["service", "kind"],
)
QUEUE_DEPTH = Gauge(
    "fiduce_queue_depth",
    "Profondeur estimée de la file (messages en attente)",
    ["service", "subject"],
)


def metrics_response() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


def register_metrics(app, settings) -> None:
    @app.get("/metrics", include_in_schema=False)
    async def _metrics():  # noqa: ANN202
        return metrics_response()
