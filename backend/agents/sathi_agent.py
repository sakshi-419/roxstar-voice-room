"""
backend/agents/sathi_agent.py
-----------------------------
SathiAgent implementation for Roxstar Voice Room.

Extends BaseBotAgent with Sathi-specific per-turn language detection:
  - Detects Hindi / Hinglish / English from user text each turn
  - Injects the appropriate language instruction into the system prompt
  - Ensures Sathi responds in the same language the user is using

All other behavior (routing, locking, interruption) is inherited from BaseBotAgent.
"""

from __future__ import annotations

from typing import Any

from agents.base_bot import BaseBotAgent
from agents.sathi_persona import SATHI_GREETING, SATHI_SYSTEM_PROMPT
from core.language_detector import get_language_instruction, detect_language
from core.latency_tracker import LatencyTracker
from core.logger import get_logger
from core.room_state import RoomState
from livekit.agents import llm

logger = get_logger("roxstar.agents.sathi")


class SathiAgent(BaseBotAgent):
    """Roxstar AI Sathi - Friendly Indian female AI companion with language-adaptive responses."""

    def __init__(
        self,
        *,
        state: RoomState,
        latency_tracker: LatencyTracker | None = None,
        instructions: str = SATHI_SYSTEM_PROMPT,
        greeting: str = SATHI_GREETING,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            bot_name="roxstar-sathi",
            state=state,
            latency_tracker=latency_tracker,
            instructions=instructions,
            greeting=greeting,
            **kwargs,
        )
        # Cache last detected language for follow-up continuity
        self._last_detected_language: str = "HINGLISH"

    async def on_user_turn_completed(
        self,
        turn_ctx: llm.ChatContext,
        new_message: llm.ChatMessage,
    ) -> None:
        """
        Per-turn language detection for Sathi.

        Before delegating to BaseBotAgent, we:
        1. Extract user text from the message
        2. Detect the language (HINDI / HINGLISH / ENGLISH)
        3. Inject the language instruction into _raw_instructions

        This ensures Sathi responds in the same language as the human.
        """
        # Extract user text early for language detection
        user_text = ""
        if isinstance(new_message.content, list):
            user_text = " ".join(
                str(c) for c in new_message.content if isinstance(c, str)
            ).strip()
        elif isinstance(new_message.content, str):
            user_text = new_message.content.strip()

        if user_text:
            detected_lang = detect_language(user_text)
            lang_instruction = get_language_instruction(user_text)
            self._last_detected_language = detected_lang
            logger.info(
                "sathi_language_detected",
                language=detected_lang,
                text_preview=user_text[:60].encode("ascii", "replace").decode("ascii"),
            )

            # Temporarily patch _raw_instructions with the detected language instruction.
            # BaseBotAgent.on_user_turn_completed will call self._raw_instructions.format(...)
            # which will substitute {detected_language_instruction} correctly.
            original_instructions = self._raw_instructions
            try:
                self._raw_instructions = SATHI_SYSTEM_PROMPT.replace(
                    "{detected_language_instruction}",
                    lang_instruction,
                )
            except Exception as exc:
                logger.debug("sathi_language_injection_failed", error=str(exc))
                self._raw_instructions = original_instructions

        # Delegate all routing, locking, echo suppression, and TTS to BaseBotAgent
        await super().on_user_turn_completed(turn_ctx, new_message)
