"""
backend/tests/test_phase4.py
------------------------------
Unit and integration tests for Phase 4: Shared Memory & Speaker Memory.
"""

import asyncio
import pytest
from pathlib import Path
import sys

# Ensure backend root is in sys.path
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from core.room_state import RoomState, TurnRecord
from agents.base_bot import extract_speaker_facts, BaseBotAgent


def test_speaker_fact_extraction():
    """Verify rule-based fact extraction from speech transcripts."""
    # Test Name extraction
    f1 = extract_speaker_facts("Mera naam Rahul hai bhai")
    assert f1.get("name") == "Rahul"

    f2 = extract_speaker_facts("My name is Priya and I live in Delhi")
    assert f2.get("name") == "Priya"
    assert f2.get("city") == "Delhi"

    # Test City extraction
    f3 = extract_speaker_facts("Main Mumbai se hoon")
    assert f3.get("city") == "Mumbai"

    # Test Interest extraction
    f4 = extract_speaker_facts("Mujhe coding pasand hai")
    assert "coding" in f4.get("interests", "").lower()


@pytest.mark.asyncio
async def test_speaker_profile_redis_sync_and_memory():
    """Verify speaker registration and fact updates in RoomState."""
    state = RoomState("test-phase4-room")

    # 1. Register speaker
    await state.register_speaker("user_404", "Amit")
    profile1 = await state.get_speaker_profile("user_404")
    assert "Amit" in profile1

    # 2. Update facts
    await state.update_speaker_facts("user_404", {"city": "Bangalore", "interests": "music"})
    profile2 = await state.get_speaker_profile("user_404")
    assert "Amit" in profile2
    assert "Bangalore" in profile2
    assert "music" in profile2


@pytest.mark.asyncio
async def test_turn_history_capping():
    """Verify RoomState caps turns at max_turns (30)."""
    state = RoomState("test-capping-room")

    for i in range(35):
        turn = TurnRecord(
            speaker_id=f"user_{i}",
            speaker_name=f"User{i}",
            text=f"Message {i}",
        )
        await state.add_turn(turn)

    # Local turns count should not exceed 30
    assert len(state._turns) == 30
    # First turn in memory should be index 5 ("Message 5")
    assert state._turns[0].text == "Message 5"
    assert state._turns[-1].text == "Message 34"


@pytest.mark.asyncio
async def test_redis_history_hydration():
    """Verify load_history_from_redis gracefully handles missing or existing turns."""
    state = RoomState("test-hydration-room")
    count = await state.load_history_from_redis()
    # If no turns exist in Redis yet, returns 0 turns loaded without raising
    assert isinstance(count, int)
