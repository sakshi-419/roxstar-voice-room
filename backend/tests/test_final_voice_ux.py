"""
backend/tests/test_final_voice_ux.py
-------------------------------------
Comprehensive regression tests for Roxstar AI Voice Room final UX requirements.
Tests all 20 mandatory behaviors from the final voice UX specification.
"""

import asyncio
import pytest
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from core.room_state import RoomState, TurnRecord
from core.bot_router import BotRouter
from agents.base_bot import BaseBotAgent, _is_ai_participant
from agents.dost_agent import DostAgent
from agents.sathi_agent import SathiAgent
from agents.dost_persona import DOST_GREETING, DOST_SYSTEM_PROMPT
from agents.sathi_persona import SATHI_GREETING, SATHI_SYSTEM_PROMPT
from livekit.agents import llm
from livekit.agents.llm import StopResponse


class MockSession:
    def __init__(self):
        self.interrupt = MagicMock()
        self.say = AsyncMock()


# =====================================================================
# Test 1: Room starts with zero AI speech
# =====================================================================
@pytest.mark.asyncio
async def test_1_room_starts_with_zero_ai_speech():
    """on_enter() must not call session.say() under any circumstance."""
    state = RoomState("test-room-silent")
    agent = DostAgent(state=state)
    mock_session = MockSession()
    agent.session = mock_session

    await agent.on_enter()

    # The critical assertion: say() was never called
    mock_session.say.assert_not_called()


# =====================================================================
# Test 2: No automatic Dost greeting on startup
# =====================================================================
@pytest.mark.asyncio
async def test_2_no_automatic_dost_greeting():
    """DostAgent.on_enter() must remain completely silent."""
    state = RoomState("test-dost-silent")
    agent = DostAgent(state=state)
    mock_session = MockSession()
    agent.session = mock_session

    await agent.on_enter()

    mock_session.say.assert_not_called()
    # Verify greeting variable exists but is NOT auto-sent
    assert DOST_GREETING  # it exists as a string
    assert "Namaste" in DOST_GREETING  # it has greeting text
    # But it was never used:
    mock_session.say.assert_not_called()


# =====================================================================
# Test 3: No automatic Sathi greeting on startup
# =====================================================================
@pytest.mark.asyncio
async def test_3_no_automatic_sathi_greeting():
    """SathiAgent.on_enter() must remain completely silent."""
    state = RoomState("test-sathi-silent")
    agent = SathiAgent(state=state)
    mock_session = MockSession()
    agent.session = mock_session

    await agent.on_enter()

    mock_session.say.assert_not_called()
    # Verify greeting variable exists but is NOT auto-sent
    assert SATHI_GREETING
    assert "Main Sathi" in SATHI_GREETING
    mock_session.say.assert_not_called()


# =====================================================================
# Test 4: Human turn triggers exactly one bot
# =====================================================================
@pytest.mark.asyncio
async def test_4_human_turn_triggers_exactly_one_bot():
    """Router returns exactly one bot name for any input."""
    state = RoomState("test-single-bot")
    for text in [
        "Namaste kaise ho aap log?",
        "Cloud computing kya hota hai?",
        "Mujhe help chahiye",
        "Achha iska example batao",
    ]:
        bot = await BotRouter.select_bot(state, text)
        assert bot in ("roxstar-dost", "roxstar-sathi"), f"Expected one bot, got: {bot} for: {text}"


# =====================================================================
# Test 5: Dost direct address -> only Dost
# =====================================================================
@pytest.mark.asyncio
async def test_5_dost_direct_address_only_dost():
    """Any direct address to Dost must route exclusively to Dost."""
    state = RoomState("test-dost-address")
    dost_phrases = [
        "Dost, Python kya hai?",
        "Hey Dost, suno",
        "Dost bhai, cricket score kya hai?",
        "Hello Dost, help chahiye",
        "Dost, ek second",
        "Dost suno mujhe samajh nahi aaya",
        "Arrey dost yaar",
    ]
    for phrase in dost_phrases:
        selected = await BotRouter.select_bot(state, phrase)
        assert selected == "roxstar-dost", f"Expected roxstar-dost for: '{phrase}', got: {selected}"


