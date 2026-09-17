"""
backend/scripts/verify_redis.py
-------------------------------
Verification script to test connection to the Redis database (Upstash)
using the existing backend configuration and async Redis client.

Prints only safe status messages without exposing any credentials.
"""

from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

# Ensure backend root directory is in sys.path
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _sanitize_error(exc: Exception) -> str:
    """Mask any credential patterns in error messages to prevent leakage."""
    msg = str(exc)
    # Mask password patterns like :password@
    msg = re.sub(r"://([^:]+):([^@]+)@", r"://\1:***@", msg)
    msg = re.sub(r"password=['\"][^'\"]+['\"]", "password='***'", msg, flags=re.IGNORECASE)
    return msg


async def main() -> int:
    try:
        from config import settings
        from core.redis_client import close_redis, get_redis
    except Exception as exc:
        print(f"Failed to load backend configuration/client: {_sanitize_error(exc)}")
        return 1

    try:
        # Obtain client using existing backend client factory
        client = await get_redis()

        # 1. Ping Redis
        is_alive = await client.ping()
        if not is_alive:
            print("Redis PING: FAILED (ping returned non-truthy value)")
            return 1
        print("Redis PING: OK")

        # 2. SET key "test:roxstar:ping" to "hello"
        test_key = "test:roxstar:ping"
        test_val = "hello"
        await client.set(test_key, test_val)

        # 3. GET the same key and verify
        retrieved_val = await client.get(test_key)
        if retrieved_val == test_val:
            print("Redis SET/GET: OK")
        else:
            print(f"Redis SET/GET: FAILED (expected {test_val!r}, got {retrieved_val!r})")
            return 1

        # Clean up test key
        await client.delete(test_key)

        return 0

    except Exception as exc:
        print(f"Redis connection error: {_sanitize_error(exc)}")
        return 1

    finally:
        # Ensure clean disconnection
        try:
            await close_redis()
        except Exception:
            pass


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
