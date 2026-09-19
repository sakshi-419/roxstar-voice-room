"""
backend/core/redis_client.py
----------------------------
Loop-safe Async Redis connection factory.

Binds Redis connection instances to the current running asyncio event loop.
This prevents 'got Future attached to a different loop' errors when LiveKit
worker spawns jobs across multiple tasks and event loops.
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

    connect_kwargs: dict = {"decode_responses": True}

    if settings.redis_password:
        connect_kwargs["password"] = settings.redis_password

    if settings.redis_tls:
        connect_kwargs["ssl"] = True
        connect_kwargs["ssl_cert_reqs"] = None

    client = aioredis.from_url(settings.redis_url, **connect_kwargs)

    try:
        await client.ping()
        safe_url = re.sub(r"://([^:]+):([^@]+)@", r"://\1:***@", settings.redis_url)
        logger.info("Redis connection established on loop %s: %s", id(loop), safe_url)
    except RedisError as exc:
        logger.error("Redis ping failed: %s", exc)

    _loop_clients[loop] = client
    return client


async def ping_redis() -> bool:
    """Ping Redis and return True if reachable, False otherwise."""
    try:
        client = await get_redis()
        result = await client.ping()
        return bool(result)
    except Exception as exc:
        logger.warning("Redis ping failed: %s", exc)
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
