"""
backend/agents/base_bot.py
--------------------------
BaseBotAgent provides core room context integration, turn memory recording,
exactly-once voice ingestion, distributed routing, and speaking locks for
conversational voice bots in Roxstar Voice Room.
"""

from __future__ import annotations

import asyncio
import re
import time
from typing import Any

from core.bot_router import BotRouter
from core.latency_tracker import LatencyTracker
from core.logger import get_logger
from core.room_state import RoomState, TurnRecord
from livekit.agents import Agent, llm
from livekit.agents.llm import StopResponse

logger = get_logger("roxstar.agents.base")


def extract_speaker_facts(text: str) -> dict[str, Any]:
    """Extract personal facts (name, city, interest) from user speech using lightweight regex rules."""
    facts: dict[str, Any] = {}

    # 1. Name extraction
    name_match = (
        re.search(r"\bmera\s+naam\s+([a-zA-Z]+)", text, re.IGNORECASE)
        or re.search(r"\bmy\s+name\s+is\s+([a-zA-Z]+)", text, re.IGNORECASE)
        or re.search(r"\bcall\s+me\s+([a-zA-Z]+)", text, re.IGNORECASE)
        or re.search(r"\bmujhe\s+([a-zA-Z]+)\s+bulao\b", text, re.IGNORECASE)
    )
    if name_match:
        cand = name_match.group(1).capitalize()
        if cand.lower() not in {"dost", "sathi", "human", "bot", "user"}:
            facts["name"] = cand

    # 2. Location / City extraction
    city_match = (
        re.search(r"\bmain\s+([a-zA-Z]+)\s+se\s+hoo?n\b", text, re.IGNORECASE)
        or re.search(r"\bi\s+live\s+in\s+([a-zA-Z]+)", text, re.IGNORECASE)
        or re.search(r"\bi\s+am\s+from\s+([a-zA-Z]+)", text, re.IGNORECASE)
    )
    if city_match:
        cand = city_match.group(1).capitalize()
        if cand.lower() not in {"yahan", "wahan", "india", "ghar"}:
            facts["city"] = cand

    # 3. Interest / Hobby extraction
    interest_match = (
        re.search(r"\bmujhe\s+(.+?)\s+pasand\s+hai\b", text, re.IGNORECASE)
        or re.search(r"\bi\s+(?:like|love)\s+(.+?)(?:\s+a\s+lot|\.|$)", text, re.IGNORECASE)
    )
    if interest_match:
        cand_str = interest_match.group(1).strip()
        if 2 <= len(cand_str) <= 30:
            facts["interests"] = cand_str

    return facts


