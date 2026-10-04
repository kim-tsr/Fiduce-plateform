"""Worker de traitement asynchrone.

Consomme deux familles de jobs depuis NATS JetStream :
- `*.reconcile.requested` : exécute la réconciliation d'un run.
- `*.report.requested`    : génère le contenu d'un rapport.

Plusieurs réplicas se partagent la charge via un *queue group* (scaling horizontal).
Le worker expose tout de même /healthz, /readyz et /metrics pour Kubernetes.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fiduce_platform.app_factory import build_app
from fiduce_platform.broker import (
    close_broker,
    consumer_pending,
    init_broker,
    ping_broker,
    subscribe,
)
from fiduce_platform.cache import close_cache, get_cache, init_cache, ping_cache
from fiduce_platform.config import get_settings
from fiduce_platform.db import close_db, get_pool, init_db, ping_db
from fiduce_platform.metrics import JOB_DURATION, JOBS_PROCESSED, QUEUE_DEPTH

logger = logging.getLogger("worker")
settings = get_settings(service_name="worker", http_port=8000)

PREFIX = settings.nats_stream.lower()
RECONCILE_SUBJECT = f"{PREFIX}.reconcile.requested"
REPORT_SUBJECT = f"{PREFIX}.report.requested"
RECONCILE_DURABLE = "reconcile-worker"
REPORT_DURABLE = "report-worker"
# JetStream (nats-py) lie le *queue group* (deliver group) au nom du durable :
# pour un abonnement de file, queue == durable. Le partage de charge entre
# réplicas se fait donc par durable (un par type de job), pas via un groupe
# unique partagé. On dérive le groupe du durable pour respecter cette contrainte.

_metrics_task: asyncio.Task | None = None


# --- Traitements métier ------------------------------------------------------

async def handle_reconcile(data: dict) -> None:
    run_id = data["run_id"]
    tenant = data["tenant"]
    started = time.perf_counter()
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "UPDATE reconciliation_runs SET status='running' "
                "WHERE id=$1 AND tenant_id=$2",
                run_id, tenant,
            )
            # Règle simplifiée : une écriture portant une référence externe est
            # considérée rapprochée (matchée au relevé bancaire), sinon non.
            await conn.execute(
                "UPDATE entries SET status='matched' "
                "WHERE tenant_id=$1 AND status='pending' AND external_ref IS NOT NULL",
                tenant,
            )
            await conn.execute(
                "UPDATE entries SET status='unmatched' "
                "WHERE tenant_id=$1 AND status='pending' AND external_ref IS NULL",
                tenant,
            )
            matched_count = await conn.fetchval(
                "SELECT count(*) FROM entries WHERE tenant_id=$1 AND status='matched'",
                tenant,
            )
            unmatched_count = await conn.fetchval(
                "SELECT count(*) FROM entries WHERE tenant_id=$1 AND status='unmatched'",
                tenant,
            )
            await conn.execute(
                "UPDATE reconciliation_runs SET status='completed', "
                "matched_count=$3, unmatched_count=$4, completed_at=now() "
                "WHERE id=$1 AND tenant_id=$2",
                run_id, tenant, int(matched_count), int(unmatched_count),
            )
    # Les soldes peuvent avoir changé : on purge le cache du tenant.
    await _invalidate_tenant_balances(tenant)
    JOBS_PROCESSED.labels("worker", "reconcile", "ok").inc()
    JOB_DURATION.labels("worker", "reconcile").observe(time.perf_counter() - started)
    logger.info(
        "Réconciliation terminée",
        extra={"extra_fields": {"run_id": run_id, "tenant": tenant,
                                "matched": int(matched_count),
                                "unmatched": int(unmatched_count)}},
    )


async def handle_report(data: dict) -> None:
    report_id = data["report_id"]
    tenant = data["tenant"]
    rtype = data.get("type", "balance_summary")
    started = time.perf_counter()
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE reports SET status='processing' WHERE id=$1 AND tenant_id=$2",
            report_id, tenant,
        )
        result = await _build_report(conn, tenant, rtype)
        await conn.execute(
            "UPDATE reports SET status='ready', result=$3, completed_at=now() "
            "WHERE id=$1 AND tenant_id=$2",
            report_id, tenant, json.dumps(result),
        )
    JOBS_PROCESSED.labels("worker", "report", "ok").inc()
    JOB_DURATION.labels("worker", "report").observe(time.perf_counter() - started)
    logger.info(
        "Rapport généré",
        extra={"extra_fields": {"report_id": report_id, "tenant": tenant, "type": rtype}},
    )


async def _build_report(conn, tenant: str, rtype: str) -> dict:
    accounts = await conn.fetch(
        "SELECT a.code, a.name, a.currency, "
        "COALESCE(SUM(CASE WHEN e.side='debit' THEN e.amount_cents "
        "ELSE -e.amount_cents END),0) AS balance_cents, "
        "count(e.id) AS entry_count "
        "FROM accounts a LEFT JOIN entries e ON e.account_id=a.id AND e.tenant_id=a.tenant_id "
        "WHERE a.tenant_id=$1 GROUP BY a.code, a.name, a.currency ORDER BY a.code",
        tenant,
    )
    status_counts = await conn.fetch(
        "SELECT status, count(*) AS n FROM entries WHERE tenant_id=$1 GROUP BY status",
        tenant,
    )
    return {
        "type": rtype,
        "tenant": tenant,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        # asyncpg mappe SUM(bigint) -> Decimal et count() -> int : on normalise
        # en entiers, sinon json.dumps échoue (Decimal non sérialisable).
        "accounts": [
            {
                "code": a["code"],
                "name": a["name"],
                "currency": a["currency"],
                "balance_cents": int(a["balance_cents"]),
                "entry_count": int(a["entry_count"]),
            }
            for a in accounts
        ],
        "entries_by_status": {r["status"]: int(r["n"]) for r in status_counts},
    }


async def _invalidate_tenant_balances(tenant: str) -> None:
    try:
        cache = get_cache()
        async for key in cache.scan_iter(match=f"balance:{tenant}:*"):
            await cache.delete(key)
    except Exception:  # pragma: no cover
        logger.warning("Invalidation du cache impossible pour %s", tenant)


# --- Tâche de mesure de la profondeur de file (pour HPA custom / supervision) -

async def _publish_queue_depth() -> None:
    while True:
        try:
            QUEUE_DEPTH.labels("worker", RECONCILE_SUBJECT).set(
                await consumer_pending(RECONCILE_DURABLE)
            )
            QUEUE_DEPTH.labels("worker", REPORT_SUBJECT).set(
                await consumer_pending(REPORT_DURABLE)
            )
        except Exception:  # pragma: no cover
            pass
        await asyncio.sleep(5)


@asynccontextmanager
async def lifespan(app):
    global _metrics_task
    await init_db(settings)
    await init_cache(settings)
    await init_broker(settings)
    await subscribe(RECONCILE_SUBJECT, RECONCILE_DURABLE, RECONCILE_DURABLE, handle_reconcile)
    await subscribe(REPORT_SUBJECT, REPORT_DURABLE, REPORT_DURABLE, handle_report)
    _metrics_task = asyncio.create_task(_publish_queue_depth())
    logger.info("Worker prêt, en écoute des jobs")
    yield
    if _metrics_task:
        _metrics_task.cancel()
    await close_broker()
    await close_cache()
    await close_db()


# Application minimale : expose seulement /healthz, /readyz, /metrics.
app = build_app(
    settings,
    lifespan=lifespan,
    readiness=[("postgres", ping_db), ("redis", ping_cache), ("nats", ping_broker)],
)
