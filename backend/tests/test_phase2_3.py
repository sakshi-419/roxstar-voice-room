"""
backend/tests/test_phase2_3.py
------------------------------
Unit tests for Phase 2 (Providers, RoomState, LatencyTracker, Structured Logger)
and Phase 3 (Dost Persona & Agent logic).
"""

import pytest
import asyncio
import time
from pathlib import Path
import sys

# Ensure backend root is in sys.path
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from core.room_state import RoomState, TurnRecord
from core.latency_tracker import LatencyTracker
from core.logger import sanitize_sensitive_data
from providers.stt import build_stt
from providers.llm import build_llm
from providers.tts import build_tts
from agents.dost_agent import DostAgent
from livekit.agents import llm


@pytest.mark.asyncio
async def test_room_state_turn_memory():
    """Verify RoomState stores turns and builds context strings correctly."""
    state = RoomState("test-room")
    
    # 1. Add user turn
    turn1 = TurnRecord(speaker_id="user_1", speaker_name="Rahul", text="namaste dost")
    await state.add_turn(turn1)
    
    # 2. Add bot turn
    turn2 = TurnRecord(speaker_id="dost", speaker_name="Dost", text="Haan Rahul bhai! Kaise ho?", bot_name="roxstar-dost")
    await state.add_turn(turn2)
    
    # 3. Add follow-up turn
    turn3 = TurnRecord(speaker_id="user_1", speaker_name="Rahul", text="wahi topic simple batao")
    await state.add_turn(turn3)
    
    context = await state.build_context_string(n=10)
    assert "User (Rahul): namaste dost" in context
    assert "Dost: Haan Rahul bhai! Kaise ho?" in context
    assert "User (Rahul): wahi topic simple batao" in context


@pytest.mark.asyncio
async def test_room_state_speaker_profile():
    """Verify speaker registration and profile generation."""
    state = RoomState("test-room")
    await state.register_speaker("user_101", "Priya")
    await state.update_speaker_facts("user_101", {"city": "Mumbai", "interests": "coding"})
    
    profile = await state.get_speaker_profile("user_101")
    assert "Priya" in profile
    assert "Mumbai" in profile


def test_latency_tracker_statistics():
    """Verify LatencyTracker records samples and computes percentiles."""
    tracker = LatencyTracker(window_size=50)
    
    for val in [100.0, 150.0, 200.0, 250.0, 300.0]:
        tracker.record("stt", val)
        tracker.record("llm", val * 2)
    
    with tracker.measure("tts"):
        time.sleep(0.01)
    
    stats = tracker.get_stats()
    assert stats["stt"]["count"] == 5
    assert stats["stt"]["p50"] == 200.0
    assert stats["llm"]["p50"] == 400.0
    assert stats["tts"]["count"] == 1
    assert stats["tts"]["avg"] >= 10.0


def test_secret_sanitizer():
    """Verify structured logger sanitizer masks credentials."""
    event = {
        "event": "connect",
        "url": "rediss://default:supersecretpassword123@delicate-dolphin-283071.upstash.io:6379",
        "api_key": "sk_3774f90f388db3eb7f2ac07741ae797e008d8b10d1375538",
    }
    sanitized = sanitize_sensitive_data(None, "info", event)
    assert "supersecretpassword123" not in sanitized["url"]
    assert "***" in sanitized["url"]
    assert "3774f90f" not in sanitized["api_key"]


def test_provider_factories():
    """Verify STT, LLM, and TTS providers initialize properly with Gemini 3.6 Flash."""
    stt_p = build_stt()
    llm_p = build_llm()
    tts_p = build_tts("dost")
    
    assert stt_p is not None
    assert llm_p is not None
    assert tts_p is not None
    
    # Verify Gemini model configuration and timeout
    if hasattr(llm_p, "_llm"):
        assert llm_p._llm[0].model == "gemini-3.6-flash"
        assert llm_p._llm[1].model == "gemini-3.5-flash"
        assert getattr(llm_p, "_attempt_timeout", 0.0) >= 10.0
    elif hasattr(llm_p, "model"):
        assert llm_p.model == "gemini-3.6-flash"


@pytest.mark.asyncio
async def test_dost_agent_turn_processing():
    """Verify DostAgent updates its prompt with conversational history on user turn."""
    state = RoomState("test-room")
    agent = DostAgent(state=state)
    
    turn_ctx = llm.ChatContext()
    user_msg = llm.ChatMessage(role="user", content=["Arrey dost, wahi topic pe baat karo"])
    
    await agent.on_user_turn_completed(turn_ctx, user_msg)
    
    # Check that turn was recorded in RoomState
    turns = await state.get_context_window()
    assert len(turns) == 1
    assert turns[0].text == "Arrey dost, wahi topic pe baat karo"
    
    # Check that instructions were updated with context
    assert "Arrey dost, wahi topic pe baat karo" in agent.instructions
