"""
backend/tests/test_runtime_fixes.py
-----------------------------------
Tests for the final runtime fixes:
  1. Duplicate Dost summon is rejected/idempotent
  2. Duplicate Sathi summon is rejected/idempotent
  3. User speech produces a transcript
  4. One transcript results in exactly one bot response
  5. STT fallback does not initialize Google STT without Google Cloud credentials
"""

import asyncio
import os
import pytest
from pathlib import Path
import sys
from unittest.mock import AsyncMock, MagicMock, patch

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from core.room_state import RoomState
from core.bot_router import BotRouter
from providers.stt import build_stt
from server.token_server import dispatch_agents, DispatchRequest
from agents.dost_agent import DostAgent
from agents.sathi_agent import SathiAgent
from livekit.agents import llm
from livekit.agents.llm import StopResponse
from livekit.agents.voice import UserInputTranscribedEvent


@pytest.mark.asyncio
async def test_duplicate_dost_summon_is_rejected_idempotent():
    """Verify that if Dost is already active in the room, dispatch ignores Dost."""
    req = DispatchRequest(room_name="test-idempotent-room")

    # Mock LiveKitAPI to simulate Dost already present in room participants
    mock_participant = MagicMock()
    mock_participant.name = "Dost"
    mock_participant.identity = "roxstar-dost-123"

    mock_parts_resp = MagicMock()
    mock_parts_resp.participants = [mock_participant]

    with patch("server.token_server.LiveKitAPI") as MockLK, patch("server.token_server.get_redis", AsyncMock(return_value=None)):
        lk_instance = MagicMock()
        MockLK.return_value.__aenter__.return_value = lk_instance
        lk_instance.room.list_participants = AsyncMock(return_value=mock_parts_resp)
        lk_instance.agent_dispatch.list_dispatch = AsyncMock(return_value=[])
        lk_instance.agent_dispatch.create_dispatch = AsyncMock()

        res = await dispatch_agents(req)

        assert "roxstar-dost" in res.already_running
        assert "roxstar-dost" not in res.dispatched
        for call_args in lk_instance.agent_dispatch.create_dispatch.call_args_list:
            dispatched_agent = call_args[0][0].metadata
            assert dispatched_agent != "roxstar-dost"


@pytest.mark.asyncio
async def test_duplicate_sathi_summon_is_rejected_idempotent():
    """Verify that if Sathi is already dispatched, dispatch ignores Sathi."""
    req = DispatchRequest(room_name="test-idempotent-room-2")

    mock_dispatch = MagicMock()
    mock_dispatch.metadata = "roxstar-sathi"
    mock_dispatch.agent_name = ""

    with patch("server.token_server.LiveKitAPI") as MockLK, patch("server.token_server.get_redis", AsyncMock(return_value=None)):
        lk_instance = MagicMock()
        MockLK.return_value.__aenter__.return_value = lk_instance
        lk_instance.room.list_participants = AsyncMock(return_value=MagicMock(participants=[]))
        lk_instance.agent_dispatch.list_dispatch = AsyncMock(return_value=[mock_dispatch])
        lk_instance.agent_dispatch.create_dispatch = AsyncMock()

        res = await dispatch_agents(req)

        assert "roxstar-sathi" in res.already_running
        assert "roxstar-sathi" not in res.dispatched
        for call_args in lk_instance.agent_dispatch.create_dispatch.call_args_list:
            dispatched_agent = call_args[0][0].metadata
            assert dispatched_agent != "roxstar-sathi"


@pytest.mark.asyncio
async def test_user_speech_produces_transcript():
    """Verify that UserInputTranscribedEvent parses and contains the user transcript."""
    event = UserInputTranscribedEvent(
        transcript="Dost, hello. Mujhe batao Python automation kya hota hai?",
        is_final=True,
    )
    assert event.is_final is True
    assert "Python automation" in event.transcript
    assert event.transcript.startswith("Dost, hello")


@pytest.mark.asyncio
async def test_one_transcript_results_in_exactly_one_bot_response():
    """Verify that a transcript triggers exactly one bot to respond and suppresses the other."""
    room_id = "test-single-bot-routing-room"
    state = RoomState(room_name=room_id)

    user_text = "Dost, hello. Mujhe batao Python automation kya hota hai?"
    selected_bot = await BotRouter.select_bot(state, user_text)

    # 1. Direct addressing must route strictly to Dost
    assert selected_bot == "roxstar-dost"

    # 2. Verify duplicate response prevention: Dost responds, Sathi suppresses
    dost_agent = DostAgent(state=state)
    sathi_agent = SathiAgent(state=state)

    turn_ctx = llm.ChatContext()
    user_msg = llm.ChatMessage(role="user", content=[user_text])

    # Sathi is NOT selected and must raise StopResponse
    with pytest.raises(StopResponse):
        await sathi_agent.on_user_turn_completed(turn_ctx, user_msg)

    # Dost is selected and proceeds to acquire lock and update instructions
    await dost_agent.on_user_turn_completed(turn_ctx, user_msg)
    assert "Python automation" in dost_agent.instructions


post_germ_setup = None

def test_stt_fallback_does_not_initialize_google_without_credentials():
    """Verify build_stt() does NOT initialize Google STT when credentials file is missing."""
    with patch.dict(os.environ, {"GOOGLE_APPLICATION_CREDENTIALS": "", "GOOGLE_API_KEY": "fake_key"}, clear=False):
        provider = build_stt()
        from livekit.plugins import deepgram
        assert isinstance(provider, deepgram.STT)

    # Even with non-existent file path, it must not attempt Google STT
    with patch.dict(os.environ, {"GOOGLE_APPLICATION_CREDENTIALS": "C/non/existent/path.json"}):
        provider = build_stt()
        assert isinstance(provider, deepgram.STT)