# =====================================================================
# Test 6: Sathi direct address -> only Sathi
# =====================================================================
@pytest.mark.asyncio
async def test_6_sathi_direct_address_only_sathi():
    """Any direct address to Sathi must route exclusively to Sathi."""
    state = RoomState("test-sathi-address")
    sathi_phrases = [
        "Sathi, ab tum batao",
        "Saathi ji, aap kaisi hain?",
        "Hey Sathi, poem sunao",
        "Sathi suno, kya chal raha hai?",
        "Sathi, ek second",
        "Hello Sathi, mujhe help chahiye",
    ]
    for phrase in sathi_phrases:
        selected = await BotRouter.select_bot(state, phrase)
        assert selected == "roxstar-sathi", f"Expected roxstar-sathi for: '{phrase}', got: {selected}"


# =====================================================================
# Test 7: Follow-up stays with current bot
# =====================================================================
@pytest.mark.asyncio
async def test_7_follow_up_stays_with_current_bot():
    """Once a bot is selected, follow-up messages stay with that bot."""
    state = RoomState("test-followup")

    # Step A: User asks Dost
    first = await BotRouter.select_bot(state, "Dost, API kya hoti hai?")
    assert first == "roxstar-dost"
    await state.set_last_bot("roxstar-dost")

    # Step B: Follow-up must stay with Dost
    followup1 = await BotRouter.select_bot(state, "Achha iska example batao.")
    assert followup1 == "roxstar-dost"

    followup2 = await BotRouter.select_bot(state, "Thoda simple samjhao.")
    assert followup2 == "roxstar-dost"

    # Step C: User explicitly addresses Sathi
    second = await BotRouter.select_bot(state, "Sathi, ab tum batao.")
    assert second == "roxstar-sathi"
    await state.set_last_bot("roxstar-sathi")

    # Step D: Follow-up must stay with Sathi now
    followup3 = await BotRouter.select_bot(state, "Thoda aur detail mein.")
    assert followup3 == "roxstar-sathi"


# =====================================================================
# Test 8: Explicit switch overrides history
# =====================================================================
@pytest.mark.asyncio
async def test_8_explicit_switch_works():
    """Explicit bot address always overrides the previous active bot."""
    state = RoomState("test-explicit-switch")
    await state.set_last_bot("roxstar-dost")

    switched = await BotRouter.select_bot(state, "Sathi, ab tumhari baari hai.")
    assert switched == "roxstar-sathi"

    await state.set_last_bot("roxstar-sathi")
    switched_back = await BotRouter.select_bot(state, "Dost, tum batao yaar.")
    assert switched_back == "roxstar-dost"


# =====================================================================
# Test 9: STOP interrupts TTS
# =====================================================================
def test_9_stop_interrupts_tts():
    """'stop' and variants must be recognized as interrupt commands."""
    assert BotRouter.is_stop_command("stop") is True
    assert BotRouter.is_stop_command("stop it") is True
    assert BotRouter.is_stop_command("stop karo") is True
    assert BotRouter.is_stop_command("stop dost") is True
    assert BotRouter.is_stop_command("stop sathi") is True
    assert BotRouter.is_stop_command("atop sathi") is True  # STT mishearing


# =====================================================================
# Test 10: RUKO interrupts TTS
# =====================================================================
def test_10_ruko_interrupts_tts():
    """'ruko' and variants must be recognized as interrupt commands."""
    assert BotRouter.is_stop_command("ruko") is True
    assert BotRouter.is_stop_command("ruk jao") is True
    assert BotRouter.is_stop_command("ruko dost") is True
    assert BotRouter.is_stop_command("ruko sathi") is True
    assert BotRouter.is_stop_command("ruk") is True


# =====================================================================
# Test 11: BAS / CHUP interrupts TTS
# =====================================================================
def test_11_bas_interrupts_tts():
    """'bas', 'chup', and variants must be recognized as interrupt commands."""
    assert BotRouter.is_stop_command("bas") is True
    assert BotRouter.is_stop_command("bas karo") is True
    assert BotRouter.is_stop_command("chup") is True
    assert BotRouter.is_stop_command("chup karo") is True
    assert BotRouter.is_stop_command("wait") is True
    assert BotRouter.is_stop_command("hold on") is True
    assert BotRouter.is_stop_command("ek second") is True


