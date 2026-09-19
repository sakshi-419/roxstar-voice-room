"""
backend/core/redis_client.py
----------------------------
Loop-safe Async Redis connection factory with native Upstash TLS support.

Binds Redis connection instances to the current running asyncio event loop.
This prevents 'got Future attached to a different loop' errors when LiveKit
worker or FastAPI server processes concurrent requests across event loops.
"""

from __future__ import annotations

import asyncio
import logging
import re

import redis.asyncio as aioredis
from redis.asyncio import Redis
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)

# Map each event loop to its dedicated Redis client instance
_loop_clients: dict[asyncio.AbstractEventLoop, Redis] = {}


def _mask_url(url: str) -> str:
    """Safely mask password in redis connection URLs for logging."""
    return re.sub(r"://([^:]+):([^@]+)@", r"://\1:***@", url)


async def get_redis() -> Redis:
    """Return the loop-safe async Redis client, creating it for the current loop if needed."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.get_event_loop()

    client = _loop_clients.get(loop)
    if client is not None:
        return client

    from config import settings

    raw_url = (settings.redis_url or "").strip().strip('"').strip("'")
    if not raw_url:
        raw_url = "redis://localhost:6379/0"

    is_tls = raw_url.startswith("rediss://") or bool(settings.redis_tls)

    connect_kwargs: dict = {
        "decode_responses": True,
        "socket_timeout": 5.0,
        "socket_connect_timeout": 5.0,
    }

    if settings.redis_password:
        connect_kwargs["password"] = settings.redis_password

    # Note: For rediss:// URLs, redis-py selects SSLConnection automatically.
    # We pass ssl_cert_reqs='none' to avoid SSL verification failures in containerized cloud environments (e.g. Render).
    # We DO NOT pass 'ssl=True' as that causes a TypeError in redis-py 8.x.
    if is_tls:
        connect_kwargs["ssl_cert_reqs"] = "none"

    client = aioredis.from_url(raw_url, **connect_kwargs)

    try:
        await asyncio.wait_for(client.ping(), timeout=5.0)
        logger.info("Redis connection established on loop %s: %s", id(loop), _mask_url(raw_url))
        _loop_clients[loop] = client
    except Exception as exc:
        logger.warning("Redis initial ping failed on loop %s for %s: %s", id(loop), _mask_url(raw_url), exc)
        # Return client but do not cache broken client so subsequent calls can retry
        return client

    return client


async def ping_redis() -> bool:
    """Ping Redis with a 3-second timeout and return True if reachable, False otherwise."""
    try:
        client = await get_redis()
        result = await asyncio.wait_for(client.ping(), timeout=3.0)
        return bool(result)
    except Exception as exc:
        logger.warning("Redis ping failed: %s", exc)
        # Evict potentially broken client so next call reconnects fresh
        try:
            loop = asyncio.get_running_loop()
            _loop_clients.pop(loop, None)
        except RuntimeError:
            pass
        return False


async def close_redis() -> None:
    """Close the Redis connection pool for the current event loop."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop in _loop_clients:
        client = _loop_clients.pop(loop)
        try:
            await client.aclose()
            logger.info("Redis connection closed for loop %s.", id(loop))
        except Exception as exc:
            logger.warning("Error closing Redis connection: %s", exc)
