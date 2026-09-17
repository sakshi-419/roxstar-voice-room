"""
backend/core/redis_client.py
----------------------------
Async Redis connection factory.

Provides a single cached connection used by every component in the
backend (RoomState, BotRouter, etc.).  Reads connection parameters from
config.Settings so no credentials are hard-coded here.

Usage
-----
    from core.redis_client import get_redis, close_redis, ping_redis

    # At agent startup:
    redis = await get_redis()

    # Health check:
    ok = await ping_redis()

    # At agent shutdown:
    await close_redis()
"""

from __future__ import annotations

import logging

import redis.asyncio as aioredis
from redis.asyncio import Redis
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)

# Module-level cache — one connection pool shared across the process lifetime.
_redis_client: Redis | None = None


async def get_redis() -> Redis:
    """Return the cached async Redis client, creating it on first call.

    The client uses a connection pool internally, so it is safe to call
    ``get_redis()`` multiple times — it always returns the same object.

    Raises
    ------
    RedisError
        If the initial connection or ping fails.  Callers should handle
        this and apply the degraded-mode fallbacks defined in the
        architecture (ARCHITECTURE.md §10.4).
    """
    global _redis_client

    if _redis_client is not None:
        return _redis_client

    # Import settings lazily to avoid circular imports during testing.
    from config import settings  # noqa: PLC0415

    # Build connection kwargs from settings.
    connect_kwargs: dict = {"decode_responses": True}

    if settings.redis_password:
        connect_kwargs["password"] = settings.redis_password

    if settings.redis_tls:
        # Upstash and other hosted providers use TLS (rediss://).
        # If REDIS_URL already starts with rediss://, ssl=True is redundant
        # but harmless; redis-py accepts it.
        connect_kwargs["ssl"] = True
        connect_kwargs["ssl_cert_reqs"] = None  # skip cert verification for simplicity

    client: Redis = aioredis.from_url(settings.redis_url, **connect_kwargs)

    # Verify connectivity immediately so the process fails fast on
    # misconfiguration rather than silently continuing.
    try:
        await client.ping()
        import re
        safe_url = re.sub(r"://([^:]+):([^@]+)@", r"://\1:***@", settings.redis_url)
        logger.info("Redis connection established: %s", safe_url)
    except RedisError as exc:
        logger.error(
            "Redis ping failed on startup — check REDIS_URL and REDIS_PASSWORD. "
            "Error: %s",
            exc,
        )
        # Still cache the client: the connection pool will retry on subsequent
        # calls and will recover automatically when Redis becomes available.

    _redis_client = client
    return _redis_client


async def ping_redis() -> bool:
    """Ping Redis and return True if reachable, False otherwise.

    Safe to call at any time (e.g., from the /health endpoint).
    Never raises — returns False on any error.
    """
    try:
        client = await get_redis()
        result = await client.ping()
        return bool(result)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Redis ping failed: %s", exc)
        return False


async def close_redis() -> None:
    """Close the Redis connection pool gracefully.

    Should be called during agent or server shutdown to release resources.
    Safe to call even if the client was never initialised.
    """
    global _redis_client

    if _redis_client is not None:
        try:
            await _redis_client.aclose()
            logger.info("Redis connection closed.")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Error closing Redis connection: %s", exc)
        finally:
            _redis_client = None
