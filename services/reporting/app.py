"""Service reporting : API de demande de rapports (traitement asynchrone).

La génération réelle est déléguée au worker via NATS. Ce service ne fait
qu'enregistrer la demande et publier le job ; il expose ensuite le statut/résultat.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, Header, HTTPException
from pydantic import BaseModel, Field

from fiduce_platform.app_factory import build_app
from fiduce_platform.broker import close_broker, init_broker, ping_broker, publish
from fiduce_platform.config import get_settings
from fiduce_platform.db import close_db, get_pool, init_db, ping_db

logger = logging.getLogger("reporting")
settings = get_settings(service_name="reporting", http_port=8000)

VALID_TYPES = {"balance_summary", "reconciliation_audit", "entries_export"}


@asynccontextmanager
async def lifespan(app):
    await init_db(settings)
    await init_broker(settings)
    yield
    await close_broker()
    await close_db()


app = build_app(
    settings,
    lifespan=lifespan,
    readiness=[("postgres", ping_db), ("nats", ping_broker)],
)


async def require_tenant(x_tenant_id: str | None = Header(default=None)) -> str:
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="En-tête X-Tenant-ID requis")
    return x_tenant_id


class ReportIn(BaseModel):
    type: str = Field(description="balance_summary | reconciliation_audit | entries_export")
    period: str | None = None


@app.post("/reports", status_code=202)
async def request_report(body: ReportIn, tenant: str = Depends(require_tenant)):
    if body.type not in VALID_TYPES:
        raise HTTPException(status_code=422, detail=f"Type inconnu. Attendu: {sorted(VALID_TYPES)}")
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            "INSERT INTO reports (tenant_id, type, period, status) "
            "VALUES ($1,$2,$3,'pending') RETURNING id, type, period, status, requested_at",
            tenant, body.type, body.period,
        )
    await publish(
        f"{settings.nats_stream.lower()}.report.requested",
        {
            "report_id": str(row["id"]),
            "tenant": tenant,
            "type": body.type,
            "period": body.period,
        },
    )
    return {"report_id": str(row["id"]), "status": row["status"], "type": row["type"]}


@app.get("/reports")
async def list_reports(tenant: str = Depends(require_tenant), limit: int = 50):
    limit = max(1, min(limit, 200))
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, type, period, status, requested_at, completed_at "
            "FROM reports WHERE tenant_id=$1 ORDER BY requested_at DESC LIMIT " + str(limit),
            tenant,
        )
    return [dict(r) for r in rows]


@app.get("/reports/{report_id}")
async def get_report(report_id: str, tenant: str = Depends(require_tenant)):
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, type, period, status, result, requested_at, completed_at "
            "FROM reports WHERE tenant_id=$1 AND id=$2",
            tenant, report_id,
        )
    if row is None:
        raise HTTPException(status_code=404, detail="Rapport inconnu pour ce tenant")
    data = dict(row)
    if data.get("result") is not None:
        import json

        data["result"] = json.loads(data["result"])
    return data
