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
import os
import re
from urllib.parse import urlparse

import redis.asyncio as aioredis
from redis.asyncio import Redis

logger = logging.getLogger(__name__)

# Legacy compatibility attribute
_redis_client = None

# Map each event loop to its dedicated Redis client instance
_loop_clients: dict[asyncio.AbstractEventLoop, Redis] = {}


def _mask_url(url: str) -> str:
    """Safely mask password in redis connection URLs for logging."""
    return re.sub(r"://([^:]+):([^@]+)@", r"://\1:***@", url)


def get_configured_redis_url() -> str:
    """Retrieve Redis URL from environment variables or settings, with fallback."""
    from config import settings

    raw = (
        os.getenv("REDIS_URL")
        or os.getenv("UPSTASH_REDIS_URL")
        or os.getenv("REDIS_URI")
        or getattr(settings, "redis_url", "")
        or "redis://localhost:6379/0"
    ).strip().strip('"').strip("'")
    return raw or "redis://localhost:6379/0"


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

    raw_url = get_configured_redis_url()
    is_tls = raw_url.startswith("rediss://") or bool(getattr(settings, "redis_tls", False))

    connect_kwargs: dict = {
        "decode_responses": True,
        "socket_timeout": 5.0,
        "socket_connect_timeout": 5.0,
        "retry_on_timeout": True,
    }

    password = os.getenv("REDIS_PASSWORD") or getattr(settings, "redis_password", "")
    if password:
        connect_kwargs["password"] = password

    # For rediss:// URLs, redis-py selects SSLConnection automatically.
    # We pass ssl_cert_reqs='none' to avoid SSL verification failures in containerized cloud environments (e.g. Render).
    # We DO NOT pass 'ssl=True' as that causes a TypeError in redis-py 8.x.
    if is_tls:
        connect_kwargs["ssl_cert_reqs"] = "none"

    client = aioredis.from_url(raw_url, **connect_kwargs)
    _loop_clients[loop] = client
    return client


async def check_redis_health() -> tuple[bool, dict]:
    """Test Redis connectivity and return (is_healthy, safe_diagnostic_info).

    Safe diagnostic contains ONLY non-secret metadata (scheme, masked endpoint, error category).
    No credentials or tokens are ever returned.
    """
    raw_url = get_configured_redis_url()

    # Parse non-sensitive diagnostic info
    parsed_scheme = "unknown"
    safe_endpoint = "unknown"
    is_configured = False
    try:
        p = urlparse(raw_url)
        parsed_scheme = p.scheme or "empty"
        if p.hostname:
            port_str = f":{p.port}" if p.port else ""
            safe_endpoint = f"{p.hostname}{port_str}"
            is_configured = "localhost" not in p.hostname and "127.0.0.1" not in p.hostname
    except Exception:
        pass

    diag: dict = {
        "configured": is_configured,
        "scheme": parsed_scheme,
        "endpoint": safe_endpoint,
        "error": None,
    }

    try:
        client = await get_redis()
        pong = await asyncio.wait_for(client.ping(), timeout=3.5)
        if pong:
            return True, diag
        else:
            diag["error"] = "Ping returned falsy value"
            return False, diag
    except Exception as exc:
        err_type = type(exc).__name__
        err_msg = str(exc)
        safe_msg = re.sub(r"://([^:]+):([^@]+)@", r"://\1:***@", err_msg)
        diag["error"] = f"{err_type}: {safe_msg}" if safe_msg else err_type
        logger.warning("Redis health check failed for %s: %s", safe_endpoint, diag["error"])

        # Evict potentially broken client so next call reconnects fresh
        try:
            loop = asyncio.get_running_loop()
            broken = _loop_clients.pop(loop, None)
            if broken:
                asyncio.create_task(broken.aclose())
        except Exception:
            pass
        return False, diag


async def ping_redis() -> bool:
    """Backward-compatible helper returning boolean."""
    ok, _ = await check_redis_health()
    return ok


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
