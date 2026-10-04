"""Messagerie asynchrone via NATS JetStream.

- Stream durable unique (`FIDUCE`) couvrant les sujets `fiduce.>`.
- Abonnements durables avec *queue group* : plusieurs réplicas du worker se
  partagent la charge (support du scaling horizontal / HPA).
- Le contexte de trace W3C est injecté dans les en-têtes du message à la
  publication et restauré à la consommation (corrélation de bout en bout).
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Awaitable, Callable

import nats
from nats.js.api import ConsumerConfig, RetentionPolicy, StreamConfig

logger = logging.getLogger(__name__)

_nc = None  # type: ignore[var-annotated]
_js = None  # type: ignore[var-annotated]
_stream = "FIDUCE"


async def init_broker(settings):
    global _nc, _js, _stream
    if _js is not None:
        return _js
    if not settings.nats_url:
        raise RuntimeError("NATS_URL non configurée")
    _stream = settings.nats_stream

    last_exc: Exception | None = None
    for attempt in range(1, 31):
        try:
            _nc = await nats.connect(
                settings.nats_url,
                max_reconnect_attempts=-1,
                reconnect_time_wait=1,
                connect_timeout=5,
                name=settings.service_name,
            )
            break
        except Exception as exc:  # pragma: no cover - dépend de l'infra
            last_exc = exc
            logger.warning("NATS injoignable (%d/30): %s", attempt, exc)
            await asyncio.sleep(1.0)
    else:
        raise RuntimeError(f"Connexion NATS impossible: {last_exc}")

    _js = _nc.jetstream()

    cfg = StreamConfig(
        name=_stream,
        subjects=[f"{_stream.lower()}.>"],
        retention=RetentionPolicy.WORK_QUEUE,
        max_msgs=-1,
    )
    try:
        await _js.add_stream(cfg)
    except Exception:
        # Le stream existe déjà : on tente une mise à jour idempotente.
        try:
            await _js.update_stream(cfg)
        except Exception:  # pragma: no cover
            logger.info("Stream %s déjà présent", _stream)
    logger.info("NATS JetStream prêt (stream=%s)", _stream)
    return _js


def get_js():
    if _js is None:
        raise RuntimeError("Broker non initialisé (init_broker non appelé)")
    return _js


async def close_broker() -> None:
    global _nc, _js
    if _nc is not None:
        await _nc.drain()
        _nc = None
        _js = None


async def ping_broker() -> bool:
    try:
        return _nc is not None and _nc.is_connected
    except Exception:  # pragma: no cover
        return False


def _inject_trace_headers() -> dict[str, str]:
    headers: dict[str, str] = {}
    try:
        from opentelemetry.propagate import inject

        inject(headers)
    except Exception:  # pragma: no cover
        pass
    return headers


async def publish(subject: str, data: dict) -> None:
    payload = json.dumps(data).encode()
    headers = _inject_trace_headers()
    await get_js().publish(subject, payload, headers=headers)


Handler = Callable[[dict], Awaitable[None]]


async def subscribe(subject: str, durable: str, queue: str, handler: Handler):
    """Abonnement durable avec ack manuel + groupe de file (load balancing)."""
    from opentelemetry import trace
    from opentelemetry.propagate import extract

    tracer = trace.get_tracer("fiduce.broker")

    async def _cb(msg):  # noqa: ANN001
        carrier = {k: v for k, v in (msg.headers or {}).items()}
        ctx = extract(carrier)
        with tracer.start_as_current_span(f"consume {subject}", context=ctx):
            try:
                data = json.loads(msg.data.decode())
                await handler(data)
                await msg.ack()
            except Exception:
                logger.exception("Echec de traitement du message sur %s", subject)
                await msg.nak(delay=5)

    sub = await get_js().subscribe(
        subject,
        durable=durable,
        queue=queue,
        cb=_cb,
        manual_ack=True,
        config=ConsumerConfig(ack_wait=60, max_deliver=5),
    )
    logger.info("Abonné à %s (durable=%s, queue=%s)", subject, durable, queue)
    return sub


async def consumer_pending(durable: str) -> int:
    """Messages en attente pour un consommateur (utile pour métrique/HPA)."""
    try:
        info = await get_js().consumer_info(_stream, durable)
        return int(info.num_pending)
    except Exception:  # pragma: no cover
        return 0