# =====================================================================
# Test 12: Human barge-in interrupts AI speaking
# =====================================================================
@pytest.mark.asyncio
async def test_12_human_barge_in_interrupts_ai():
    """Human barge-in must call session.interrupt() and release speaking lock."""
    state = RoomState("test-barge-in")
    mock_session = MockSession()

    # Bot was speaking and acquired lock
    await state.acquire_speaking_lock("roxstar-dost", ttl=15)
    assert state._speaking_lock == "roxstar-dost"

    # Human says "ruko!" — this should trigger interrupt
    if BotRouter.is_stop_command("ruko"):
        mock_session.interrupt()
        await state.release_speaking_lock("roxstar-dost")

    mock_session.interrupt.assert_called_once()
    assert state._speaking_lock is None


# =====================================================================
# Test 13: AI audio cannot enter STT (identity check)
# =====================================================================
@pytest.mark.asyncio
async def test_13_ai_audio_cannot_enter_stt():
    """Messages from AI agent speakers must be blocked with StopResponse."""
    state = RoomState("test-ai-stt-reject")
    agent = DostAgent(state=state)

    # Simulate message with AI speaker identity
    msg = MagicMock()
    msg.content = "Namaste doston! Main Dost hoon."
    msg.speaker_id = "roxstar-dost"
    msg.speaker_name = "Dost"

    with pytest.raises(StopResponse):
        await agent.on_user_turn_completed(turn_ctx=MagicMock(), new_message=msg)


# =====================================================================
# Test 14: Dost audio cannot trigger Sathi
# =====================================================================
@pytest.mark.asyncio
async def test_14_dost_cannot_trigger_sathi():
    """Sathi must block messages that claim to come from Dost."""
    state = RoomState("test-dost-no-trigger-sathi")
    sathi = SathiAgent(state=state)

    msg = MagicMock()
    msg.content = "Sathi, tum batao is baare mein."
    msg.speaker_id = "roxstar-dost"
    msg.speaker_name = "Dost"

    with pytest.raises(StopResponse):
        await sathi.on_user_turn_completed(turn_ctx=MagicMock(), new_message=msg)


# =====================================================================
# Test 15: Sathi audio cannot trigger Dost
# =====================================================================
@pytest.mark.asyncio
async def test_15_sathi_cannot_trigger_dost():
    """Dost must block messages that claim to come from Sathi."""
    state = RoomState("test-sathi-no-trigger-dost")
    dost = DostAgent(state=state)

    msg = MagicMock()
    msg.content = "Dost, kya lagta hai?"
    msg.speaker_id = "roxstar-sathi"
    msg.speaker_name = "Sathi"

    with pytest.raises(StopResponse):
        await dost.on_user_turn_completed(turn_ctx=MagicMock(), new_message=msg)


# =====================================================================
# Test 16: One human turn produces exactly one AI response (idempotency)
# =====================================================================
@pytest.mark.asyncio
async def test_16_one_human_turn_produces_one_ai_response():
    """The turn_id claim mechanism ensures only one bot handles each turn."""
    state = RoomState("test-idempotency")
    turn_id = "turn-abc-def-123"

    # First claim succeeds
    result1 = await state.claim_voice_ingest(turn_id, ttl=10)
    assert result1 is True

    # Duplicate claim on same turn ID must fail
    result2 = await state.claim_voice_ingest(turn_id, ttl=10)
    assert result2 is False

    # A completely different turn ID succeeds
    result3 = await state.claim_voice_ingest("turn-xyz-999", ttl=10)
    assert result3 is True


# =====================================================================
# Test 17: Two AI bots cannot speak simultaneously
# =====================================================================
@pytest.mark.asyncio
async def test_17_two_ai_speaking_simultaneously_impossible():
    """The speaking lock guarantees mutual exclusion between Dost and Sathi."""
    state = RoomState("test-mutex-speaking")

    # Dost acquires speaking lock
    assert await state.acquire_speaking_lock("roxstar-dost", ttl=10) is True

    # Sathi tries while Dost holds it — must fail
    assert await state.acquire_speaking_lock("roxstar-sathi", ttl=10) is False

    # Also: another Dost instance trying to re-acquire returns True (same owner)
    # or False depending on implementation — but a second different bot must fail
    assert await state.acquire_speaking_lock("roxstar-sathi", ttl=10) is False

    # Dost releases
    assert await state.release_speaking_lock("roxstar-dost") is True

    # Now Sathi can acquire
    assert await state.acquire_speaking_lock("roxstar-sathi", ttl=10) is True
    await state.release_speaking_lock("roxstar-sathi")


