"""
backend/tests/test_phase5.py
----------------------------
Comprehensive test suite for Phase 5:
  1. Direct Dost addressing ("Dost", "Dostu")
  2. Direct Sathi addressing ("Sathi", "Saathi", "Sathiji")
  3. "bhai" / "yaar" as persona affinity (NOT guaranteed direct Dost)
  4. Emotional affinity -> Sathi
  5. Technical / playful affinity -> Dost
  6. 10-query alternation
  7. Concurrent exactly-once voice ingestion claim
  8. Routing decision coordination
  9. Speaking lock mutual exclusion and ownership release
  10. Duplicate response suppression via StopResponse
  11. SathiAgent and DostAgent instantiation
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
from core.bot_router import BotRouter
from core.redis_client import close_redis
from agents.dost_agent import DostAgent
from agents.sathi_agent import SathiAgent
from livekit.agents import llm
from livekit.agents.llm import StopResponse


@pytest.fixture(autouse=True)
async def cleanup_redis_per_test():
    """Ensure clean Redis client lifecycle between async test cases."""
    yield
    await close_redis()


@pytest.mark.asyncio
async def test_direct_addressing_dost():
    """Verify explicit Dost name mentions route to roxstar-dost."""
    state = RoomState("test-router-dost")

    # "Dost"
    res1 = await BotRouter.select_bot(state, "Dost, suno zara ek baat")
    assert res1 == "roxstar-dost"

    # "Dostu"
    res2 = await BotRouter.select_bot(state, "Arrey Dostu kaise ho?")
    assert res2 == "roxstar-dost"

    # Case-insensitivity
    res3 = await BotRouter.select_bot(state, "kya haal hai DOST?")
    assert res3 == "roxstar-dost"


@pytest.mark.asyncio
async def test_direct_addressing_sathi():
    """Verify explicit Sathi name mentions route to roxstar-sathi."""
    state = RoomState("test-router-sathi")

    # "Sathi"
    res1 = await BotRouter.select_bot(state, "Sathi, mujhe tumse baat karni hai")
    assert res1 == "roxstar-sathi"

    # "Saathi"
    res2 = await BotRouter.select_bot(state, "Haan Saathi, batao")
    assert res2 == "roxstar-sathi"

    # "Sathiji"
    res3 = await BotRouter.select_bot(state, "Namaste Sathiji, aap kaisi hain?")
    assert res3 == "roxstar-sathi"


@pytest.mark.asyncio
async def test_bhai_yaar_affinity_not_direct_dost():
    """Verify 'bhai' and 'yaar' are persona affinity, not guaranteed direct Dost."""
    state = RoomState("test-router-affinity")

    # 1. When Sathi is directly addressed, 'yaar' or 'bhai' does NOT override Sathi
    res1 = await BotRouter.select_bot(state, "Sathi yaar, mujhe bohot accha laga")
    assert res1 == "roxstar-sathi"

    res2 = await BotRouter.select_bot(state, "Sathiji bhai ek poem sunao")
    assert res2 == "roxstar-sathi"

    # 2. When no direct name is used, 'bhai' or 'yaar' acts as affinity for Dost
    res3 = await BotRouter.select_bot(state, "kya chal raha hai bhai")
    assert res3 == "roxstar-dost"

    res4 = await BotRouter.select_bot(state, "arre yaar maza aa gaya")
    assert res4 == "roxstar-dost"


@pytest.mark.asyncio
async def test_emotional_and_thoughtful_affinity():
    """Verify emotional, reflective queries route to roxstar-sathi."""
    state = RoomState("test-router-emotional")

    # Deep emotional / sadness query
    res1 = await BotRouter.select_bot(state, "Aaj mera dil bohot udas aur pareshan hai")
    assert res1 == "roxstar-sathi"

    # Peaceful / poetry query
    res2 = await BotRouter.select_bot(state, "thoda sukoon chahiye, ek acchi shayari ya poem")
    assert res2 == "roxstar-sathi"


@pytest.mark.asyncio
async def test_technical_and_playful_affinity():
    """Verify technical, gaming, and playful banter queries route to roxstar-dost."""
    state = RoomState("test-router-tech")

    # Technical query
    res1 = await BotRouter.select_bot(state, "Python code me bug kaise fix karein?")
    assert res1 == "roxstar-dost"

    # Cricket / Gaming query
    res2 = await BotRouter.select_bot(state, "cricket match ka kya score chal raha hai?")
    assert res2 == "roxstar-dost"


@pytest.mark.asyncio
async def test_ten_query_alternation():
    """Verify neutral queries cleanly alternate between Dost and Sathi across 10 turns."""
    state = RoomState("test-router-alternation")

    current_expected = "roxstar-dost"

    for i in range(10):
        neutral_query = f"Yeh statement number {i} hai"
        selected = await BotRouter.select_bot(state, neutral_query)
        assert selected == current_expected, f"Turn {i}: expected {current_expected}, got {selected}"

        await state.set_last_bot(selected)
        current_expected = "roxstar-sathi" if selected == "roxstar-dost" else "roxstar-dost"


@pytest.mark.asyncio
async def test_concurrent_exactly_once_claim():
    """Verify concurrent voice ingest claims yield exactly 1 winner."""
    state = RoomState("test-dedup-room")
    turn_id = "user_test:1234500"

    tasks = [state.claim_voice_ingest(turn_id) for _ in range(10)]
    results = await asyncio.gather(*tasks)

    winners = [r for r in results if r is True]
    losers = [r for r in results if r is False]

    assert len(winners) == 1, f"Expected exactly 1 winner, got {len(winners)}"
    assert len(losers) == 9, f"Expected 9 losers, got {len(losers)}"


@pytest.mark.asyncio
async def test_route_key_coordination():
    """Verify winner writes route and loser cleanly retrieves it via wait_for_voice_route."""
    state = RoomState("test-route-coord-room")
    turn_id = "user_test:6789000"

    # Winner claims turn successfully
    assert await state.claim_voice_ingest(turn_id) is True
    # Loser attempting same turn is rejected
    assert await state.claim_voice_ingest(turn_id) is False

    # Loser polls for winner's route decision while winner calculates and writes it
    async def loser_workflow():
        return await state.wait_for_voice_route(turn_id, timeout_seconds=2.0)

    loser_task = asyncio.create_task(loser_workflow())
    await asyncio.sleep(0.05)  # Brief simulated delay for winner route computation
    await state.set_voice_route(turn_id, "roxstar-sathi")

    loser_route = await loser_task
    assert loser_route == "roxstar-sathi"


@pytest.mark.asyncio
async def test_speaking_lock_mutual_exclusion():
    """Verify distributed speaking lock mutual exclusion and proper release."""
    state = RoomState("test-lock-room")

    # 1. Dost acquires lock
    assert await state.acquire_speaking_lock("roxstar-dost", ttl=15) is True

    # 2. Sathi cannot acquire lock while Dost holds it
    assert await state.acquire_speaking_lock("roxstar-sathi", ttl=15) is False

    # 3. Sathi cannot release lock owned by Dost
    assert await state.release_speaking_lock("roxstar-sathi") is False

    # 4. Dost releases lock
    assert await state.release_speaking_lock("roxstar-dost") is True

    # 5. Sathi can now acquire lock
    assert await state.acquire_speaking_lock("roxstar-sathi", ttl=15) is True
    assert await state.release_speaking_lock("roxstar-sathi") is True


@pytest.mark.asyncio
async def test_duplicate_response_suppression():
    """Verify unselected bot raises StopResponse and does not generate response."""
    state = RoomState("test-suppression-room")
    dost_agent = DostAgent(state=state)
    sathi_agent = SathiAgent(state=state)

    # User addresses Sathi directly
    turn_ctx = llm.ChatContext()
    user_msg = llm.ChatMessage(role="user", content=["Sathi, please speak to me"])

    # Dost should raise StopResponse
    with pytest.raises(StopResponse):
        await dost_agent.on_user_turn_completed(turn_ctx, user_msg)

    # Sathi should process and acquire speaking lock without error
    await sathi_agent.on_user_turn_completed(turn_ctx, user_msg)
    assert "Sathi, please speak to me" in sathi_agent.instructions
