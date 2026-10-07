"""Cache Redis (redis.asyncio)."""
from __future__ import annotations

import asyncio
import logging

import redis.asyncio as redis

logger = logging.getLogger(__name__)

_client: redis.Redis | None = None


async def init_cache(settings) -> redis.Redis:
    global _client
    if _client is not None:
        return _client
    if not settings.redis_url:
        raise RuntimeError("REDIS_URL non configurée")

    for attempt in range(1, 31):
        try:
            client = redis.from_url(settings.redis_url, decode_responses=True)
            await client.ping()
            _client = client
            logger.info("Redis prêt (tentative %d)", attempt)
            return _client
        except Exception as exc:  # pragma: no cover
            logger.warning("Redis injoignable (%d/30): %s", attempt, exc)
            await asyncio.sleep(1.0)
    raise RuntimeError("Connexion Redis impossible")


def get_cache() -> redis.Redis:
    if _client is None:
        raise RuntimeError("Cache non initialisé (init_cache non appelé)")
    return _client


async def close_cache() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


async def ping_cache() -> bool:
    try:
        return bool(await get_cache().ping())
    except Exception:  # pragma: no cover
        return False
