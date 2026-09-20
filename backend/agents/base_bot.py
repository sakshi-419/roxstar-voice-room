"""
backend/agents/base_bot.py
--------------------------
BaseBotAgent provides core room context integration, turn memory recording,
exactly-once voice ingestion, distributed routing, and speaking locks for
conversational voice bots in Roxstar Voice Room.

CRITICAL GUARANTEES (enforced here):
  1. Agents enter COMPLETELY SILENT - no auto-greeting on join/reconnect.
  2. Only HUMAN participants can trigger responses (AI-to-AI loops blocked).
  3. Exact-once per human turn: distributed turn_id claim + speaking lock.
  4. Stop/Ruko/Bas commands immediately interrupt TTS without verbal reply.
"""

from __future__ import annotations

import hashlib

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

# Markers that identify an AI agent participant vs a real human
_AI_IDENTITY_MARKERS = frozenset({
    "dost", "sathi", "roxstar", "agent", "bot",
})


def _is_ai_participant(identity: str, name: str = "") -> bool:
    """Return True if this participant belongs to an AI agent, not a human."""
    id_lower = (identity or "").lower()
    name_lower = (name or "").lower()
    return any(m in id_lower or m in name_lower for m in _AI_IDENTITY_MARKERS)


def extract_speaker_facts(text: str) -> dict[str, Any]:
    """Extract personal facts (name, city, interest) from user speech."""
    facts: dict[str, Any] = {}

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

    city_match = (
        re.search(r"\bmain\s+([a-zA-Z]+)\s+se\s+hoo?n\b", text, re.IGNORECASE)
        or re.search(r"\bi\s+live\s+in\s+([a-zA-Z]+)", text, re.IGNORECASE)
        or re.search(r"\bi\s+am\s+from\s+([a-zA-Z]+)", text, re.IGNORECASE)
    )
    if city_match:
        cand = city_match.group(1).capitalize()
        if cand.lower() not in {"yahan", "wahan", "india", "ghar"}:
            facts["city"] = cand

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
        self._prompt_template = instructions
        self._last_detected_language = "HINGLISH"
        default_lang_instr = (
            "LANGUAGE DIRECTIVE: Under NO circumstances speak Spanish, French, German, or any foreign language. "
            "Respond in natural Indian Hinglish, Hindi (Devanagari if user spoke Hindi), or English matching the user."
        )
        initial_instructions = (
            instructions
            .replace("{detected_language_instruction}", default_lang_instr)
            .replace("{room_context}", "Room conversation just started.")
            .replace("{speaker_profile}", "No prior info.")
        )
        super().__init__(instructions=initial_instructions, **kwargs)
        self.bot_name = bot_name
        self.state = state
        self.latency_tracker = latency_tracker or LatencyTracker()
        # greeting is stored for reference only - NEVER auto-sent
        self.greeting = greeting
        self._raw_instructions = initial_instructions
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
        """Called when the agent enters the room session.

        CRITICAL: Agent enters COMPLETELY SILENT.
        No automatic greeting speech on join/startup/reconnect.
        First AI audio only happens AFTER a human speaks first.
        """
        logger.info("bot_entered_session_silent", bot=self.bot_name, room=self.state.room_name)
        await self.state.load_history_from_redis()

    def format_instructions(
        self,
        room_context: str = "Room conversation active.",
        speaker_profile: str = "Active speaker.",
        language_instruction: str = "",
    ) -> str:
        """Safely format system prompt template replacing placeholders."""
        text = getattr(self, "_prompt_template", "") or self._raw_instructions
        if not language_instruction:
            language_instruction = (
                f"LANGUAGE RULE: Respond in natural {getattr(self, '_last_detected_language', 'HINGLISH').lower()}. "
                "Match the speaker's language style. NEVER speak Spanish or any foreign language."
            )
        text = text.replace("{detected_language_instruction}", language_instruction)
        text = text.replace("{room_context}", room_context or "No prior context.")
        text = text.replace("{speaker_profile}", speaker_profile or "Speaker profile available.")
        return text

    async def on_participant_connected(self, participant: Any) -> None:
        """Called when a participant joins the LiveKit room.

        ONLY registers and counts HUMAN participants.
        AI agent participants (Dost, Sathi, roxstar-*) are ignored.
        """
        identity = getattr(participant, "identity", "")
        name = getattr(participant, "name", "") or identity

        if _is_ai_participant(identity, name):
            logger.debug(
                "ai_participant_join_ignored",
                bot=self.bot_name,
                identity=identity,
            )
            return

        await self.state.register_speaker(identity, name)
        await self.state.increment_human_count()
        logger.info("human_participant_registered", bot=self.bot_name, identity=identity, name=name)

    async def on_participant_disconnected(self, participant: Any) -> None:
        """Called when a participant leaves. Only decrements count for real humans."""
        identity = getattr(participant, "identity", "")
        name = getattr(participant, "name", "") or identity

        if _is_ai_participant(identity, name):
            return

        await self.state.decrement_human_count()
        logger.info("human_participant_left", bot=self.bot_name, identity=identity)

    async def on_user_turn_completed(
        self,
        turn_ctx: llm.ChatContext,
        new_message: llm.ChatMessage,
    ) -> None:
        """Called when user finishes speaking before LLM generates a response.

        This is the ONLY path through which AI speech is generated.
        All guards must pass before any LLM/TTS work is started.
        """
        # 1. Extract text from message
        user_text = ""
        if isinstance(new_message.content, list):
            user_text = " ".join(str(c) for c in new_message.content if isinstance(c, str)).strip()
        elif isinstance(new_message.content, str):
            user_text = new_message.content.strip()

        if not user_text:
            return

        logger.info(
            "VOICE_TRANSCRIPT",
            text=user_text[:100].encode("ascii", "replace").decode("ascii"),
            room=self.state.room_name,
        )

        # 2. Speaker Identity & AI-to-AI Loop Prevention
        speaker_id = (
            self._last_transcribed_speaker_id
            or getattr(new_message, "speaker_id", None)
            or "human"
        )
        speaker_name = getattr(new_message, "speaker_name", None) or speaker_id

        if _is_ai_participant(str(speaker_id), str(speaker_name or "")):
            logger.debug("ai_audio_loop_blocked", speaker_id=speaker_id, bot=self.bot_name)
            raise StopResponse()

        # 3. AI Audio Loopback / Acoustic Echo Suppression
        try:
            recent_turns = await self.state.get_context_window(6)
            cleaned_user = re.sub(r"[^\w\s]", "", user_text.lower()).strip()
            if len(cleaned_user) >= 6:
                for t in reversed(recent_turns):
                    if t.bot_name and t.text:
                        cleaned_bot = re.sub(r"[^\w\s]", "", t.text.lower()).strip()
                        if cleaned_user in cleaned_bot or (len(cleaned_user) > 12 and cleaned_bot in cleaned_user):
                            logger.warning("ai_audio_loopback_detected_suppressing", bot=self.bot_name, text=user_text[:60])
                            raise StopResponse()
                        user_words = set(cleaned_user.split())
                        bot_words = set(cleaned_bot.split())
                        if len(user_words) >= 4 and len(user_words & bot_words) / len(user_words) > 0.8:
                            logger.warning("ai_audio_word_overlap_loopback_suppressing", bot=self.bot_name, text=user_text[:60])
                            raise StopResponse()
        except StopResponse:
            raise
        except Exception as exc:
            logger.debug("echo_suppression_check_error", error=str(exc))

        # 4. STOP / Ruko / Bas / Chup — immediately interrupt TTS, NO verbal reply
        if BotRouter.is_stop_command(user_text):
            logger.info("INTERRUPT_STOP_COMMAND_PROCESSED", bot=self.bot_name, text=user_text)
            if hasattr(self, "session") and self.session:
                try:
                    self.session.interrupt()
                except Exception:
                    pass
            await self.state.release_speaking_lock(self.bot_name)
            raise StopResponse()

        # 5. Distributed Bot Routing — select exactly ONE bot to respond
        target_bot = await BotRouter.select_bot(self.state, user_text)

        if target_bot == "STOP":
            logger.info("INTERRUPT_STOP_COMMAND_EXECUTED", bot=self.bot_name, text=user_text)
            if hasattr(self, "session") and self.session:
                try:
                    self.session.interrupt()
                except Exception:
                    pass
            await self.state.release_speaking_lock(self.bot_name)
            raise StopResponse()

        # 6. Routing Filter: Only the selected bot proceeds; the other is silenced.
        if target_bot != self.bot_name:
            logger.info(
                "bot_turn_suppressed_by_router",
                bot=self.bot_name,
                target_bot=target_bot,
            )
            raise StopResponse()

        # 7. Turn Idempotency: Exactly one bot handles this human turn.
        clean_user_turn = re.sub(r"[^\w\s]", "", user_text.lower()).strip()
        turn_window = int(time.time() / 3.0)
        turn_id = hashlib.sha256(f"{clean_user_turn}:{turn_window}".encode("utf-8")).hexdigest()[:16]
        claimed = await self.state.claim_voice_ingest(turn_id, ttl=10)
        if not claimed:
            logger.warning(
                "bot_turn_suppressed_duplicate_or_already_claimed",
                bot=self.bot_name,
                turn_id=turn_id,
            )
            raise StopResponse()

        # 8. Distributed Speaking Lock: At most ONE bot speaks at any moment.
        lock_acquired = await self.state.acquire_speaking_lock(self.bot_name, ttl=15)
        if not lock_acquired:
            logger.warning("bot_turn_suppressed_speaking_lock_busy", bot=self.bot_name)
            raise StopResponse()

        # Update last bot for conversation continuity
        await self.state.set_last_bot(self.bot_name)

        # Record speaker and turn history in room state
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
        logger.info("TTS_START", bot=self.bot_name, room=self.state.room_name)

        # 9. Cap dialogue context to keep LLM TTFB fast
        try:
            if hasattr(turn_ctx, "truncate") and len(getattr(turn_ctx, "items", [])) > 6:
                turn_ctx.truncate(max_items=6)
        except Exception:
            pass

        # 10. Language detection, continuity & dynamic instruction update
        from core.language_detector import detect_language, get_language_instruction
        prev_lang = getattr(self, "_last_detected_language", "HINGLISH")
        detected_lang = detect_language(user_text, previous_language=prev_lang)
        self._last_detected_language = detected_lang
        lang_instruction = get_language_instruction(user_text, previous_language=detected_lang)
        logger.info(
            "language_detected",
            bot=self.bot_name,
            language=detected_lang,
            text_preview=user_text[:60].encode("ascii", "replace").decode("ascii"),
        )

        room_context = await self.state.build_context_string(n=5)
        speaker_profile = await self.state.get_speaker_profile(speaker_id)

        try:
            updated_instructions = self.format_instructions(
                room_context=room_context,
                speaker_profile=speaker_profile,
                language_instruction=lang_instruction,
            )
            self._raw_instructions = updated_instructions
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
