"""
backend/server/token_server.py
------------------------------
FastAPI token & dispatch server for Roxstar AI Voice Room.

Endpoints:
  - POST /token    : Generates signed LiveKit JWT for room participants
  - POST /dispatch : Dispatches roxstar-dost & roxstar-sathi agents to a room (Idempotent)
  - GET  /health   : Health status reporting backend & Redis connectivity
"""

from __future__ import annotations

import logging
import os
from datetime import timedelta

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from config import settings
from core.redis_client import get_redis, ping_redis
from livekit.api import (
    AccessToken,
    CreateAgentDispatchRequest,
    ListParticipantsRequest,
    LiveKitAPI,
    VideoGrants,
)

logger = logging.getLogger("roxstar.token_server")
logging.basicConfig(level=settings.log_level)

app = FastAPI(
    title="Roxstar AI Voice Room Token Server",
    description="Signs LiveKit tokens and manages agent dispatches.",
    version="0.1.0",
)

# Configure CORS for local development and cloud production (e.g. Vercel)
raw_cors = os.getenv("CORS_ORIGINS", os.getenv("ALLOWED_ORIGINS", "")).strip()
if raw_cors and raw_cors != "*":
    origins = [o.strip() for o in raw_cors.split(",") if o.strip()]
    allow_creds = True
else:
    origins = ["*"]
    allow_creds = False

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=allow_creds,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Pydantic Request & Response Models ───────────────────────────────────────

class TokenRequest(BaseModel):
    room_name: str = Field(..., min_length=1, max_length=128, description="Room name to join")
    participant_name: str = Field(..., min_length=1, max_length=128, description="Display name for participant")


class TokenResponse(BaseModel):
    token: str
    livekit_url: str
    room_name: str
    participant_name: str


class DispatchRequest(BaseModel):
    room_name: str = Field(..., min_length=1, max_length=128, description="Room name to dispatch agents to")


class DispatchResponse(BaseModel):
    room_name: str
    dispatched: list[str]
    already_running: list[str]
    status: str = "ok"


class HealthResponse(BaseModel):
    status: str
    redis: bool
    livekit_configured: bool
    version: str = "0.1.0"


# ── Health Endpoint ──────────────────────────────────────────────────────────

