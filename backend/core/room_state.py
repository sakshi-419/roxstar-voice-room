"""
backend/core/room_state.py
--------------------------
RoomState abstraction for maintaining dialogue turns and room session context.

Features:
  - TurnRecord representation for human and bot utterances.
  - In-session multi-turn dialogue history for immediate conversational context.
  - Formatted context string generator for LLM prompt injection (follow-ups & coreference).
  - Speaker profile tracking and human participant counter.
  - Graceful Redis sync when available, falling back completely to local session memory.
  - Strictly per-session / per-room (no global singleton anti-pattern).
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

from pydantic import BaseModel, Field

from core.logger import get_logger

logger = get_logger("roxstar.room_state")


class TurnRecord(BaseModel):
    """Represents a single conversational turn in the voice room."""

    turn_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    speaker_id: str
    speaker_name: str
    text: str
    bot_name: str | None = None
    timestamp: float = Field(default_factory=time.time)

    def to_dialogue_line(self) -> str:
        """Format as a human-readable dialogue line for LLM prompts."""
        if self.bot_name:
            label = "Dost" if "dost" in self.bot_name.lower() else ("Sathi" if "sathi" in self.bot_name.lower() else self.bot_name)
            return f"{label}: {self.text}"
        return f"User ({self.speaker_name}): {self.text}"


class RoomState:
    """Manages conversational state for a room session."""

    def __init__(self, room_name: str) -> None:
        self.room_name = room_name
        self._turns: list[TurnRecord] = []
        self._speakers: dict[str, dict[str, Any]] = {}
        self._human_count: int = 0
        self._max_turns: int = 30

    # ── Turn Memory ──────────────────────────────────────────────────────────

    async def add_turn(self, turn: TurnRecord) -> None:
        """Record a turn in local history and attempt background Redis sync."""
        self._turns.append(turn)
        if len(self._turns) > self._max_turns:
            self._turns.pop(0)

        logger.info(
            "turn_recorded",
            room=self.room_name,
            speaker=turn.speaker_name,
            bot=turn.bot_name,
            turn_id=turn.turn_id,
            text_preview=turn.text[:60],
        )

        # Sync to Redis if available (Phase 0 client)
        try:
            from core.redis_client import get_redis
            redis = await get_redis()
            key = f"room:{self.room_name}:turns"
            payload = json.dumps(turn.model_dump())
            await redis.lpush(key, payload)
            await redis.ltrim(key, 0, self._max_turns - 1)
            await redis.expire(key, 86400)
        except Exception as exc:
            # Degraded local mode: Redis error never fails turn recording
            logger.debug("redis_sync_turn_skipped", room=self.room_name, error=str(exc))

    async def get_context_window(self, n: int = 10) -> list[TurnRecord]:
        """Return the most recent n turns."""
        return self._turns[-n:] if len(self._turns) > n else list(self._turns)

    async def build_context_string(self, n: int = 10) -> str:
        """Build formatted dialogue block of recent turns for LLM prompt injection."""
        recent_turns = await self.get_context_window(n)
        if not recent_turns:
            return "No previous conversation in this room yet."

        lines = [turn.to_dialogue_line() for turn in recent_turns]
        return "\n".join(lines)

    # ── History Hydration ───────────────────────────────────────────────────

    async def load_history_from_redis(self) -> int:
        """Hydrate local turns and speaker profiles from Redis if local state is empty."""
        try:
            from core.redis_client import get_redis
            redis = await get_redis()

            # 1. Hydrate turn history if local list is empty
            if not self._turns:
                key = f"room:{self.room_name}:turns"
                raw_items = await redis.lrange(key, 0, self._max_turns - 1)
                if raw_items:
                    loaded_turns: list[TurnRecord] = []
                    # Items from LPUSH are newest first -> reverse for chronological order
                    for item in reversed(raw_items):
                        try:
                            data = json.loads(item)
                            loaded_turns.append(TurnRecord(**data))
                        except Exception:
                            continue
                    self._turns = loaded_turns
                    logger.info("turns_hydrated_from_redis", room=self.room_name, count=len(self._turns))

            return len(self._turns)
        except Exception as exc:
            logger.debug("redis_history_hydration_skipped", room=self.room_name, error=str(exc))
            return len(self._turns)

    # ── Speaker Memory ───────────────────────────────────────────────────────

    async def register_speaker(self, identity: str, name: str) -> None:
        """Register or update a participant in local memory and Redis."""
        now = time.time()
        if identity not in self._speakers:
            self._speakers[identity] = {
                "identity": identity,
                "name": name,
                "first_seen": now,
                "facts": {},
            }
        else:
            self._speakers[identity]["name"] = name

        # Background Redis sync
        try:
            from core.redis_client import get_redis
            redis = await get_redis()
            key = f"room:{self.room_name}:speaker:{identity}"
            current_facts = json.dumps(self._speakers[identity]["facts"])
            mapping = {
                "identity": identity,
                "name": name,
                "first_seen": str(self._speakers[identity]["first_seen"]),
                "facts": current_facts,
            }
            await redis.hset(key, mapping=mapping)
            await redis.expire(key, 86400)
            logger.debug("speaker_registered_redis", room=self.room_name, identity=identity, name=name)
        except Exception as exc:
            logger.debug("redis_sync_speaker_skipped", room=self.room_name, error=str(exc))

    async def update_speaker_facts(self, identity: str, facts: dict[str, Any]) -> None:
        """Store extracted attributes or facts for a speaker in memory and Redis."""
        if not facts:
            return

        if identity not in self._speakers:
            await self.register_speaker(identity, identity)

        self._speakers[identity]["facts"].update(facts)

        logger.info(
            "speaker_facts_updated",
            room=self.room_name,
            identity=identity,
            facts=facts,
        )

        # Background Redis sync
        try:
            from core.redis_client import get_redis
            redis = await get_redis()
            key = f"room:{self.room_name}:speaker:{identity}"
            facts_json = json.dumps(self._speakers[identity]["facts"])
            await redis.hset(key, "facts", facts_json)
            await redis.expire(key, 86400)
        except Exception as exc:
            logger.debug("redis_sync_facts_skipped", room=self.room_name, error=str(exc))

    async def get_speaker_profile(self, identity: str) -> str:
        """Return a formatted profile of the speaker for prompt injection."""
        profile = self._speakers.get(identity)

        # Try hydrating from Redis if missing locally
        if not profile:
            try:
                from core.redis_client import get_redis
                redis = await get_redis()
                key = f"room:{self.room_name}:speaker:{identity}"
                raw_hash = await redis.hgetall(key)
                if raw_hash:
                    # Redis returns bytes or strings depending on decode_responses
                    h_data = {
                        (k.decode("utf-8") if isinstance(k, bytes) else k): (v.decode("utf-8") if isinstance(v, bytes) else v)
                        for k, v in raw_hash.items()
                    }
                    facts_dict = {}
                    if "facts" in h_data and h_data["facts"]:
                        try:
                            facts_dict = json.loads(h_data["facts"])
                        except Exception:
                            facts_dict = {}

                    profile = {
                        "identity": h_data.get("identity", identity),
                        "name": h_data.get("name", identity),
                        "first_seen": float(h_data.get("first_seen", time.time())),
                        "facts": facts_dict,
                    }
                    self._speakers[identity] = profile
            except Exception as exc:
                logger.debug("redis_get_speaker_skipped", room=self.room_name, error=str(exc))

        if not profile:
            return f"Speaker ID: {identity}"

        name = profile.get("name", identity)
        facts = profile.get("facts", {})
        if facts:
            facts_str = ", ".join(f"{k}: {v}" for k, v in facts.items())
            return f"Speaker Name: {name} (Known facts: {facts_str})"
        return f"Speaker Name: {name}"

    # ── Participant Counter ──────────────────────────────────────────────────

    async def increment_human_count(self) -> int:
        self._human_count += 1
        return self._human_count

    async def decrement_human_count(self) -> int:
        self._human_count = max(0, self._human_count - 1)
        return self._human_count

    async def get_human_count(self) -> int:
        return self._human_count

