"""
backend/server/main.py
----------------------
LiveKit Agents worker server for Roxstar AI Voice Room.

Phase 2 & 3:
  - roxstar-dost  : Fully integrated voice agent with Deepgram STT,
                    Google Gemini LLM, ElevenLabs TTS, RoomState memory,
                    and LatencyTracker.
  - roxstar-sathi : Phase 1 worker stub (full Sathi pipeline implemented in Phase 5).

Can run as:
  1. A unified development worker dispatching to appropriate handler based on job.agent_name.
  2. Dedicated processes by setting AGENT_NAME=roxstar-dost or AGENT_NAME=roxstar-sathi.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

# Ensure backend root is in sys.path
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from agents.dost_agent import DostAgent
from config import settings
from core.latency_tracker import LatencyTracker
from core.logger import configure_logging, get_logger
from core.room_state import RoomState, TurnRecord
from livekit.agents import (
    APIConnectOptions,
    AgentServer,
    AgentSession,
    AutoSubscribe,
    JobContext,
    cli,
    llm,
    metrics,
)
from livekit.agents.voice import (
    ConversationItemAddedEvent,
    ErrorEvent,
    MetricsCollectedEvent,
)
from livekit.agents.voice.agent_session import SessionConnectOptions
from livekit.plugins import silero
from providers.llm import build_llm
from providers.stt import build_stt
from providers.tts import build_tts

configure_logging(settings.log_level)
logger = get_logger("roxstar.agent_server")

# Optional environment variable to bind this worker to a specific persona
AGENT_NAME = os.getenv("AGENT_NAME", "").strip()

server = AgentServer(
    ws_url=settings.livekit_url,
    api_key=settings.livekit_api_key,
    api_secret=settings.livekit_api_secret,
)


async def dost_entrypoint(ctx: JobContext) -> None:
    """Roxstar AI Dost — End-to-end voice pipeline (Phase 3)."""
    room_name = ctx.room.name
    logger.info("dost_job_received", room=room_name, job_id=ctx.job.id)

    try:
        # 1. Initialize session-scoped RoomState and LatencyTracker
        state = RoomState(room_name=room_name)
        tracker = LatencyTracker()

        # 2. Build STT, LLM, TTS providers with automatic fallbacks (15s LLM timeout)
        stt_provider = build_stt()
        llm_provider = build_llm(timeout=15.0)
        tts_provider = build_tts("dost")
        vad_provider = silero.VAD.load()

        # 3. Create AgentSession with voice activity detection, interruption support & 15s LLM timeout
        session = AgentSession(
            stt=stt_provider,
            vad=vad_provider,
            llm=llm_provider,
            tts=tts_provider,
            allow_interruptions=True,
            conn_options=SessionConnectOptions(
                llm_conn_options=APIConnectOptions(
                    max_retry=3,
                    retry_interval=2.0,
                    timeout=15.0,
                ),
            ),
        )

        # 4. Attach telemetry and turn tracking listeners
        @session.on("metrics_collected")
        def on_metrics_collected(ev: MetricsCollectedEvent) -> None:
            m = ev.metrics
            if isinstance(m, metrics.STTMetrics):
                tracker.record("stt", m.duration * 1000.0, extra={"room": room_name})
            elif isinstance(m, metrics.LLMMetrics):
                dur = (m.ttft if m.ttft is not None else m.duration) * 1000.0
                tracker.record("llm", dur, extra={"room": room_name})
            elif isinstance(m, metrics.TTSMetrics):
                dur = (m.ttfb if m.ttfb is not None else m.duration) * 1000.0
                tracker.record("tts", dur, extra={"room": room_name})

        @session.on("conversation_item_added")
        def on_item_added(ev: ConversationItemAddedEvent) -> None:
            item = ev.item
            if isinstance(item, llm.ChatMessage) and item.role == "assistant":
                text = item.text_content
                if text:
                    turn = TurnRecord(
                        speaker_id="dost",
                        speaker_name="Dost",
                        text=text,
                        bot_name="roxstar-dost",
                    )
                    asyncio.create_task(state.add_turn(turn))

        @session.on("error")
        def on_session_error(ev: ErrorEvent) -> None:
            logger.error("agent_session_error", room=room_name, error=str(ev.error))

        # 5. Initialize Dost Agent with persona instructions and greeting
        agent = DostAgent(state=state, latency_tracker=tracker)

        # 6. Start the agent session connected to the room
        logger.info("starting_dost_agent_session", room=room_name)
        await session.start(agent, room=ctx.room)
        logger.info("dost_agent_session_active", room=room_name)

    except Exception as exc:
        logger.error(
            "dost_entrypoint_failed",
            room=room_name,
            error=str(exc),
            exc_info=True,
        )
        # Fallback to keep participant connection alive without crashing worker
        try:
            await ctx.connect(auto_subscribe=AutoSubscribe.SUBSCRIBE_ALL)
        except Exception:
            pass


async def sathi_entrypoint(ctx: JobContext) -> None:
    """Handler for Roxstar AI Sathi (Phase 1 stub; full pipeline in Phase 5)."""
    logger.info("sathi_job_received", room=ctx.room.name)
    await ctx.connect(auto_subscribe=AutoSubscribe.SUBSCRIBE_ALL)
    logger.info("sathi_connected", room=ctx.room.name)


HANDLERS = {
    "roxstar-dost": dost_entrypoint,
    "roxstar-sathi": sathi_entrypoint,
}


@server.rtc_session(agent_name=AGENT_NAME)
async def entrypoint(ctx: JobContext) -> None:
    """Main job router: resolves the dispatched agent name and delegates to its handler."""
    target_agent = ctx.job.agent_name or AGENT_NAME or "roxstar-dost"
    logger.info("routing_agent_job", target_agent=target_agent, room=ctx.room.name)

    handler = HANDLERS.get(target_agent)
    if handler:
        await handler(ctx)
    else:
        logger.warning(
            "unknown_agent_target_falling_back_to_dost",
            target_agent=target_agent,
        )
        await dost_entrypoint(ctx)


if __name__ == "__main__":
    cli.run_app(server)
