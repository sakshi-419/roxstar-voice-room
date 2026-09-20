"""
backend/agents/sathi_agent.py
-----------------------------
SathiAgent implementation for Roxstar Voice Room.

Inherits from BaseBotAgent with Sathi-specific persona and greeting.
Language detection, instruction injection, routing, locking, and interruption
are cleanly handled by BaseBotAgent.
"""

from __future__ import annotations

from typing import Any

from agents.base_bot import BaseBotAgent
from agents.sathi_persona import SATHI_GREETING, SATHI_SYSTEM_PROMPT
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

    async def on_user_turn_completed(
        self,
        turn_ctx: llm.ChatContext,
        new_message: llm.ChatMessage,
    ) -> None:
        """Delegate to BaseBotAgent while logging Sathi-specific language telemetry."""
        user_text = ""
        if isinstance(new_message.content, list):
            user_text = " ".join(
                str(c) for c in new_message.content if isinstance(c, str)
            ).strip()
        elif isinstance(new_message.content, str):
            user_text = new_message.content.strip()

        if user_text:
            from core.language_detector import detect_language
            detected_lang = detect_language(user_text, previous_language=self._last_detected_language)
            logger.info(
                "sathi_language_detected",
                language=detected_lang,
                text_preview=user_text[:60].encode("ascii", "replace").decode("ascii"),
            )

        await super().on_user_turn_completed(turn_ctx, new_message)
