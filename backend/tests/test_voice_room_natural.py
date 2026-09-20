"""
backend/tests/test_voice_room_natural.py
----------------------------------------
Regression tests validating the natural voice room experience:
1. Room starts with zero AI speech
2. No automatic Dost greeting
3. No automatic Sathi greeting
4. Human turn triggers exactly one bot
5. Dost direct address -> only Dost
6. Sathi direct address -> only Sathi
7. Follow-up stays with current bot
8. Explicit switch works
9. STOP interrupts TTS
10. RUKO interrupts TTS
11. BAS interrupts TTS
12. Human barge-in interrupts AI
13. AI audio cannot enter STT
14. Dost cannot trigger Sathi
15. Sathi cannot trigger Dost
16. One human turn produces one AI response (idempotency)
17. Two AI speaking simultaneously is impossible
18. Duplicate dispatch cannot create another agent
19. Reconnect cannot create another agent
20. Text chat follows the same routing rules
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from core.bot_router import BotRouter
from core.room_state import RoomState
from agents.base_bot import BaseBotAgent
from agents.dost_agent import DostAgent
from agents.sathi_agent import SathiAgent
from livekit.agents import StopResponse
from livekit import rtc


class MockSession:
    def __init__(self):
        self.say = AsyncMock()
        self.interrupt = MagicMock()


# 1. Room starts with zero AI speech
@pytest.mark.asyncio
async def test_room_starts_with_zero_ai_speech():
    state = RoomState("test-silent-room")
    bot = BaseBotAgent(state=state, bot_name="generic-bot", greeting="Namaste")
    mock_session = MockSession()
    bot.session = mock_session

    # Call on_enter: MUST be silent!
    await bot.on_enter()
    mock_session.say.assert_not_called()


# 2. No automatic Dost greeting
@pytest.mark.asyncio
async def test_no_automatic_dost_greeting():
    state = RoomState("test-dost-silent")
    agent = DostAgent(state=state)
    mock_session = MockSession()
    agent.session = mock_session

    await agent.on_enter()
    mock_session.say.assert_not_called()


# 3. No automatic Sathi greeting
@pytest.mark.asyncio
async def test_no_automatic_sathi_greeting():
    state = RoomState("test-sathi-silent")
    agent = SathiAgent(state=state)
    mock_session = MockSession()
    agent.session = mock_session

    await agent.on_enter()
    mock_session.say.assert_not_called()


# 4. Human turn triggers exactly one bot
@pytest.mark.asyncio
async def test_human_turn_triggers_exactly_one_bot():
    state = RoomState("test-single-bot")
    bot = await BotRouter.select_bot(state, "Namaste kaise ho aap log?")
    assert bot in ("roxstar-dost", "roxstar-sathi")
    assert isinstance(bot, str)


# 5. Dost direct address -> only Dost
@pytest.mark.asyncio
async def test_dost_direct_address_only_dost():
    state = RoomState("test-dost-address")
    test_phrases = [
        "Dost, Python kya hai?",
        "Hey Dost, suno",
        "Dost bhai, cricket score kya hai?",
        "Hello Dost, help chahiye",
        "Dost, ek second",
    ]
    for phrase in test_phrases:
        selected = await BotRouter.select_bot(state, phrase)
        assert selected == "roxstar-dost", f"Failed for phrase: {phrase}"


# 6. Sathi direct address -> only Sathi
@pytest.mark.asyncio
async def test_sathi_direct_address_only_sathi():
    state = RoomState("test-sathi-address")
    test_phrases = [
        "Sathi, ab tum batao",
        "Saathi ji, aap kaisi hain?",
        "Hey Sathi, poem sunao",
        "Sathi suno, kya chal raha hai?",
        "Sathi, ek second",
    ]
    for phrase in test_phrases:
        selected = await BotRouter.select_bot(state, phrase)
        assert selected == "roxstar-sathi", f"Failed for phrase: {phrase}"


# 7. Follow-up stays with current bot
@pytest.mark.asyncio
async def test_follow_up_stays_with_current_bot():
    state = RoomState("test-followup")

    # Step A: User asks Dost
    first = await BotRouter.select_bot(state, "Dost, API kya hoti hai?")
    assert first == "roxstar-dost"
    await state.set_last_bot("roxstar-dost")

    # Step B: Follow-up must stay with Dost
    followup1 = await BotRouter.select_bot(state, "Achha iska example batao.")
    assert followup1 == "roxstar-dost"

    # Step C: User addresses Sathi
    second = await BotRouter.select_bot(state, "Sathi, ab tum batao.")
    assert second == "roxstar-sathi"
    await state.set_last_bot("roxstar-sathi")

    # Step D: Follow-up must stay with Sathi
    followup2 = await BotRouter.select_bot(state, "Thoda simple bhasha mein samjhao.")
    assert followup2 == "roxstar-sathi"


# 8. Explicit switch overrides history
@pytest.mark.asyncio
async def test_explicit_switch_works():
    state = RoomState("test-explicit-switch")
    await state.set_last_bot("roxstar-dost")

    # Explicit switch to Sathi overrides active Dost conversation
    switched = await BotRouter.select_bot(state, "Sathi, ab tumhari baari hai.")
    assert switched == "roxstar-sathi"


# 9. STOP interrupts TTS
def test_stop_interrupts_tts():
    assert BotRouter.is_stop_command("stop") is True
    assert BotRouter.is_stop_command("stop it") is True
    assert BotRouter.is_stop_command("stop karo") is True
    assert BotRouter.is_stop_command("stop dost") is True
    assert BotRouter.is_stop_command("stop sathi") is True


# 10. RUKO interrupts TTS
def test_ruko_interrupts_tts():
    assert BotRouter.is_stop_command("ruko") is True
    assert BotRouter.is_stop_command("ruk jao") is True
    assert BotRouter.is_stop_command("ruko dost") is True
    assert BotRouter.is_stop_command("ruko sathi") is True


# 11. BAS interrupts TTS
def test_bas_interrupts_tts():
    assert BotRouter.is_stop_command("bas") is True
    assert BotRouter.is_stop_command("bas karo") is True
    assert BotRouter.is_stop_command("chup") is True
    assert BotRouter.is_stop_command("chup karo") is True


# 12. Human barge-in interrupts AI
@pytest.mark.asyncio
async def test_human_barge_in_interrupts_ai():
    state = RoomState("test-barge-in")
    mock_session = MockSession()

    # Bot was speaking and acquired lock
    await state.acquire_speaking_lock("roxstar-dost", ttl=15)
    assert state._speaking_lock == "roxstar-dost"

    # Human speaks "ruko!"
    if BotRouter.is_stop_command("ruko"):
        mock_session.interrupt()
        await state.release_speaking_lock("roxstar-dost")

    mock_session.interrupt.assert_called_once()
    assert state._speaking_lock is None


# 13. AI audio cannot enter STT
@pytest.mark.asyncio
async def test_ai_audio_cannot_enter_stt():
    state = RoomState("test-ai-stt-reject")
    agent = DostAgent(state=state)

    # Simulate message from an agent
    msg = MagicMock()
    msg.content = "Namaste doston! Main Dost hoon."
    msg.speaker_id = "roxstar-dost"
    msg.speaker_name = "Dost"

    with pytest.raises(StopResponse):
        await agent.on_user_turn_completed(turn_ctx=MagicMock(), new_message=msg)


# 14. Dost cannot trigger Sathi
@pytest.mark.asyncio
async def test_dost_cannot_trigger_sathi():
    state = RoomState("test-dost-no-trigger-sathi")
    sathi = SathiAgent(state=state)

    msg = MagicMock()
    msg.content = "Sathi, tum batao is baare mein."
    msg.speaker_id = "roxstar-dost"
    msg.speaker_name = "Dost"

    with pytest.raises(StopResponse):
        await sathi.on_user_turn_completed(turn_ctx=MagicMock(), new_message=msg)


# 15. Sathi cannot trigger Dost
@pytest.mark.asyncio
async def test_sathi_cannot_trigger_dost():
    state = RoomState("test-sathi-no-trigger-dost")
    dost = DostAgent(state=state)

    msg = MagicMock()
    msg.content = "Dost, kya lagta hai?"
    msg.speaker_id = "roxstar-sathi"
    msg.speaker_name = "Sathi"

    with pytest.raises(StopResponse):
        await dost.on_user_turn_completed(turn_ctx=MagicMock(), new_message=msg)


# 16. One human turn produces one AI response (idempotency claim)
@pytest.mark.asyncio
async def test_one_human_turn_produces_one_ai_response():
    state = RoomState("test-idempotency")
    turn_id = "turn-abc-123"

    # First claim succeeds
    assert await state.claim_voice_ingest(turn_id, ttl=10) is True

    # Duplicate claim on same turn ID fails
    assert await state.claim_voice_ingest(turn_id, ttl=10) is False


# 17. Two AI speaking simultaneously is impossible (mutual exclusion lock)
@pytest.mark.asyncio
async def test_two_ai_speaking_simultaneously_impossible():
    state = RoomState("test-mutex-speaking")

    # Dost acquires lock
    assert await state.acquire_speaking_lock("roxstar-dost", ttl=10) is True

    # Sathi tries to acquire lock while Dost holds it -> Must fail
    assert await state.acquire_speaking_lock("roxstar-sathi", ttl=10) is False

    # Dost releases lock
    assert await state.release_speaking_lock("roxstar-dost") is True

    # Now Sathi can acquire lock
    assert await state.acquire_speaking_lock("roxstar-sathi", ttl=10) is True
    await state.release_speaking_lock("roxstar-sathi")


# 18. Duplicate dispatch cannot create another agent
@pytest.mark.asyncio
async def test_duplicate_dispatch_cannot_create_another_agent():
    state = RoomState("test-dup-dispatch")

    # First dispatch locks persona
    assert await state.acquire_persona_lock("roxstar-dost", ttl=60) is True

    # Second dispatch for same persona is rejected
    assert await state.acquire_persona_lock("roxstar-dost", ttl=60) is False


# 19. Reconnect cannot create another agent
@pytest.mark.asyncio
async def test_reconnect_cannot_create_another_agent():
    state = RoomState("test-reconnect")

    # First connection holds lock
    assert await state.acquire_persona_lock("roxstar-sathi", ttl=60) is True

    # Another instance cannot steal the lock
    assert await state.acquire_persona_lock("roxstar-sathi", ttl=60) is False


# 20. Text chat follows the same routing rules
@pytest.mark.asyncio
async def test_text_chat_follows_same_routing_rules():
    state = RoomState("test-text-chat-routing")

    # Direct address
    assert await BotRouter.select_bot(state, "Dost, AI kya hota hai?") == "roxstar-dost"
    assert await BotRouter.select_bot(state, "Sathi, rain explain karo.") == "roxstar-sathi"

    # Stop command
    assert await BotRouter.select_bot(state, "ruko karo") == "STOP"

    # Follow-up continuity
    await state.set_last_bot("roxstar-sathi")
    assert await BotRouter.select_bot(state, "Thoda simple batao.") == "roxstar-sathi"
