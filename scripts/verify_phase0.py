"""
scripts/verify_phase0.py
------------------------
Phase 0 verification script.

Run from the backend directory with the virtual environment active:

    uv run python ../scripts/verify_phase0.py

Checks:
  1. Python version >= 3.11
  2. Required packages importable (redis, fastapi, structlog, pydantic_settings)
  3. Redis connectivity: SET + GET round-trip
  4. Redis PING health check via redis_client.get_redis()

Exit code 0 = all checks passed.
Exit code 1 = one or more checks failed.
"""

from __future__ import annotations

import asyncio
import sys
import os

# ── 1. Python version ──────────────────────────────────────────────────────────
print(f"Python version: {sys.version}")
if sys.version_info < (3, 11):
    print("FAIL: Python 3.11+ required.")
    sys.exit(1)
print("PASS: Python version OK.")

# ── 2. Package imports ──────────────────────────────────────────────────────────
required = [
    ("redis.asyncio", "redis (asyncio)"),
    ("fastapi", "fastapi"),
    ("structlog", "structlog"),
    ("pydantic_settings", "pydantic-settings"),
    ("livekit.agents", "livekit-agents"),
    ("uvicorn", "uvicorn"),
]

all_ok = True
for module, label in required:
    try:
        __import__(module)
        print(f"PASS: {label} importable.")
    except ImportError as e:
        print(f"FAIL: {label} import error — {e}")
        all_ok = False

if not all_ok:
    sys.exit(1)

# ── 3 & 4. Redis connectivity ──────────────────────────────────────────────────

# Allow REDIS_URL override via env; default to localhost for CI/local dev.
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("REDIS_PASSWORD", "")
os.environ.setdefault("REDIS_TLS", "false")

# Provide dummy values for required LiveKit settings so Settings() doesn't
# raise on import (we don't need LiveKit for the Redis check).
os.environ.setdefault("LIVEKIT_URL", "wss://placeholder.livekit.cloud")
os.environ.setdefault("LIVEKIT_API_KEY", "APIplaceholder")
os.environ.setdefault("LIVEKIT_API_SECRET", "placeholder_secret_value_32chars!")


async def check_redis() -> bool:
    """Perform SET/GET round-trip and PING check."""
    try:
        import redis.asyncio as aioredis

        redis_url = os.environ["REDIS_URL"]
        client = aioredis.from_url(redis_url, decode_responses=True)

        # PING
        pong = await client.ping()
        if not pong:
            print("FAIL: Redis PING returned falsy.")
            await client.aclose()
            return False
        print(f"PASS: Redis PING → {pong}")

        # SET
        await client.set("test:phase0", "hello_roxstar", ex=30)
        print("PASS: Redis SET test:phase0 hello_roxstar  [EX 30]")

        # GET
        value = await client.get("test:phase0")
        if value != "hello_roxstar":
            print(f"FAIL: Redis GET returned {value!r}, expected 'hello_roxstar'.")
            await client.aclose()
            return False
        print(f"PASS: Redis GET test:phase0 → '{value}'")

        # DEL (cleanup)
        await client.delete("test:phase0")
        print("PASS: Redis DEL test:phase0  (cleanup).")

        await client.aclose()
        return True

    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: Redis error — {exc}")
        print()
        print("      Is Redis running?  Try one of:")
        print("        docker run --rm -p 6379:6379 redis:7-alpine")
        print("        winget install Redis.Redis  (Windows native)")
        print("        Or sign up for a free Upstash account and set REDIS_URL")
        return False


ok = asyncio.run(check_redis())
if not ok:
    sys.exit(1)

print()
print("=" * 60)
print("ALL PHASE 0 CHECKS PASSED.")
print("=" * 60)
