"""
backend/agents/dost_agent.py
----------------------------
Roxstar AI Dost agent implementation.
"""

from __future__ import annotations

from typing import Any

from agents.base_bot import BaseBotAgent
from agents.dost_persona import DOST_GREETING, DOST_SYSTEM_PROMPT
from core.latency_tracker import LatencyTracker
from core.room_state import RoomState


class DostAgent(BaseBotAgent):
    """Roxstar AI Dost — Friendly Indian male AI companion with language adaptation."""

    def __init__(
        self,
        *,
        state: RoomState,
        latency_tracker: LatencyTracker | None = None,
        instructions: str = DOST_SYSTEM_PROMPT,
        greeting: str = DOST_GREETING,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            bot_name="roxstar-dost",
            state=state,
            latency_tracker=latency_tracker,
            instructions=instructions,
            greeting=greeting,
            **kwargs,
        )
