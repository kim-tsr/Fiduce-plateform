"""Logging structuré JSON, corrélé aux traces et au tenant.

Chaque ligne de log porte `trace_id`, `request_id` et `tenant`, ce qui permet de
relier logs, métriques et traces pour une même requête (exigence d'observabilité).
"""
from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime

# Contexte propagé par requête (renseigné par le middleware).
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")
tenant_id_var: ContextVar[str] = ContextVar("tenant_id", default="-")
user_id_var: ContextVar[str] = ContextVar("user_id", default="-")

_SERVICE = "fiduce-service"


def _current_trace_id() -> str:
    try:
        from opentelemetry import trace

        span = trace.get_current_span()
        ctx = span.get_span_context()
        if ctx and ctx.trace_id:
            return format(ctx.trace_id, "032x")
    except Exception:  # pragma: no cover - OTel non initialisé
        pass
    return "-"


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "service": _SERVICE,
            "msg": record.getMessage(),
            "trace_id": _current_trace_id(),
            "request_id": request_id_var.get(),
            "tenant": tenant_id_var.get(),
            "user": user_id_var.get(),
        }
        # Champs additionnels passés via logger.info(..., extra={"extra_fields": {...}})
        extra = getattr(record, "extra_fields", None)
        if isinstance(extra, dict):
            payload.update(extra)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(settings) -> logging.Logger:
    global _SERVICE
    _SERVICE = settings.service_name

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(settings.log_level.upper())

    # Aligne les loggers uvicorn/asyncpg sur le même format JSON.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers.clear()
        lg.propagate = True

    return logging.getLogger(settings.service_name)
