"""
backend/agents/sathi_agent.py
-----------------------------
SathiAgent implementation for Roxstar Voice Room (Phase 5).
Subclasses BaseBotAgent and binds Sathi's persona instructions and greeting.
"""

from __future__ import annotations

from typing import Any

from agents.base_bot import BaseBotAgent
from agents.sathi_persona import SATHI_GREETING, SATHI_SYSTEM_PROMPT
from core.latency_tracker import LatencyTracker
from core.room_state import RoomState


class SathiAgent(BaseBotAgent):
    """Roxstar AI Sathi voice agent."""

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
