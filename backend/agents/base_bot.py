"""
backend/agents/base_bot.py
--------------------------
BaseBotAgent provides core room context integration, turn memory recording,
and latency tracking for conversational voice bots in Roxstar Voice Room.
"""

from __future__ import annotations

from typing import Any

from core.latency_tracker import LatencyTracker
from core.logger import get_logger
from core.room_state import RoomState, TurnRecord
from livekit.agents import Agent, llm

logger = get_logger("roxstar.agents.base")


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

    async def on_enter(self) -> None:
        """Called when the agent enters the room session."""
        logger.info("bot_entered_session", bot=self.bot_name, room=self.state.room_name)
        if self.greeting and hasattr(self, "session") and self.session:
            try:
                # Greet the room warmly on entry
                await self.session.say(self.greeting, allow_interruptions=True)
                logger.info("bot_greeting_delivered", bot=self.bot_name, text=self.greeting)
            except Exception as exc:
                logger.warning("bot_greeting_failed", bot=self.bot_name, error=str(exc))

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
            logger.debug("empty_user_transcript_received", bot=self.bot_name)
            return

        speaker_id = "user"
        speaker_name = "User"

        # 2. Record human turn into RoomState
        turn = TurnRecord(
            speaker_id=speaker_id,
            speaker_name=speaker_name,
            text=user_text,
        )
        await self.state.add_turn(turn)

        # 3. Dynamically inject updated room context & speaker profile into system instructions
        room_context = await self.state.build_context_string(n=10)
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
            user_text=user_text[:80],
            context_turns_count=len(self.state._turns),
        )
