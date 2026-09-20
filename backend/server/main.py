"""
backend/server/main.py
----------------------
LiveKit Agents worker server for Roxstar AI Voice Room.

Phase 2 & 3:
  - roxstar-dost  : Fully integrated voice agent with Deepgram STT,
                    Google Gemini LLM, ElevenLabs TTS, RoomState memory,
                    and LatencyTracker.

Phase 5:
  - roxstar-sathi : Full end-to-end empathetic voice agent with Sathi persona,
                    sathi TTS voice, RoomState memory, and distributed routing.
  - Distributed speaking lock release and post-speech cooldown handling.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
import json
import uuid
import hashlib
from pathlib import Path

# Force UTF-8 encoding on Windows console for Hindi/Hinglish transcripts
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

# Ensure backend root is in sys.path
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from agents.dost_agent import DostAgent
from agents.sathi_agent import SathiAgent
from config import settings
from core.latency_tracker import LatencyTracker
from core.logger import configure_logging, get_logger
from core.room_state import RoomState, TurnRecord
from livekit import rtc
from core.bot_router import BotRouter
from livekit.agents.voice.room_io import RoomInputOptions
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
    AgentStateChangedEvent,
    ConversationItemAddedEvent,
    ErrorEvent,
    MetricsCollectedEvent,
    UserInputTranscribedEvent,
    UserStateChangedEvent,
)
from livekit.agents.voice.agent_session import SessionConnectOptions
from livekit.plugins import silero
try:
    from livekit.plugins import groq, deepgram, elevenlabs
except Exception:
    pass

from providers.llm import build_llm
from providers.stt import build_stt
from providers.tts import build_tts

def _sanitize_for_voice(text: str) -> str:
    """Strip markdown formatting, emoji, and symbols for clean spoken voice output."""
    import re as _re
    if not text:
        return ""
    # Strip markdown bold / italics
    text = _re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = _re.sub(r"\*([^*]+)\*", r"\1", text)
    text = _re.sub(r"__([^_]+)__", r"\1", text)
    text = _re.sub(r"_([^_]+)_", r"\1", text)
    # Strip markdown headers, lists, bullets
    text = _re.sub(r"^[#>\-\*\+]\s+", "", text, flags=_re.MULTILINE)
    # Strip code backticks
    text = _re.sub(r"`+([^`]+)`+", r"\1", text)
    # Strip markdown links
    text = _re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)
    # Remove non-printable / emoji outside standard range
    cleaned = _re.sub(r"[^\x09\x0A\x0D\x20-\x7E\u00C0-\u024F\u0900-\u097F]", "", text)
    # Collapse multiple spaces
    cleaned = _re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or text


configure_logging(settings.log_level)
logger = get_logger("roxstar.agent_server")

# Optional environment variable to bind this worker to a specific persona
AGENT_NAME = os.getenv("AGENT_NAME", "").strip()

server = AgentServer(
    ws_url=settings.livekit_url or None,
    api_key=settings.livekit_api_key or None,
    api_secret=settings.livekit_api_secret or None,
)


async def dost_entrypoint(ctx: JobContext) -> None:
    """Roxstar AI Dost — End-to-end voice pipeline (Phase 3 & 5)."""
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
            min_endpointing_delay=0.25,
            max_endpointing_delay=0.8,
            conn_options=SessionConnectOptions(
                max_unrecoverable_errors=100,
                llm_conn_options=APIConnectOptions(
                    max_retry=5,
                    retry_interval=3.0,
                    timeout=30.0,
                ),
                tts_conn_options=APIConnectOptions(
                    max_retry=5,
                    retry_interval=2.0,
                    timeout=20.0,
                ),
            ),
        )

        # 4. Attach telemetry, boundary logs, latency tracking, and turn listeners
        t_audio_recv = 0.0
        stt_dur_ms = 0.0
        llm_dur_ms = 0.0
        tts_dur_ms = 0.0

        @session.on("user_state_changed")
        def on_user_state_changed(ev: UserStateChangedEvent) -> None:
            nonlocal t_audio_recv
            if str(getattr(ev, "new_state", "")).lower() == "speaking":
                t_audio_recv = time.time()
                # Barge-in: interrupt active speech immediately so human takes precedence
                try:
                    session.interrupt()
                except Exception:
                    pass
                asyncio.create_task(state.release_speaking_lock("roxstar-dost"))
                logger.info("USER_AUDIO_RECEIVED", room=room_name)
                logger.info("STT_STARTED", room=room_name)

        @session.on("user_input_transcribed")
        def on_user_input_transcribed(ev: UserInputTranscribedEvent) -> None:
            nonlocal stt_dur_ms
            speaker_id = getattr(ev, "speaker_id", None)
            if speaker_id and hasattr(agent, "set_last_speaker"):
                agent.set_last_speaker(speaker_id)
            if getattr(ev, "is_final", False) and getattr(ev, "transcript", ""):
                if t_audio_recv > 0:
                    stt_dur_ms = (time.time() - t_audio_recv) * 1000.0
                logger.info("STT_TRANSCRIPT", text=ev.transcript[:100], room=room_name)

        @session.on("metrics_collected")
        def on_metrics_collected(ev: MetricsCollectedEvent) -> None:
            nonlocal stt_dur_ms, llm_dur_ms, tts_dur_ms
            m = ev.metrics
            if isinstance(m, metrics.STTMetrics):
                stt_dur_ms = m.duration * 1000.0
                tracker.record("stt", stt_dur_ms, extra={"room": room_name})
            elif isinstance(m, metrics.LLMMetrics):
                llm_dur_ms = (m.ttft if m.ttft is not None else m.duration) * 1000.0
                tracker.record("llm", llm_dur_ms, extra={"room": room_name})
            elif isinstance(m, metrics.TTSMetrics):
                tts_dur_ms = (m.ttfb if m.ttfb is not None else m.duration) * 1000.0
                tracker.record("tts", tts_dur_ms, extra={"room": room_name})
                logger.info("TTS_COMPLETED", bot="roxstar-dost", duration_ms=round(tts_dur_ms, 1), room=room_name)

        @session.on("conversation_item_added")
        def on_item_added(ev: ConversationItemAddedEvent) -> None:
            item = ev.item
            if isinstance(item, llm.ChatMessage) and item.role == "assistant":
                text = item.text_content
                if text:
                    logger.info("LLM_RESPONSE", bot="roxstar-dost", text=text[:100], room=room_name)
                    logger.info("TTS_STARTED", bot="roxstar-dost", room=room_name)
                    turn = TurnRecord(
                        speaker_id="dost",
                        speaker_name="Dost",
                        text=text,
                        bot_name="roxstar-dost",
                    )
                    asyncio.create_task(state.add_turn(turn))
                    try:
                        import json, time, uuid
                        chat_payload = json.dumps({"id": str(uuid.uuid4()), "message": text, "timestamp": int(time.time() * 1000)}).encode("utf-8")
                        asyncio.create_task(ctx.room.local_participant.publish_data(chat_payload, reliable=True, topic="lk-chat-topic"))
                        asyncio.create_task(ctx.room.local_participant.publish_data(json.dumps({"message": text, "sender": "Dost"}).encode("utf-8"), reliable=True, topic="lk.chat"))
                    except Exception:
                        pass
                    # Release speaking lock, activate cooldown, and update last_bot
                    asyncio.create_task(state.release_speaking_lock("roxstar-dost"))
                    asyncio.create_task(state.set_cooldown("roxstar-dost", 1.5))
                    asyncio.create_task(state.set_last_bot("roxstar-dost"))
                    logger.info("TTS_COMPLETE", bot="roxstar-dost", room=room_name)

        @session.on("agent_state_changed")
        def on_state_changed(ev: AgentStateChangedEvent) -> None:
            new_st = str(getattr(ev, "new_state", "")).lower()
            if new_st == "speaking":
                total_ms = (time.time() - t_audio_recv) * 1000.0 if t_audio_recv > 0 else (stt_dur_ms + llm_dur_ms + tts_dur_ms)
                logger.info("AUDIO_RESPONSE_PUBLISHED", bot="roxstar-dost", room=room_name)
                logger.info(
                    "VOICE_LATENCY",
                    bot="roxstar-dost",
                    stt_ms=round(stt_dur_ms, 1),
                    llm_ms=round(llm_dur_ms, 1),
                    tts_ms=round(tts_dur_ms, 1),
                    total_ms=round(total_ms, 1),
                    room=room_name,
                )
            elif new_st in ("idle", "listening"):
                asyncio.create_task(state.release_speaking_lock("roxstar-dost"))

        @session.on("error")
        def on_session_error(ev: ErrorEvent) -> None:
            logger.error("agent_session_error", room=room_name, error=str(ev.error))
            asyncio.create_task(state.release_speaking_lock("roxstar-dost"))

        # 5. Initialize Dost Agent with persona instructions and greeting
        agent = DostAgent(state=state, latency_tracker=tracker)

        # 6. Start the agent session connected to the room
        logger.info("starting_dost_agent_session", room=room_name)
        await session.start(agent, room=ctx.room, room_input_options=RoomInputOptions(participant_kinds=[rtc.ParticipantKind.PARTICIPANT_KIND_STANDARD], close_on_disconnect=False))
        try:
            await ctx.room.local_participant.set_name("Dost")
        except Exception:
            pass
        # 7. Listen for Room Text Chat messages (Requirement 2.3 & Scenarios 1-5)
        @ctx.room.on("data_received")
        def on_data_received(dp: rtc.DataPacket) -> None:
            try:
                raw_bytes = dp.data
                raw_str = raw_bytes.decode("utf-8") if isinstance(raw_bytes, (bytes, bytearray)) else str(raw_bytes)
                chat_text = ""
                try:
                    import json
                    parsed = json.loads(raw_str)
                    chat_text = parsed.get("message") or parsed.get("text") or parsed.get("content") or raw_str
                except Exception:
                    chat_text = raw_str

                chat_text = chat_text.strip()
                if not chat_text:
                    return

                sender_id = getattr(dp.participant, "identity", "User") if dp.participant else "User"
                sender_name = getattr(dp.participant, "name", "") or sender_id if dp.participant else "User"

                sid_l = sender_id.lower()
                sname_l = (sender_name or "").lower()
                if ("dost" in sid_l or "sathi" in sid_l or
                        "dost" in sname_l or "sathi" in sname_l or
                        "roxstar" in sid_l or "agent" in sid_l or
                        (ctx.room.local_participant and sid_l == ctx.room.local_participant.identity.lower())):
                    logger.debug("ai_chat_loop_blocked", sender_id=sender_id, bot="roxstar-dost")
                    return

                if BotRouter.is_stop_command(chat_text):
                    try:
                        session.interrupt()
                    except Exception:
                        pass
                    asyncio.create_task(state.release_speaking_lock("roxstar-dost"))
                    return

                logger.info("TEXT_CHAT_RECEIVED", bot="roxstar-dost", sender=sender_name, text=chat_text[:80].encode("ascii", "replace").decode("ascii"))

                async def handle_chat() -> None:
                    thash = hashlib.md5(chat_text.lower().encode("utf-8")).hexdigest()[:8]
                    turn_id = f"chat:{sender_id}:{int(time.time() / 2.0) * 2}:{thash}"
                    is_winner = await state.claim_voice_ingest(turn_id)
                    from core.bot_router import BotRouter
                    if is_winner:
                        target = await BotRouter.select_bot(state, chat_text)
                        await state.set_voice_route(turn_id, target)
                        await state.add_turn(TurnRecord(speaker_id=sender_id, speaker_name=sender_name, text=chat_text))
                    else:
                        target = await state.wait_for_voice_route(turn_id, timeout_seconds=0.6)
                        if not target:
                            target = await BotRouter.select_bot(state, chat_text)

                    should_respond = (target == "roxstar-dost")
                    if should_respond:
                        lock_ok = await state.acquire_speaking_lock("roxstar-dost", ttl=15)
                        if not lock_ok:
                            await state.release_speaking_lock("roxstar-dost")
                            lock_ok = await state.acquire_speaking_lock("roxstar-dost", ttl=15)
                            if not lock_ok:
                                return
                        try:
                            room_context = await state.build_context_string(n=5)
                            updated_instructions = agent._raw_instructions.format(
                                room_context=room_context,
                                speaker_profile="No prior info.",
                            )
                            await agent.update_instructions(updated_instructions)
                            chat_ctx = llm.ChatContext()
                            chat_ctx.add_message(role="system", content=updated_instructions)
                            chat_ctx.add_message(role="user", content=chat_text)
                            stream = llm_provider.chat(chat_ctx=chat_ctx)
                            reply_text = ""
                            async for chunk in stream:
                                if chunk.delta and chunk.delta.content:
                                    reply_text += chunk.delta.content
                            reply_text = _sanitize_for_voice(reply_text.strip())
                            if not reply_text:
                                reply_text = "Haan dost, main sun raha hoon! Batao kya help chahiye?"

                            chat_payload = json.dumps({"id": str(uuid.uuid4()), "message": reply_text, "timestamp": int(time.time() * 1000)}).encode("utf-8")
                            await ctx.room.local_participant.publish_data(chat_payload, reliable=True, topic="lk-chat-topic")
                            await ctx.room.local_participant.publish_data(json.dumps({"message": reply_text, "sender": "Dost"}).encode("utf-8"), reliable=True, topic="lk.chat")

                            turn = TurnRecord(speaker_id="dost", speaker_name="Dost", text=reply_text, bot_name="roxstar-dost")
                            await state.add_turn(turn)
                            await state.set_last_bot("roxstar-dost")

                            try:
                                await session.say(reply_text, allow_interruptions=True)
                            except Exception as say_err:
                                logger.error("dost_say_error", error=str(say_err))
                        except Exception as exc:
                            logger.error("dost_chat_reply_failed", error=str(exc))
                        finally:
                            await state.release_speaking_lock("roxstar-dost")
                            await state.set_cooldown("roxstar-dost", 1.0)

                asyncio.create_task(handle_chat())
            except Exception as exc:
                logger.error("text_chat_error", bot="roxstar-dost", error=str(exc))

        logger.info("dost_agent_session_active", room=room_name)

    except Exception as exc:
        logger.error(
            "dost_entrypoint_failed",
            room=room_name,
            error=str(exc),
            exc_info=True,
        )
        raise


async def sathi_entrypoint(ctx: JobContext) -> None:
    """Roxstar AI Sathi — End-to-end voice pipeline (Phase 5)."""
    room_name = ctx.room.name
    logger.info("sathi_job_received", room=room_name, job_id=ctx.job.id)

    try:
        # 1. Initialize session-scoped RoomState and LatencyTracker
        state = RoomState(room_name=room_name)
        tracker = LatencyTracker()

        # 2. Build STT, LLM, TTS providers (Sathi voice) with automatic fallbacks
        stt_provider = build_stt()
        llm_provider = build_llm(timeout=15.0)
        tts_provider = build_tts("sathi")
        vad_provider = silero.VAD.load()

        # 3. Create AgentSession with voice activity detection & interruption support
        session = AgentSession(
            stt=stt_provider,
            vad=vad_provider,
            llm=llm_provider,
            tts=tts_provider,
            allow_interruptions=True,
            min_endpointing_delay=0.25,
            max_endpointing_delay=0.8,
            conn_options=SessionConnectOptions(
                max_unrecoverable_errors=100,
                llm_conn_options=APIConnectOptions(
                    max_retry=5,
                    retry_interval=3.0,
                    timeout=30.0,
                ),
                tts_conn_options=APIConnectOptions(
                    max_retry=5,
                    retry_interval=2.0,
                    timeout=20.0,
                ),
            ),
        )

        # 4. Attach telemetry, boundary logs, latency tracking, and turn listeners
        t_audio_recv = 0.0
        stt_dur_ms = 0.0
        llm_dur_ms = 0.0
        tts_dur_ms = 0.0

        @session.on("user_state_changed")
        def on_user_state_changed(ev: UserStateChangedEvent) -> None:
            nonlocal t_audio_recv
            if str(getattr(ev, "new_state", "")).lower() == "speaking":
                t_audio_recv = time.time()
                # Barge-in: interrupt active speech immediately so human takes precedence
                try:
                    session.interrupt()
                except Exception:
                    pass
                asyncio.create_task(state.release_speaking_lock("roxstar-sathi"))
                logger.info("USER_AUDIO_RECEIVED", room=room_name)
                logger.info("STT_STARTED", room=room_name)

        @session.on("user_input_transcribed")
        def on_user_input_transcribed(ev: UserInputTranscribedEvent) -> None:
            nonlocal stt_dur_ms
            speaker_id = getattr(ev, "speaker_id", None)
            if speaker_id and hasattr(agent, "set_last_speaker"):
                agent.set_last_speaker(speaker_id)
            if getattr(ev, "is_final", False) and getattr(ev, "transcript", ""):
                if t_audio_recv > 0:
                    stt_dur_ms = (time.time() - t_audio_recv) * 1000.0
                logger.info("STT_TRANSCRIPT", text=ev.transcript[:100], room=room_name)

        @session.on("metrics_collected")
        def on_metrics_collected(ev: MetricsCollectedEvent) -> None:
            nonlocal stt_dur_ms, llm_dur_ms, tts_dur_ms
            m = ev.metrics
            if isinstance(m, metrics.STTMetrics):
                stt_dur_ms = m.duration * 1000.0
                tracker.record("stt", stt_dur_ms, extra={"room": room_name})
            elif isinstance(m, metrics.LLMMetrics):
                llm_dur_ms = (m.ttft if m.ttft is not None else m.duration) * 1000.0
                tracker.record("llm", llm_dur_ms, extra={"room": room_name})
            elif isinstance(m, metrics.TTSMetrics):
                tts_dur_ms = (m.ttfb if m.ttfb is not None else m.duration) * 1000.0
                tracker.record("tts", tts_dur_ms, extra={"room": room_name})
                logger.info("TTS_COMPLETED", bot="roxstar-sathi", duration_ms=round(tts_dur_ms, 1), room=room_name)

        @session.on("conversation_item_added")
        def on_item_added(ev: ConversationItemAddedEvent) -> None:
            item = ev.item
            if isinstance(item, llm.ChatMessage) and item.role == "assistant":
                text = item.text_content
                if text:
                    logger.info("LLM_RESPONSE", bot="roxstar-sathi", text=text[:100], room=room_name)
                    logger.info("TTS_STARTED", bot="roxstar-sathi", room=room_name)
                    turn = TurnRecord(
                        speaker_id="sathi",
                        speaker_name="Sathi",
                        text=text,
                        bot_name="roxstar-sathi",
                    )
                    asyncio.create_task(state.add_turn(turn))
                    try:
                        import json, time, uuid
                        chat_payload = json.dumps({"id": str(uuid.uuid4()), "message": text, "timestamp": int(time.time() * 1000)}).encode("utf-8")
                        asyncio.create_task(ctx.room.local_participant.publish_data(chat_payload, reliable=True, topic="lk-chat-topic"))
                        asyncio.create_task(ctx.room.local_participant.publish_data(json.dumps({"message": text, "sender": "Sathi"}).encode("utf-8"), reliable=True, topic="lk.chat"))
                    except Exception:
                        pass
                    # Release speaking lock, activate cooldown, and update last_bot
                    asyncio.create_task(state.release_speaking_lock("roxstar-sathi"))
                    asyncio.create_task(state.set_cooldown("roxstar-sathi", 1.5))
                    asyncio.create_task(state.set_last_bot("roxstar-sathi"))

        @session.on("agent_state_changed")
        def on_state_changed(ev: AgentStateChangedEvent) -> None:
            new_st = str(getattr(ev, "new_state", "")).lower()
            if new_st == "speaking":
                total_ms = (time.time() - t_audio_recv) * 1000.0 if t_audio_recv > 0 else (stt_dur_ms + llm_dur_ms + tts_dur_ms)
                logger.info("AUDIO_RESPONSE_PUBLISHED", bot="roxstar-sathi", room=room_name)
                logger.info(
                    "VOICE_LATENCY",
                    bot="roxstar-sathi",
                    stt_ms=round(stt_dur_ms, 1),
                    llm_ms=round(llm_dur_ms, 1),
                    tts_ms=round(tts_dur_ms, 1),
                    total_ms=round(total_ms, 1),
                    room=room_name,
                )
            elif new_st in ("idle", "listening"):
                asyncio.create_task(state.release_speaking_lock("roxstar-sathi"))

        @session.on("error")
        def on_session_error(ev: ErrorEvent) -> None:
            logger.error("agent_session_error", room=room_name, error=str(ev.error))
            asyncio.create_task(state.release_speaking_lock("roxstar-sathi"))

        # 5. Initialize Sathi Agent with persona instructions and greeting
        agent = SathiAgent(state=state, latency_tracker=tracker)

        # 6. Start the agent session connected to the room
        logger.info("starting_sathi_agent_session", room=room_name)
        await session.start(agent, room=ctx.room, room_input_options=RoomInputOptions(participant_kinds=[rtc.ParticipantKind.PARTICIPANT_KIND_STANDARD], close_on_disconnect=False))
        try:
            await ctx.room.local_participant.set_name("Sathi")
        except Exception:
            pass
        # 7. Listen for Room Text Chat messages (Requirement 2.3 & Scenarios 1-5)
        @ctx.room.on("data_received")
        def on_data_received(dp: rtc.DataPacket) -> None:
            try:
                raw_bytes = dp.data
                raw_str = raw_bytes.decode("utf-8") if isinstance(raw_bytes, (bytes, bytearray)) else str(raw_bytes)
                chat_text = ""
                try:
                    import json
                    parsed = json.loads(raw_str)
                    chat_text = parsed.get("message") or parsed.get("text") or parsed.get("content") or raw_str
                except Exception:
                    chat_text = raw_str

                chat_text = chat_text.strip()
                if not chat_text:
                    return

                sender_id = getattr(dp.participant, "identity", "User") if dp.participant else "User"
                sender_name = getattr(dp.participant, "name", "") or sender_id if dp.participant else "User"

                sid_l = sender_id.lower()
                sname_l = (sender_name or "").lower()
                if ("dost" in sid_l or "sathi" in sid_l or
                        "dost" in sname_l or "sathi" in sname_l or
                        "roxstar" in sid_l or "agent" in sid_l or
                        (ctx.room.local_participant and sid_l == ctx.room.local_participant.identity.lower())):
                    logger.debug("ai_chat_loop_blocked", sender_id=sender_id, bot="roxstar-sathi")
                    return

                if BotRouter.is_stop_command(chat_text):
                    try:
                        session.interrupt()
                    except Exception:
                        pass
                    asyncio.create_task(state.release_speaking_lock("roxstar-sathi"))
                    return

                logger.info("TEXT_CHAT_RECEIVED", bot="roxstar-sathi", sender=sender_name, text=chat_text[:80].encode("ascii", "replace").decode("ascii"))

                async def handle_chat() -> None:
                    thash = hashlib.md5(chat_text.lower().encode("utf-8")).hexdigest()[:8]
                    turn_id = f"chat:{sender_id}:{int(time.time() / 2.0) * 2}:{thash}"
                    is_winner = await state.claim_voice_ingest(turn_id)
                    from core.bot_router import BotRouter
                    if is_winner:
                        target = await BotRouter.select_bot(state, chat_text)
                        await state.set_voice_route(turn_id, target)
                        await state.add_turn(TurnRecord(speaker_id=sender_id, speaker_name=sender_name, text=chat_text))
                    else:
                        target = await state.wait_for_voice_route(turn_id, timeout_seconds=0.6)
                        if not target:
                            target = await BotRouter.select_bot(state, chat_text)

                    should_respond = (target == "roxstar-sathi")
                    if should_respond:
                        lock_ok = await state.acquire_speaking_lock("roxstar-sathi", ttl=15)
                        if not lock_ok:
                            await state.release_speaking_lock("roxstar-sathi")
                            lock_ok = await state.acquire_speaking_lock("roxstar-sathi", ttl=15)
                            if not lock_ok:
                                return
                        try:
                            room_context = await state.build_context_string(n=5)
                            updated_instructions = agent._raw_instructions.format(
                                room_context=room_context,
                                speaker_profile="No prior info.",
                            )
                            await agent.update_instructions(updated_instructions)
                            chat_ctx = llm.ChatContext()
                            chat_ctx.add_message(role="system", content=updated_instructions)
                            chat_ctx.add_message(role="user", content=chat_text)
                            stream = llm_provider.chat(chat_ctx=chat_ctx)
                            reply_text = ""
                            async for chunk in stream:
                                if chunk.delta and chunk.delta.content:
                                    reply_text += chunk.delta.content
                            reply_text = _sanitize_for_voice(reply_text.strip())
                            if not reply_text:
                                reply_text = "Haan ji, main sun rahi hoon! Bataiye kaise help kar sakti hoon?"

                            chat_payload = json.dumps({"id": str(uuid.uuid4()), "message": reply_text, "timestamp": int(time.time() * 1000)}).encode("utf-8")
                            await ctx.room.local_participant.publish_data(chat_payload, reliable=True, topic="lk-chat-topic")
                            await ctx.room.local_participant.publish_data(json.dumps({"message": reply_text, "sender": "Sathi"}).encode("utf-8"), reliable=True, topic="lk.chat")

                            turn = TurnRecord(speaker_id="sathi", speaker_name="Sathi", text=reply_text, bot_name="roxstar-sathi")
                            await state.add_turn(turn)
                            await state.set_last_bot("roxstar-sathi")

                            try:
                                await session.say(reply_text, allow_interruptions=True)
                            except Exception as say_err:
                                logger.error("sathi_say_error", error=str(say_err))
                        except Exception as exc:
                            logger.error("sathi_chat_reply_failed", error=str(exc))
                        finally:
                            await state.release_speaking_lock("roxstar-sathi")
                            await state.set_cooldown("roxstar-sathi", 1.0)

                asyncio.create_task(handle_chat())
            except Exception as exc:
                logger.error("text_chat_error", bot="roxstar-sathi", error=str(exc))

        logger.info("sathi_agent_session_active", room=room_name)

    except Exception as exc:
        logger.error(
            "sathi_entrypoint_failed",
            room=room_name,
            error=str(exc),
            exc_info=True,
        )
        raise


HANDLERS = {
    "roxstar-dost": dost_entrypoint,
    "roxstar-sathi": sathi_entrypoint,
}


@server.rtc_session(agent_name=AGENT_NAME)
async def entrypoint(ctx: JobContext) -> None:
    """Main job router: resolves dispatched agent and strictly prevents duplicates per room."""
    target_agent = ctx.job.metadata or ctx.job.agent_name or AGENT_NAME or "roxstar-dost"
    room_name = ctx.room.name
    logger.info("routing_agent_job", target_agent=target_agent, room=room_name)

    # 1. Check if an agent of this persona is already connected to the room
    expected_name = "Dost" if "dost" in target_agent else "Sathi"
    for p in ctx.room.remote_participants.values():
        p_name = (p.name or "").lower()
        p_id = (p.identity or "").lower()
        if expected_name.lower() in p_name or target_agent in p_id:
            logger.warning(
                "duplicate_agent_job_suppressed",
                target_agent=target_agent,
                existing_participant=p.identity,
                room=room_name,
            )
            return

    # 2. Redis active persona lock to prevent race conditions across parallel workers
    state = RoomState(room_name=room_name)
    redis = await state._get_redis()
    active_key = f"room:{room_name}:active_persona:{target_agent}"
    if redis:
        acquired = await redis.set(active_key, ctx.job.id, nx=True, ex=30)
        if not acquired:
            logger.warning(
                "duplicate_agent_job_suppressed_by_redis_lock",
                target_agent=target_agent,
                room=room_name,
            )
            return

    heartbeat_task = None

    async def _persona_heartbeat() -> None:
        try:
            while True:
                await asyncio.sleep(10)
                if redis:
                    await redis.set(active_key, ctx.job.id, ex=30)
        except asyncio.CancelledError:
            pass
        except Exception as err:
            logger.debug("persona_heartbeat_error", error=str(err))

    if redis:
        heartbeat_task = asyncio.create_task(_persona_heartbeat())

    @ctx.room.on("disconnected")
    def on_disconnected() -> None:
        logger.info("room_disconnected_releasing_persona_lock", agent=target_agent, room=room_name)
        if heartbeat_task and not heartbeat_task.done():
            heartbeat_task.cancel()
        if redis:
            asyncio.create_task(redis.delete(active_key))

    try:
        handler = HANDLERS.get(target_agent)
        if handler:
            await handler(ctx)
        else:
            logger.warning(
                "unknown_agent_target_falling_back_to_dost",
                target_agent=target_agent,
            )
            await dost_entrypoint(ctx)
    except Exception as exc:
        logger.error("agent_entrypoint_failed", target_agent=target_agent, error=str(exc))
        if heartbeat_task and not heartbeat_task.done():
            heartbeat_task.cancel()
        if redis:
            await redis.delete(active_key)
        raise


if __name__ == "__main__":
    cli.run_app(server)