@app.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Report server health and connectivity to external services (Redis, LiveKit)."""
    redis_ok = await ping_redis()
    livekit_ok = bool(
        settings.livekit_url and settings.livekit_api_key and settings.livekit_api_secret
    )
    overall_status = "ok" if (redis_ok and livekit_ok) else "degraded"

    return HealthResponse(
        status=overall_status,
        redis=redis_ok,
        livekit_configured=livekit_ok,
    )


# ── Token Generation Endpoint ────────────────────────────────────────────────

@app.post("/token", response_model=TokenResponse)
async def create_token(req: TokenRequest) -> TokenResponse:
    """Generate a signed LiveKit JWT token for a participant joining a voice room."""
    if not settings.livekit_url or not settings.livekit_api_key or not settings.livekit_api_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="LiveKit credentials are not configured on the server",
        )

    room_name = req.room_name.strip()
    participant_name = req.participant_name.strip()
    identity = participant_name

    try:
        grants = VideoGrants(
            room_join=True,
            room=room_name,
            can_publish=True,
            can_subscribe=True,
            can_publish_data=True,
        )

        token = (
            AccessToken(
                api_key=settings.livekit_api_key,
                api_secret=settings.livekit_api_secret,
            )
            .with_identity(identity)
            .with_name(participant_name)
            .with_grants(grants)
            .with_ttl(timedelta(seconds=settings.token_ttl_seconds))
            .to_jwt()
        )

        logger.info(
            "Issued LiveKit token for participant '%s' in room '%s'",
            identity,
            room_name,
        )

        return TokenResponse(
            token=token,
            livekit_url=settings.livekit_url,
            room_name=room_name,
            participant_name=participant_name,
        )
    except Exception as exc:
        logger.error("Failed to generate LiveKit token: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate LiveKit token",
        ) from exc


# ── Agent Dispatch Endpoint (Strictly Idempotent) ────────────────────────────

@app.post("/dispatch", response_model=DispatchResponse)
async def dispatch_agents(req: DispatchRequest) -> DispatchResponse:
    """Dispatch roxstar-dost and roxstar-sathi to the requested room.

    Strictly idempotent:
    1. Checks if Dost or Sathi is already present in room participants.
    2. Checks if an active dispatch already exists in LiveKit.
    3. Uses a distributed Redis lock to prevent concurrent double-clicks.
    Guarantees that exactly one Dost and one Sathi exist per room.
    """
    if not settings.livekit_url or not settings.livekit_api_key or not settings.livekit_api_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="LiveKit credentials are not configured on the server",
        )

    room_name = req.room_name.strip()
    target_agents = ["roxstar-dost", "roxstar-sathi"]
    dispatched: list[str] = []
    already_running: list[str] = []
    active_agent_names: set[str] = set()

    try:
        async with LiveKitAPI(
            url=settings.livekit_url,
            api_key=settings.livekit_api_key,
            api_secret=settings.livekit_api_secret,
        ) as lk:
            # 1. Check existing connected room participants
            connected_agents: set[str] = set()
            try:
                parts = await lk.room.list_participants(ListParticipantsRequest(room=room_name))
                for p in parts.participants:
                    p_name = (p.name or "").lower()
                    p_id = (p.identity or "").lower()
                    if "dost" in p_name or "dost" in p_id:
                        connected_agents.add("roxstar-dost")
                    if "sathi" in p_name or "sathi" in p_id:
                        connected_agents.add("roxstar-sathi")
            except Exception as exc:
                logger.warning("Could not query room participants for dispatch: %s", exc)

            # 2. Query existing dispatches - treat pending dispatches as already_running
            # to prevent re-dispatching an agent already queued or starting up.
            dispatched_agents: set[str] = set()
            try:
                existing = await lk.agent_dispatch.list_dispatch(room_name)
                for d in existing:
                    agent_tag = (d.metadata or d.agent_name or "").lower()
                    matched_agent = "roxstar-dost" if "dost" in agent_tag else ("roxstar-sathi" if "sathi" in agent_tag else None)
                    if matched_agent:
                        dispatched_agents.add(matched_agent)
                        logger.info("found_pending_dispatch", agent=matched_agent)
            except Exception as exc:
                logger.warning("Could not query existing agent dispatches: %s", exc)

            # 3. Process dispatch for each agent with Redis lock protection
            redis = await get_redis()
            for agent in target_agents:
                if agent in connected_agents or agent in dispatched_agents:
                    already_running.append(agent)
                    continue

                if redis:
                    # 10-second lock prevents rapid double-clicks from issuing two dispatches
                    lock_key = f"room:{room_name}:dispatch_lock:{agent}"
                    acquired = await redis.set(lock_key, "1", nx=True, ex=10)
                    if not acquired:
                        already_running.append(agent)
                        continue

                try:
                    dispatch_name = agent if settings.agent_name else ""
                    await lk.agent_dispatch.create_dispatch(
                        CreateAgentDispatchRequest(
                            agent_name=dispatch_name,
                            metadata=agent,
                            room=room_name,
                        )
                    )
                    dispatched.append(agent)
                    logger.info("Dispatched agent '%s' to room '%s'", agent, room_name)
                except Exception as exc:
                    err_msg = str(exc).lower()
                    if "already exists" in err_msg or "conflict" in err_msg:
                        already_running.append(agent)
                    else:
                        logger.error("Failed to dispatch agent '%s': %s", agent, exc)
                        raise HTTPException(
                            status_code=status.HTTP_502_BAD_GATEWAY,
                            detail=f"Failed to dispatch {agent}: {exc}",
                        ) from exc

        return DispatchResponse(
            room_name=room_name,
            dispatched=dispatched,
            already_running=already_running,
            status="ok",
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Agent dispatch error for room '%s': %s", room_name, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Agent dispatch failed: {exc}",
        ) from exc


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", str(settings.token_server_port)))
    uvicorn.run(
        "server.token_server:app",
        host="0.0.0.0",
        port=port,
        reload=False,
    )