class BaseBotAgent(Agent):
    """Base class for conversational AI voice agents."""

    def __init__(
        self,
        *,
        bot_name: str,
        state: RoomState,
        latency_tracker: LatencyTracker | None = None,
        instructions: str = "",
        greeting: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(instructions=instructions, **kwargs)
        self.bot_name = bot_name
        self.state = state
        self.latency_tracker = latency_tracker or LatencyTracker()
        self.greeting = greeting
        self._raw_instructions = instructions
        self._last_transcribed_speaker_id: str | None = None
        self._mock_session: Any = None

    @property
    def session(self) -> Any:
        if hasattr(self, "_mock_session") and self._mock_session is not None:
            return self._mock_session
        try:
            return super().session
        except Exception:
            return None

    @session.setter
    def session(self, val: Any) -> None:
        self._mock_session = val

    def set_last_speaker(self, speaker_id: str | None) -> None:
        """Store the speaker identity from the latest UserInputTranscribedEvent."""
        self._last_transcribed_speaker_id = speaker_id

    async def on_enter(self) -> None:
        """Called when the agent enters the room session."""
        logger.info("bot_entered_session", bot=self.bot_name, room=self.state.room_name)

        # Hydrate history from Redis if available
        await self.state.load_history_from_redis()

        if self.greeting and hasattr(self, "session") and self.session:
            try:
                # Greet the room warmly on entry
                await self.session.say(self.greeting, allow_interruptions=True)
                logger.info("bot_greeting_delivered", bot=self.bot_name, text=self.greeting)
            except Exception as exc:
                logger.warning("bot_greeting_failed", bot=self.bot_name, error=str(exc))

    async def on_participant_connected(self, participant: Any) -> None:
        """Called when a participant joins the LiveKit room."""
        identity = getattr(participant, "identity", "user")
        name = getattr(participant, "name", "") or identity
        await self.state.register_speaker(identity, name)
        await self.state.increment_human_count()
        logger.info("participant_registered", bot=self.bot_name, identity=identity, name=name)

    async def on_participant_disconnected(self, participant: Any) -> None:
        """Called when a participant leaves the LiveKit room."""
        await self.state.decrement_human_count()
        logger.info("participant_left", bot=self.bot_name)

    async def on_user_turn_completed(
        self,
        turn_ctx: llm.ChatContext,
        new_message: llm.ChatMessage,
    ) -> None:
        """Called when user finishes speaking before LLM generates a response."""
        # 1. Extract text from message
        user_text = ""
        if isinstance(new_message.content, list):
            user_text = " ".join(str(c) for c in new_message.content if isinstance(c, str)).strip()
        elif isinstance(new_message.content, str):
            user_text = new_message.content.strip()

        if not user_text:
            return

        logger.info("VOICE_TRANSCRIPT", text=user_text[:100].encode("ascii", "replace").decode("ascii"), room=self.state.room_name)

        # 2. Speaker Identity & AI-to-AI Loop Prevention
        # Only genuine human participants can trigger AI responses.
        speaker_id = self._last_transcribed_speaker_id or getattr(new_message, "speaker_id", None) or "human"
        speaker_name = getattr(new_message, "speaker_name", None) or speaker_id

        sid_lower = speaker_id.lower()
        sname_lower = (speaker_name or "").lower()
        if (
            "dost" in sid_lower
            or "sathi" in sid_lower
            or "roxstar" in sid_lower
            or "agent" in sid_lower
            or "dost" in sname_lower
            or "sathi" in sname_lower
            or sid_lower == self.bot_name.lower()
        ):
            logger.debug("ai_audio_loop_blocked", speaker_id=speaker_id, bot=self.bot_name)
            raise StopResponse()

        # 3. AI Audio Loopback / Acoustic Echo Suppression
        # Check if the transcribed text matches recently spoken bot turns
        try:
            recent_turns = await self.state.get_context_window(4)
            cleaned_user = re.sub(r"[^\w\s]", "", user_text.lower()).strip()
            if len(cleaned_user) >= 6:
                for t in reversed(recent_turns):
                    if t.bot_name and t.text:
                        cleaned_bot = re.sub(r"[^\w\s]", "", t.text.lower()).strip()
                        if cleaned_user in cleaned_bot or (len(cleaned_user) > 15 and cleaned_bot in cleaned_user):
                            logger.warning("ai_audio_loopback_detected_suppressing", bot=self.bot_name, text=user_text[:60])
                            raise StopResponse()
        except StopResponse:
            raise
        except Exception as exc:
            logger.debug("echo_suppression_check_error", error=str(exc))

        # 4. STOP / Ruko / Bas / Chup Interruption Control
        # If user says a stop command, cancel playback immediately and do NOT speak
        if BotRouter.is_stop_command(user_text):
            logger.info("INTERRUPT_STOP_COMMAND_PROCESSED", bot=self.bot_name, text=user_text)
            if hasattr(self, "session") and self.session:
                try:
                    self.session.interrupt()
                except Exception:
                    pass
            await self.state.release_speaking_lock(self.bot_name)
            raise StopResponse()

        # 5. Exactly-Once Voice Ingestion & Routing
        clean_snippet = re.sub(r"[^\w]", "", user_text.lower())[:16]
        time_bucket = int(time.time() / 2.0) * 2
        turn_id = f"{speaker_id}:{clean_snippet}:{time_bucket}"

        is_winner = await self.state.claim_voice_ingest(turn_id)

        if is_winner:
            t_route_start = time.time()
            target_bot = await BotRouter.select_bot(self.state, user_text)
            routing_ms = (time.time() - t_route_start) * 1000.0

            if target_bot == "STOP":
                if hasattr(self, "session") and self.session:
                    try:
                        self.session.interrupt()
                    except Exception:
                        pass
                await self.state.release_speaking_lock(self.bot_name)
                await self.state.set_voice_route(turn_id, "STOP")
                raise StopResponse()

            await self.state.set_voice_route(turn_id, target_bot)
            logger.info("BOT_ROUTED", selected_bot=target_bot, routing_ms=round(routing_ms, 2), room=self.state.room_name)

            await self.state.register_speaker(speaker_id, speaker_name)
            extracted_facts = extract_speaker_facts(user_text)
            if extracted_facts:
                await self.state.update_speaker_facts(speaker_id, extracted_facts)

            turn = TurnRecord(
                speaker_id=speaker_id,
                speaker_name=speaker_name,
                text=user_text,
            )
            await self.state.add_turn(turn)
        else:
            target_bot = await self.state.wait_for_voice_route(turn_id, timeout_seconds=0.6)
            if not target_bot:
                target_bot = await BotRouter.select_bot(self.state, user_text)

        if target_bot == "STOP":
            if hasattr(self, "session") and self.session:
                try:
                    self.session.interrupt()
                except Exception:
                    pass
            await self.state.release_speaking_lock(self.bot_name)
            raise StopResponse()

        # 6. Routing Filter: Only the selected bot proceeds
        if target_bot != self.bot_name:
            logger.info(
                "bot_turn_suppressed_by_router",
                bot=self.bot_name,
                target_bot=target_bot,
                turn_id=turn_id,
            )
            raise StopResponse()

        # 7. Distributed Speaking Lock: Ensure exclusive speech generation
        # Release any stale lock from previous turn, then acquire fresh lock
        await self.state.release_speaking_lock(self.bot_name)
        lock_acquired = await self.state.acquire_speaking_lock(self.bot_name, ttl=20)
        if not lock_acquired:
            logger.warning(
                "bot_turn_suppressed_speaking_lock_busy",
                bot=self.bot_name,
                turn_id=turn_id,
            )
            raise StopResponse()
        logger.info("TTS_START", bot=self.bot_name, room=self.state.room_name)

        # 8. Cap dialogue context to keep TTFB fast
        try:
            if hasattr(turn_ctx, "truncate") and len(getattr(turn_ctx, "items", [])) > 6:
                turn_ctx.truncate(max_items=6)
        except Exception:
            pass

        # 9. Dynamically inject updated room context & speaker profile into system instructions
        room_context = await self.state.build_context_string(n=5)
        speaker_profile = await self.state.get_speaker_profile(speaker_id)

        try:
            updated_instructions = self._raw_instructions.format(
                room_context=room_context,
                speaker_profile=speaker_profile,
            )
            await self.update_instructions(updated_instructions)
        except Exception as exc:
            logger.debug("instruction_formatting_skipped", error=str(exc))

        logger.info(
            "user_turn_processed",
            bot=self.bot_name,
            speaker_id=speaker_id,
            user_text=user_text[:80],
            context_turns_count=len(self.state._turns),
        )
        logger.info("LLM_STARTED", bot=self.bot_name, room=self.state.room_name)
