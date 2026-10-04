"""Accès PostgreSQL (pool asyncpg) avec connexion résiliente au démarrage."""
from __future__ import annotations

import asyncio
import logging

import asyncpg

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None


async def init_db(settings) -> asyncpg.Pool:
    """Crée le pool. Réessaie tant que la base n'est pas joignable (ordre de boot)."""
    global _pool
    if _pool is not None:
        return _pool
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL non configurée")

    last_exc: Exception | None = None
    for attempt in range(1, settings.db_connect_retries + 1):
        try:
            _pool = await asyncpg.create_pool(
                dsn=settings.database_url,
                min_size=settings.db_pool_min,
                max_size=settings.db_pool_max,
                command_timeout=30,
            )
            logger.info("Pool PostgreSQL prêt (tentative %d)", attempt)
            return _pool
        except Exception as exc:  # pragma: no cover - dépend de l'infra
            last_exc = exc
            logger.warning("PostgreSQL injoignable (%d/%d): %s", attempt,
                           settings.db_connect_retries, exc)
            await asyncio.sleep(settings.db_connect_backoff_s)
    raise RuntimeError(f"Connexion PostgreSQL impossible: {last_exc}")


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("Pool non initialisé (init_db non appelé)")
    return _pool


async def close_db() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def ping_db() -> bool:
    try:
        async with get_pool().acquire() as conn:
            await conn.execute("SELECT 1")
        return True
    except Exception:  # pragma: no cover
        return False
