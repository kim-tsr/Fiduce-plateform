"""Initialisation du tracing OpenTelemetry.

Export OTLP/HTTP si un endpoint est configuré, sinon le service fonctionne sans
export distant. Instrumente FastAPI et httpx pour propager le contexte W3C
traceparent de bout en bout (gateway -> services).
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_TRACING_READY = False


def setup_tracing(settings) -> None:
    global _TRACING_READY
    if _TRACING_READY:
        return
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        resource = Resource.create(
            {
                "service.name": settings.service_name,
                "service.namespace": settings.service_namespace,
            }
        )
        provider = TracerProvider(resource=resource)

        if settings.otel_exporter_otlp_endpoint:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )

            endpoint = settings.otel_exporter_otlp_endpoint.rstrip("/") + "/v1/traces"
            provider.add_span_processor(
                BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint))
            )
            logger.info("OTLP exporter actif: %s", endpoint)
        else:
            logger.info("OTEL_EXPORTER_OTLP_ENDPOINT absent : pas d'export de traces")

        trace.set_tracer_provider(provider)
        _TRACING_READY = True
    except Exception:  # pragma: no cover
        logger.exception("Echec d'initialisation du tracing (on continue sans)")


def instrument_fastapi(app) -> None:
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app, excluded_urls="healthz,readyz,metrics")
    except Exception:  # pragma: no cover
        logger.exception("Instrumentation FastAPI indisponible")


def instrument_httpx() -> None:
    try:
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

        HTTPXClientInstrumentor().instrument()
    except Exception:  # pragma: no cover
        logger.exception("Instrumentation httpx indisponible")


def get_tracer(name: str = "fiduce"):
    from opentelemetry import trace

    return trace.get_tracer(name)
