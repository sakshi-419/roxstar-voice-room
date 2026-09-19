"""
backend/tests/test_polish.py
----------------------------
Focused tests for final polish requirements:
  1. Dost persona identifies as male Dost.
  2. Sathi persona identifies as female Sathi.
  3. Dost uses male TTS voice configuration.
  4. Sathi uses female TTS voice configuration.
  5. Dost and Sathi have different voice IDs.
  6. Explicit "Dost" routes only to Dost.
  7. Explicit "Sathi" routes only to Sathi.
  8. Follow-up maintains correct conversational context.
  9. One user turn produces exactly one bot response.
  10. Duplicate agent summon remains idempotent.
  11. Google STT is not initialized without Google Cloud credentials.
"""

import asyncio
import uuid
import os
import pytest
from pathlib import Path
import sys
from unittest.mock import AsyncMock, MagicMock, patch

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from agents.dost_persona import DOST_SYSTEM_PROMPT, DOST_GREETING
from agents.sathi_persona import SATHI_SYSTEM_PROMPT, SATHI_GREETING
from providers.tts import DEFAULT_DOST_VOICE, DEFAULT_SATHI_VOICE, build_tts
from core.room_state import RoomState
from core.bot_router import BotRouter
from server.token_server import dispatch_agents, DispatchRequest
from agents.dost_agent import DostAgent
from agents.sathi_agent import SathiAgent
from livekit.agents import llm
from livekit.agents.llm import StopResponse
from providers.stt import build_stt
from livekit.plugins import deepgram


def test_dost_persona_identifies_as_male_dost():
    """1. Dost persona identifies as male Dost."""
    prompt = DOST_SYSTEM_PROMPT.lower()
    assert "roxstar ai dost" in prompt
    assert "male" in prompt
    assert "main dost hoon" in prompt
    assert "not sathi" in prompt
    assert "Main Dost hoon" in DOST_GREETING


def test_sathi_persona_identifies_as_female_sathi():
    """2. Sathi persona identifies as female Sathi."""
    prompt = SATHI_SYSTEM_PROMPT.lower()
    assert "roxstar ai sathi" in prompt
    assert "female" in prompt
    assert "main sathi hoon" in prompt
    assert "not dost" in prompt
    assert "Main Sathi hoon" in SATHI_GREETING


def test_dost_uses_male_tts_voice_configuration():
    """3. Dost uses male TTS voice configuration (Charlie: IKne3meq5aSn9XLyUdCD)."""
    assert DEFAULT_DOST_VOICE == "IKne3meq5aSn9XLyUdCD"


def test_sathi_uses_female_tts_voice_configuration():
    """4. Sathi uses female TTS voice configuration (Bella: EXAVITQu4vr4xnSDxMaL)."""
    assert DEFAULT_SATHI_VOICE == "EXAVITQu4vr4xnSDxMaL"


def test_dost_and_sathi_have_different_voice_ids():
    """5. Dost and Sathi have different voice IDs."""
    assert DEFAULT_DOST_VOICE != DEFAULT_SATHI_VOICE


@pytest.mark.asyncio
async def test_explicit_dost_routes_only_to_dost():
    """6. Explicit 'Dost' routes only to Dost."""
    state = RoomState(f"test-explicit-dost-{uuid.uuid4().hex[:8]}")
    route = await BotRouter.select_bot(state, "Dost, hello. Who are you?")
    assert route == "roxstar-dost"


@pytest.mark.asyncio
async def test_explicit_sathi_routes_only_to_sathi():
    """7. Explicit 'Sathi' routes only to Sathi."""
    state = RoomState(f"test-explicit-sathi-{uuid.uuid4().hex[:8]}")
    route = await BotRouter.select_bot(state, "Sathi, hello. Who are you?")
    assert route == "roxstar-sathi"


@pytest.mark.asyncio
async def test_follow_up_maintains_correct_conversational_context():
    """8. Follow-up maintains correct conversational context without sudden switching."""
    state = RoomState(f"test-followup-context-{uuid.uuid4().hex[:8]}")

    # Turn 1: User asks Dost
    route1 = await BotRouter.select_bot(state, "Dost, mujhe Python samjhao.")
    assert route1 == "roxstar-dost"
    await state.set_last_bot("roxstar-dost")

    # Turn 2: User follow-up (no explicit name)
    route2 = await BotRouter.select_bot(state, "Thoda simple batao.")
    assert route2 == "roxstar-dost", "Follow-up to Dost must stay with Dost"

    # Turn 3: User explicitly switches to Sathi
    route3 = await BotRouter.select_bot(state, "Sathi, iska ek simple example do.")
    assert route3 == "roxstar-sathi"
    await state.set_last_bot("roxstar-sathi")

    # Turn 4: User follow-up to Sathi
    route4 = await BotRouter.select_bot(state, "Ek real-life example do aur samjhao.")
    assert route4 == "roxstar-sathi", "Follow-up to Sathi must stay with Sathi"


@pytest.mark.asyncio
async def test_one_user_turn_produces_exactly_one_bot_response():
    """9. One user turn produces exactly one bot response."""
    state = RoomState(f"test-single-bot-response-{uuid.uuid4().hex[:8]}")
    user_text = "Dost, Python automation kya hota hai?"
    target_bot = await BotRouter.select_bot(state, user_text)
    assert target_bot == "roxstar-dost"

    dost = DostAgent(state=state)
    sathi = SathiAgent(state=state)
    turn_ctx = llm.ChatContext()
    user_msg = llm.ChatMessage(role="user", content=[user_text])

    # Unselected bot (Sathi) raises StopResponse
    with pytest.raises(StopResponse):
        await sathi.on_user_turn_completed(turn_ctx, user_msg)

    # Selected bot (Dost) proceeds and updates context
    await dost.on_user_turn_completed(turn_ctx, user_msg)
    assert "Python automation" in dost.instructions