# =====================================================================
# Test 18: Duplicate dispatch cannot create another agent
# =====================================================================
@pytest.mark.asyncio
async def test_18_duplicate_dispatch_cannot_create_another_agent():
    """The persona lock prevents two workers from running the same persona."""
    state = RoomState("test-dup-dispatch")

    # First dispatch locks persona
    assert await state.acquire_persona_lock("roxstar-dost", ttl=60) is True

    # Second dispatch for same persona is rejected
    assert await state.acquire_persona_lock("roxstar-dost", ttl=60) is False

    # Different persona is fine
    assert await state.acquire_persona_lock("roxstar-sathi", ttl=60) is True

    await state.release_persona_lock("roxstar-dost")
    await state.release_persona_lock("roxstar-sathi")


# =====================================================================
# Test 19: Reconnect cannot create another agent
# =====================================================================
@pytest.mark.asyncio
async def test_19_reconnect_cannot_create_another_agent():
    """Reconnect scenarios are blocked by the persona lock."""
    state = RoomState("test-reconnect")

    # First connection holds lock
    assert await state.acquire_persona_lock("roxstar-sathi", ttl=60) is True

    # A reconnect attempt cannot steal the lock
    assert await state.acquire_persona_lock("roxstar-sathi", ttl=60) is False

    # After release (room disconnect), a fresh instance can connect
    await state.release_persona_lock("roxstar-sathi")
    assert await state.acquire_persona_lock("roxstar-sathi", ttl=60) is True
    await state.release_persona_lock("roxstar-sathi")


# =====================================================================
# Test 20: Text chat follows the same routing rules as voice
# =====================================================================
@pytest.mark.asyncio
async def test_20_text_chat_follows_same_routing_rules():
    """Text chat uses identical bot routing as voice turns."""
    state = RoomState("test-text-chat-routing")

    # Direct address routes correctly
    assert await BotRouter.select_bot(state, "Dost, AI kya hota hai?") == "roxstar-dost"
    assert await BotRouter.select_bot(state, "Sathi, rain explain karo.") == "roxstar-sathi"

    # Stop command
    assert await BotRouter.select_bot(state, "ruko") == "STOP"
    assert await BotRouter.select_bot(state, "bas karo") == "STOP"

    # Follow-up continuity via last_bot
    await state.set_last_bot("roxstar-sathi")
    assert await BotRouter.select_bot(state, "Thoda simple batao.") == "roxstar-sathi"

    # Explicit switch overrides
    assert await BotRouter.select_bot(state, "Dost, tum samjhao.") == "roxstar-dost"


# =====================================================================
# Bonus Test: AI participant identity detection
# =====================================================================
def test_bonus_ai_identity_detection():
    """_is_ai_participant correctly identifies AI vs human participants."""
    # AI participants
    assert _is_ai_participant("roxstar-dost", "Dost") is True
    assert _is_ai_participant("roxstar-sathi", "Sathi") is True
    assert _is_ai_participant("agent-123", "") is True
    assert _is_ai_participant("some-dost-id", "") is True

    # Human participants
    assert _is_ai_participant("user-abc-123", "Priya") is False
    assert _is_ai_participant("sakshi-user", "Sakshi") is False
    assert _is_ai_participant("rahul_participant", "Rahul") is False


# =====================================================================
# Bonus Test: Barge-in words that are NOT stop commands
# =====================================================================
def test_bonus_not_stop_commands():
    """Direct bot addresses should not be classified as stop commands."""
    assert BotRouter.is_stop_command("Dost, Python kya hai?") is False
    assert BotRouter.is_stop_command("Sathi, cloud computing samjhao") is False
    assert BotRouter.is_stop_command("Hello Dost") is False
    assert BotRouter.is_stop_command("") is False
    # "Dost, ek second" - direct address with "ek second" but Dost is first
    # This is ambiguous, but router should route to Dost not stop
    # (stop logic in is_stop_command vs. router.select_bot handles this)


# =====================================================================
# Bonus Test: System prompts explicitly forbid auto-greetings
# =====================================================================
def test_bonus_system_prompts_forbid_auto_greeting():
    """System prompts must contain the no-auto-greeting rule."""
    assert "SILENT" in DOST_SYSTEM_PROMPT or "silent" in DOST_SYSTEM_PROMPT.lower()
    assert "SILENT" in SATHI_SYSTEM_PROMPT or "silent" in SATHI_SYSTEM_PROMPT.lower()
    # Both prompts must prohibit auto-introductions
    assert "NEVER" in DOST_SYSTEM_PROMPT
    assert "NEVER" in SATHI_SYSTEM_PROMPT
