"""
backend/server/token_server.py
------------------------------
FastAPI token & dispatch server for Roxstar AI Voice Room.

Endpoints:
  - POST /token    : Generates signed LiveKit JWT for room participants
  - POST /dispatch : Dispatches roxstar-dost & roxstar-sathi agents to a room
  - GET  /health   : Health status reporting backend & Redis connectivity
"""

from __future__ import annotations

import logging
from datetime import timedelta

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from config import settings
from core.redis_client import ping_redis
from livekit.api import (
    AccessToken,
    CreateAgentDispatchRequest,
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

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Pydantic Request & Response Models ─────────────────────────────────────────

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
    status: str


class HealthResponse(BaseModel):
    status: str
    redis: bool


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Check service health and Redis connectivity."""
    redis_ok = await ping_redis()
    return HealthResponse(
        status="ok",
        redis=redis_ok,
    )


@app.post("/token", response_model=TokenResponse)
async def create_token(req: TokenRequest) -> TokenResponse:
    """Generate a signed LiveKit access token for a human participant.

    The API key and secret are used exclusively server-side to sign the JWT.
    Only the signed JWT and client-safe WebSocket URL are returned to the client.
    """
    if not settings.livekit_url or not settings.livekit_api_key or not settings.livekit_api_secret:
        logger.error("LiveKit credentials not configured in backend settings")
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


@app.post("/dispatch", response_model=DispatchResponse)
async def dispatch_agents(req: DispatchRequest) -> DispatchResponse:
    """Dispatch roxstar-dost and roxstar-sathi to the requested room.

    Operation is idempotent: queries existing room dispatches first to prevent
    duplicate agents from being launched.
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

    try:
        async with LiveKitAPI(
            url=settings.livekit_url,
            api_key=settings.livekit_api_key,
            api_secret=settings.livekit_api_secret,
        ) as lk:
            # Query existing dispatches for idempotency
            try:
                existing = await lk.agent_dispatch.list_dispatch(room_name)
                active_agent_names = {d.agent_name for d in existing}
            except Exception as exc:
                logger.warning("Could not query existing agent dispatches: %s", exc)
                active_agent_names = set()

            for agent in target_agents:
                if agent in active_agent_names:
                    already_running.append(agent)
                    continue

                try:
                    await lk.agent_dispatch.create_dispatch(
                        CreateAgentDispatchRequest(
                            agent_name=agent,
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

    uvicorn.run(
        "server.token_server:app",
        host="0.0.0.0",
        port=settings.token_server_port,
        reload=False,
    )