@pytest.mark.asyncio
async def test_duplicate_agent_summon_remains_idempotent():
    """10. Duplicate agent summon remains idempotent."""
    req = DispatchRequest(room_name=f"test-idempotent-{uuid.uuid4().hex[:8]}")

    mock_participant = MagicMock()
    mock_participant.name = "Dost"
    mock_participant.identity = "agent-dost-999"

    with patch("server.token_server.LiveKitAPI") as MockLK, patch("server.token_server.get_redis", AsyncMock(return_value=None)):
        lk_instance = MagicMock()
        MockLK.return_value.__aenter__.return_value = lk_instance
        lk_instance.room.list_participants = AsyncMock(return_value=MagicMock(participants=[mock_participant]))
        lk_instance.agent_dispatch.list_dispatch = AsyncMock(return_value=[])
        lk_instance.agent_dispatch.create_dispatch = AsyncMock()

        res = await dispatch_agents(req)
        assert "roxstar-dost" in res.already_running
        assert "roxstar-dost" not in res.dispatched


def test_google_stt_is_not_initialized_without_credentials():
    """11. Google STT is not initialized without Google Cloud credentials."""
    with patch.dict(os.environ, {"GOOGLE_APPLICATION_CREDENTIALS": "", "GOOGLE_API_KEY": "dummy_key"}, clear=False):
        provider = build_stt()
        assert isinstance(provider, deepgram.STT)


@pytest.mark.asyncio
async def test_follow_up_after_dost_stays_with_dost():
    """Follow-up query after Dost must stay with Dost."""
    state = RoomState(f"test-dost-followup-{uuid.uuid4().hex[:8]}")
    await state.set_last_bot("roxstar-dost")

    follow_ups = [
        "Thoda aur simple batao.",
        "Aur explain karo.",
        "Ek example do.",
        "Wahi topic.",
        "Aur batao.",
        "Simple language mein samjhao.",
        "Isko thoda detail mein batao.",
    ]
    for q in follow_ups:
        route = await BotRouter.select_bot(state, q)
        assert route == "roxstar-dost", f"Query '{q}' after Dost should route to roxstar-dost, got {route}"


@pytest.mark.asyncio
async def test_follow_up_after_sathi_stays_with_sathi():
    """Follow-up query after Sathi must stay with Sathi."""
    state = RoomState(f"test-sathi-followup-{uuid.uuid4().hex[:8]}")
    await state.set_last_bot("roxstar-sathi")

    follow_ups = [
        "Thoda aur simple batao.",
        "Aur explain karo.",
        "Ek example do.",
        "Wahi topic.",
        "Aur batao.",
        "Simple language mein samjhao.",
        "Isko thoda detail mein batao.",
    ]
    for q in follow_ups:
        route = await BotRouter.select_bot(state, q)
        assert route == "roxstar-sathi", f"Query '{q}' after Sathi should route to roxstar-sathi, got {route}"


@pytest.mark.asyncio
async def test_explicit_sathi_overrides_dost_follow_up():
    """Explicit direct addressing to Sathi overrides Dost follow-up context."""
    state = RoomState(f"test-override-sathi-{uuid.uuid4().hex[:8]}")
    await state.set_last_bot("roxstar-dost")

    route = await BotRouter.select_bot(state, "Sathi, thoda aur simple batao.")
    assert route == "roxstar-sathi"


@pytest.mark.asyncio
async def test_explicit_dost_overrides_sathi_follow_up():
    """Explicit direct addressing to Dost overrides Sathi follow-up context."""
    state = RoomState(f"test-override-dost-{uuid.uuid4().hex[:8]}")
    await state.set_last_bot("roxstar-sathi")

    route = await BotRouter.select_bot(state, "Dost, thoda aur explain karo.")
    assert route == "roxstar-dost"


@pytest.mark.asyncio
async def test_complete_five_turn_conversation_sequence():
    """Exact 5-turn sequence specified in user requirements."""
    state = RoomState(f"test-5turn-seq-{uuid.uuid4().hex[:8]}")

    # Turn 1: Dost, Python automation kya hota hai? -> roxstar-dost
    r1 = await BotRouter.select_bot(state, "Dost, Python automation kya hota hai?")
    assert r1 == "roxstar-dost"
    await state.set_last_bot(r1)

    # Turn 2: Thoda simple batao. -> roxstar-dost
    r2 = await BotRouter.select_bot(state, "Thoda simple batao.")
    assert r2 == "roxstar-dost"
    await state.set_last_bot(r2)

    # Turn 3: Ek real-life example do. -> roxstar-dost
    r3 = await BotRouter.select_bot(state, "Ek real-life example do.")
    assert r3 == "roxstar-dost"
    await state.set_last_bot(r3)

    # Turn 4: Sathi, tum kya sochti ho? -> roxstar-sathi
    r4 = await BotRouter.select_bot(state, "Sathi, tum kya sochti ho?")
    assert r4 == "roxstar-sathi"
    await state.set_last_bot(r4)

    # Turn 5: Thoda aur explain karo. -> roxstar-sathi
    r5 = await BotRouter.select_bot(state, "Thoda aur explain karo.")
    assert r5 == "roxstar-sathi"
    await state.set_last_bot(r5)
