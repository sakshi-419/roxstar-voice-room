"""
backend/core/room_state.py
--------------------------
Shared in-memory and Redis-backed room state manager for Roxstar AI Voice Room.

Phase 4:
  - Tracks turns (up to max_turns=30).
  - Maintains speaker profiles and persistent facts.
  - Generates prompt context dialogues.
  - Syncs to Redis (room:{room_name}:turns, room:{room_name}:speakers) with local fallback.
  - Supports history hydration on worker startup.

Phase 5:
  - Exactly-once voice ingestion deduplication (claim_voice_ingest).
  - Distributed voice route synchronization (set_voice_route, get_voice_route, wait_for_voice_route).
  - Distributed speaking lock with 15s TTL (acquire_speaking_lock, release_speaking_lock).
  - Post-speech cooldown (set_cooldown, is_cooldown_active).
  - Last speaking bot tracking (set_last_bot, get_last_bot).
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any
from pydantic import BaseModel, Field

from core.logger import get_logger

logger = get_logger("roxstar.core.room_state")


class TurnRecord(BaseModel):
    """Represents a single conversational turn in the audio room."""

    turn_id: str = Field(default_factory=lambda: f"turn_{int(time.time() * 1000)}")
    speaker_id: str
    speaker_name: str = "User"
    bot_name: str | None = None
    text: str
    timestamp: float = Field(default_factory=time.time)

    def to_dialogue_line(self) -> str:
        """Format turn as a conversational dialogue line for LLM system prompt context."""
        if self.bot_name:
            label = "Dost" if "dost" in self.bot_name.lower() else ("Sathi" if "sathi" in self.bot_name.lower() else self.speaker_name)
            return f"{label}: {self.text}"
        return f"User ({self.speaker_name}): {self.text}"


class RoomState:
    """Manages conversational dialogue turns, speaker identities, routing, and speaking locks."""

    def __init__(self, room_name: str, max_turns: int = 30) -> None:
        self.room_name = room_name
        self._max_turns = max_turns
        self._turns: list[TurnRecord] = []
        self._speakers: dict[str, dict[str, Any]] = {}
        self._human_count: int = 0
        self._lock = asyncio.Lock()

        # Phase 5: Voice ingest claim, routing decisions, speaking lock, cooldowns, last_bot
        self._claimed_turns: dict[str, float] = {}
        self._turn_routes: dict[str, str] = {}
        self._speaking_lock: str | None = None
        self._speaking_lock_expires: float = 0.0
        self._cooldowns: dict[str, float] = {}
        self._last_bot: str | None = None

    async def _get_redis(self):
        """Safely fetch Redis client, automatically handling event loop changes in tests/workers."""
        try:
            from core import redis_client
            if redis_client._redis_client is not None:
                pool = getattr(redis_client._redis_client, "connection_pool", None)
                loop = asyncio.get_running_loop()
                pool_loop = getattr(pool, "_loop", None)
                if pool_loop is not None and (pool_loop.is_closed() or pool_loop != loop):
                    redis_client._redis_client = None
            return await redis_client.get_redis()
        except Exception:
            return None

    # ── Turn Management ───────────────────────────────────────────────────────

    async def add_turn(self, turn: TurnRecord) -> None:
        """Record a new conversational turn in memory and sync to Redis list."""
        self._turns.append(turn)
        if len(self._turns) > self._max_turns:
            self._turns.pop(0)

        logger.debug(
            "turn_recorded",
            room=self.room_name,
            speaker=turn.speaker_name,
            bot=turn.bot_name,
            turn_id=turn.turn_id,
            text_preview=turn.text[:60],
        )

        # Sync to Redis if available
        try:
            redis = await self._get_redis()
            if redis:
                key = f"room:{self.room_name}:turns"
                payload = json.dumps(turn.model_dump())
                await redis.lpush(key, payload)
                await redis.ltrim(key, 0, self._max_turns - 1)
                await redis.expire(key, 86400)
        except Exception as exc:
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
            redis = await self._get_redis()
            if not redis:
                return len(self._turns)

            # 1. Hydrate turn history if local list is empty
            if not self._turns:
                key = f"room:{self.room_name}:turns"
                raw_items = await redis.lrange(key, 0, self._max_turns - 1)
                if raw_items:
                    loaded_turns: list[TurnRecord] = []
                    for item in reversed(raw_items):
                        try:
                            data = json.loads(item)
                            loaded_turns.append(TurnRecord(**data))
                        except Exception:
                            continue
                    self._turns = loaded_turns
                    logger.info(
                        "room_history_hydrated_from_redis",
                        room=self.room_name,
                        turns_count=len(self._turns),
                    )

            # 2. Hydrate speaker profiles
            speaker_key = f"room:{self.room_name}:speakers"
            raw_speakers = await redis.hgetall(speaker_key)
            if raw_speakers:
                for sid_bytes, sdata_bytes in raw_speakers.items():
                    sid = sid_bytes.decode() if isinstance(sid_bytes, bytes) else str(sid_bytes)
                    sdata_str = sdata_bytes.decode() if isinstance(sdata_bytes, bytes) else str(sdata_bytes)
                    try:
                        self._speakers[sid] = json.loads(sdata_str)
                    except Exception:
                        continue

            return len(self._turns)
        except Exception as exc:
            logger.debug("redis_history_hydration_skipped", room=self.room_name, error=str(exc))
            return len(self._turns)

    # ── Speaker Profiles & Memory ────────────────────────────────────────────

    async def register_speaker(self, speaker_id: str, name: str) -> None:
        """Register or update a speaker identity in the room."""
        if speaker_id not in self._speakers:
            self._speakers[speaker_id] = {
                "speaker_id": speaker_id,
                "name": name,
                "first_seen": time.time(),
                "facts": {},
            }
        elif name and name != speaker_id:
            self._speakers[speaker_id]["name"] = name

        await self._sync_speaker_to_redis(speaker_id)

    async def update_speaker_facts(self, speaker_id: str, facts: dict[str, Any]) -> None:
        """Update personal facts (interests, city, topic preferences) for a speaker."""
        if speaker_id not in self._speakers:
            await self.register_speaker(speaker_id, speaker_id)

        self._speakers[speaker_id]["facts"].update(facts)
        await self._sync_speaker_to_redis(speaker_id)
        logger.info(
            "speaker_facts_updated",
            speaker_id=speaker_id,
            facts=facts,
            room=self.room_name,
        )

    async def _sync_speaker_to_redis(self, speaker_id: str) -> None:
        """Sync a speaker profile to Redis hash."""
        try:
            redis = await self._get_redis()
            if redis:
                key = f"room:{self.room_name}:speakers"
                data = json.dumps(self._speakers[speaker_id])
                await redis.hset(key, speaker_id, data)
                await redis.expire(key, 86400)
        except Exception as exc:
            logger.debug("redis_sync_speaker_skipped", speaker_id=speaker_id, error=str(exc))

    async def get_speaker_profile(self, speaker_id: str) -> str:
        """Return a formatted string describing the speaker for injection into system prompt."""
        speaker = self._speakers.get(speaker_id)
        if not speaker:
            return "New speaker, name not yet known."

        name = speaker.get("name", "Friend")
        facts = speaker.get("facts", {})
        if not facts:
            return f"Speaker Name: {name}"

        fact_lines = [f"{k}: {v}" for k, v in facts.items()]
        return f"Speaker Name: {name} | Known details: " + ", ".join(fact_lines)

    # ── Human Participant Counting ──────────────────────────────────────────

    async def increment_human_count(self) -> int:
        self._human_count += 1
        return self._human_count

    async def decrement_human_count(self) -> int:
        self._human_count = max(0, self._human_count - 1)
        return self._human_count

    # ── Phase 5: Distributed Ingestion, Routing, Speaking Lock ──────────────

    async def claim_voice_ingest(self, turn_id: str, ttl: int = 10) -> bool:
        """Attempt to atomically claim ingestion of a quantized turn.
        Returns True if this bot won the claim; False if already claimed.
        """
        try:
            redis = await self._get_redis()
            if redis:
                key = f"room:{self.room_name}:turn_claim:{turn_id}"
                res = await redis.set(key, "claimed", nx=True, ex=ttl)
                if res:
                    self._claimed_turns[turn_id] = time.time() + ttl
                    return True
                return False
        except Exception as exc:
            logger.debug("redis_claim_voice_ingest_fallback", turn_id=turn_id, error=str(exc))

        # In-memory atomic fallback
        async with self._lock:
            now = time.time()
            if turn_id in self._claimed_turns and self._claimed_turns[turn_id] > now:
                return False
            self._claimed_turns[turn_id] = now + ttl
            return True

    async def set_voice_route(self, turn_id: str, bot_name: str, ttl: int = 15) -> None:
        """Winner writes the determined bot_name route for this turn_id."""
        self._turn_routes[turn_id] = bot_name
        try:
            redis = await self._get_redis()
            if redis:
                key = f"room:{self.room_name}:turn_route:{turn_id}"
                await redis.set(key, bot_name, ex=ttl)
        except Exception as exc:
            logger.debug("redis_set_voice_route_fallback", turn_id=turn_id, error=str(exc))

    async def get_voice_route(self, turn_id: str) -> str | None:
        """Retrieve the determined bot_name route for this turn_id."""
        try:
            redis = await self._get_redis()
            if redis:
                key = f"room:{self.room_name}:turn_route:{turn_id}"
                val = await redis.get(key)
                if val:
                    return val.decode() if isinstance(val, bytes) else str(val)
        except Exception as exc:
            logger.debug("redis_get_voice_route_fallback", turn_id=turn_id, error=str(exc))
        return self._turn_routes.get(turn_id)

    async def wait_for_voice_route(self, turn_id: str, timeout_seconds: float = 0.6) -> str | None:
        """Poll for winner bot to write route decision with low latency (20ms intervals)."""
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            route = await self.get_voice_route(turn_id)
            if route:
                return route
            await asyncio.sleep(0.02)
        return await self.get_voice_route(turn_id)

    async def acquire_speaking_lock(self, bot_name: str, ttl: int = 15) -> bool:
        """Acquire distributed speaking lock so only one bot can speak at a time."""
        try:
            redis = await self._get_redis()
            if redis:
                key = f"room:{self.room_name}:speaking_lock"
                res = await redis.set(key, bot_name, nx=True, ex=ttl)
                if res:
                    self._speaking_lock = bot_name
                    self._speaking_lock_expires = time.time() + ttl
                    return True
                return False
        except Exception as exc:
            logger.debug("redis_acquire_speaking_lock_fallback", bot=bot_name, error=str(exc))

        async with self._lock:
            now = time.time()
            if self._speaking_lock is not None and self._speaking_lock_expires > now:
                if self._speaking_lock == bot_name:
                    return True
                return False
            self._speaking_lock = bot_name
            self._speaking_lock_expires = now + ttl
            return True

    async def release_speaking_lock(self, bot_name: str) -> bool:
        """Release distributed speaking lock if owned by this bot."""
        released = False
        try:
            redis = await self._get_redis()
            if redis:
                key = f"room:{self.room_name}:speaking_lock"
                val = await redis.get(key)
                if val:
                    current_owner = val.decode() if isinstance(val, bytes) else str(val)
                    if current_owner == bot_name:
                        await redis.delete(key)
                        released = True
        except Exception as exc:
            logger.debug("redis_release_speaking_lock_fallback", bot=bot_name, error=str(exc))

        async with self._lock:
            if self._speaking_lock == bot_name:
                self._speaking_lock = None
                self._speaking_lock_expires = 0.0
                released = True
        return released

    async def set_cooldown(self, bot_name: str, duration: float = 1.5) -> None:
        """Set post-speech cooldown for a bot."""
        self._cooldowns[bot_name] = time.time() + duration
        try:
            redis = await self._get_redis()
            if redis:
                key = f"room:{self.room_name}:cooldown:{bot_name}"
                await redis.set(key, "1", px=int(duration * 1000))
        except Exception as exc:
            logger.debug("redis_set_cooldown_fallback", bot=bot_name, error=str(exc))

    async def is_cooldown_active(self, bot_name: str) -> bool:
        """Check if bot cooldown is active."""
        try:
            redis = await self._get_redis()
            if redis:
                key = f"room:{self.room_name}:cooldown:{bot_name}"
                exists = await redis.exists(key)
                if exists:
                    return True
        except Exception as exc:
            logger.debug("redis_is_cooldown_active_fallback", bot=bot_name, error=str(exc))
        return self._cooldowns.get(bot_name, 0.0) > time.time()

    async def set_last_bot(self, bot_name: str) -> None:
        """Update last speaking bot."""
        self._last_bot = bot_name
        try:
            redis = await self._get_redis()
            if redis:
                key = f"room:{self.room_name}:last_bot"
                await redis.set(key, bot_name, ex=86400)
        except Exception as exc:
            logger.debug("redis_set_last_bot_fallback", bot=bot_name, error=str(exc))

    async def get_last_bot(self) -> str | None:
        """Get last speaking bot. Fast memory lookup with Redis fallback."""
        if self._last_bot:
            return self._last_bot
        try:
            redis = await self._get_redis()
            if redis:
                key = f"room:{self.room_name}:last_bot"
                val = await redis.get(key)
                if val:
                    bot = val.decode() if isinstance(val, bytes) else str(val)
                    self._last_bot = bot
                    return bot
        except Exception as exc:
            logger.debug("redis_get_last_bot_fallback", error=str(exc))
        return self._last_bot


    async def acquire_persona_lock(self, persona: str, ttl: int = 60) -> bool:
        """Atomically lock a persona for this room to prevent duplicate agent instances."""
        try:
            redis = await self._get_redis()
            if redis:
                key = f"room:{self.room_name}:active_persona:{persona}"
                acquired = await redis.set(key, "1", nx=True, ex=ttl)
                if acquired:
                    return True
                return False
        except Exception as exc:
            logger.debug("redis_acquire_persona_lock_fallback", persona=persona, error=str(exc))

        async with self._lock:
            now = time.time()
            if not hasattr(self, "_persona_locks"):
                self._persona_locks = {}
            if persona in self._persona_locks and self._persona_locks[persona] > now:
                return False
            self._persona_locks[persona] = now + ttl
            return True

    async def release_persona_lock(self, persona: str) -> bool:
        """Release the persona lock for this room."""
        try:
            redis = await self._get_redis()
            if redis:
                key = f"room:{self.room_name}:active_persona:{persona}"
                await redis.delete(key)
                return True
        except Exception as exc:
            logger.debug("redis_release_persona_lock_fallback", persona=persona, error=str(exc))

        async with self._lock:
            if hasattr(self, "_persona_locks") and persona in self._persona_locks:
                del self._persona_locks[persona]
                return True
            return False
