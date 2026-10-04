"""Service ledger : ingestion d'écritures, soldes, réconciliation (cœur métier).

Toutes les requêtes sont strictement filtrées par tenant. L'identité du tenant
est portée par l'en-tête `X-Tenant-ID` positionné par la gateway APRÈS validation
du JWT (frontière de confiance documentée — à durcir côté plateforme : mTLS de
maillage, revue de token par service, etc.).
"""
from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, Header, HTTPException
from pydantic import BaseModel, Field

from fiduce_platform.app_factory import build_app
from fiduce_platform.broker import close_broker, init_broker, ping_broker, publish
from fiduce_platform.cache import close_cache, get_cache, init_cache, ping_cache
from fiduce_platform.config import get_settings
from fiduce_platform.db import close_db, get_pool, init_db, ping_db

logger = logging.getLogger("ledger")
settings = get_settings(service_name="ledger", http_port=8000)


@asynccontextmanager
async def lifespan(app):
    await init_db(settings)
    await init_cache(settings)
    await init_broker(settings)
    yield
    await close_broker()
    await close_cache()
    await close_db()


app = build_app(
    settings,
    lifespan=lifespan,
    readiness=[("postgres", ping_db), ("redis", ping_cache), ("nats", ping_broker)],
)


async def require_tenant(x_tenant_id: str | None = Header(default=None)) -> str:
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="En-tête X-Tenant-ID requis")
    return x_tenant_id


class EntryIn(BaseModel):
    account_code: str
    amount_cents: int = Field(gt=0)
    side: str = Field(pattern="^(debit|credit)$")
    currency: str = "EUR"
    reference: str | None = None
    external_ref: str | None = None


@app.get("/accounts")
async def list_accounts(tenant: str = Depends(require_tenant)):
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, code, name, currency FROM accounts WHERE tenant_id=$1 ORDER BY code",
            tenant,
        )
    return [dict(r) for r in rows]


@app.get("/entries")
async def list_entries(
    tenant: str = Depends(require_tenant),
    status: str | None = None,
    limit: int = 100,
):
    limit = max(1, min(limit, 500))
    query = (
        "SELECT e.id, a.code AS account_code, e.amount_cents, e.currency, e.side, "
        "e.reference, e.external_ref, e.status, e.created_at "
        "FROM entries e JOIN accounts a ON a.id = e.account_id "
        "WHERE e.tenant_id=$1"
    )
    params: list = [tenant]
    if status:
        params.append(status)
        query += f" AND e.status=${len(params)}"
    query += " ORDER BY e.created_at DESC LIMIT " + str(limit)
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(query, *params)
    return [dict(r) for r in rows]


@app.post("/entries", status_code=201)
async def create_entry(body: EntryIn, tenant: str = Depends(require_tenant)):
    async with get_pool().acquire() as conn:
        account = await conn.fetchrow(
            "SELECT id FROM accounts WHERE tenant_id=$1 AND code=$2",
            tenant, body.account_code,
        )
        if account is None:
            raise HTTPException(status_code=404, detail="Compte inconnu pour ce tenant")
        row = await conn.fetchrow(
            "INSERT INTO entries "
            "(tenant_id, account_id, amount_cents, currency, side, reference, external_ref) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7) "
            "RETURNING id, amount_cents, currency, side, status, created_at",
            tenant, account["id"], body.amount_cents, body.currency,
            body.side, body.reference, body.external_ref,
        )
    # Invalide le solde en cache pour ce compte.
    await get_cache().delete(f"balance:{tenant}:{body.account_code}")
    return {"account_code": body.account_code, **dict(row)}


@app.get("/accounts/{code}/balance")
async def account_balance(code: str, tenant: str = Depends(require_tenant)):
    cache_key = f"balance:{tenant}:{code}"
    cached = await get_cache().get(cache_key)
    if cached is not None:
        return {**json.loads(cached), "cached": True}

    async with get_pool().acquire() as conn:
        account = await conn.fetchrow(
            "SELECT id, currency FROM accounts WHERE tenant_id=$1 AND code=$2",
            tenant, code,
        )
        if account is None:
            raise HTTPException(status_code=404, detail="Compte inconnu pour ce tenant")
        net = await conn.fetchval(
            "SELECT COALESCE(SUM(CASE WHEN side='debit' THEN amount_cents "
            "ELSE -amount_cents END), 0) FROM entries "
            "WHERE tenant_id=$1 AND account_id=$2",
            tenant, account["id"],
        )
    payload = {
        "account_code": code,
        "currency": account["currency"],
        "balance_cents": int(net),  # convention: somme(débits) - somme(crédits)
    }
    await get_cache().set(cache_key, json.dumps(payload), ex=settings.cache_ttl_s)
    return {**payload, "cached": False}


@app.post("/reconcile", status_code=202)
async def trigger_reconcile(tenant: str = Depends(require_tenant)):
    async with get_pool().acquire() as conn:
        run = await conn.fetchrow(
            "INSERT INTO reconciliation_runs (tenant_id, status) VALUES ($1,'queued') "
            "RETURNING id, status, requested_at",
            tenant,
        )
    await publish(
        f"{settings.nats_stream.lower()}.reconcile.requested",
        {"run_id": str(run["id"]), "tenant": tenant},
    )
    return {"run_id": str(run["id"]), "status": run["status"]}


@app.get("/reconcile/{run_id}")
async def reconcile_status(run_id: str, tenant: str = Depends(require_tenant)):
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, status, matched_count, unmatched_count, requested_at, completed_at "
            "FROM reconciliation_runs WHERE tenant_id=$1 AND id=$2",
            tenant, run_id,
        )
    if row is None:
        raise HTTPException(status_code=404, detail="Run inconnu pour ce tenant")
    return dict(row)
