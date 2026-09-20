"""
backend/tests/test_ai_language_behavior.py
-----------------------------------------
Dedicated unit test suite verifying the 8 AI language behavior requirements:
  TEST 1: Hindi understanding & Devanagari response with English technical terms
  TEST 2: Hinglish understanding & natural Roman Hinglish response
  TEST 3: English understanding & response
  TEST 4: Hinglish follow-up continuity ("Thoda aur simple batao")
  TEST 5: Hindi follow-up continuity ("थोड़ा आसान करके बताओ।")
  TEST 6: English follow-up continuity ("Can you give me a simple example?")
  TEST 7: Bot routing (Dost vs Sathi direct address including Devanagari)
  TEST 8: Zero tolerance for Spanish or foreign language responses
"""

import pytest
from core.language_detector import detect_language, get_language_instruction
from core.bot_router import BotRouter
from core.room_state import RoomState
from agents.sathi_persona import SATHI_SYSTEM_PROMPT
from agents.dost_persona import DOST_SYSTEM_PROMPT
from agents.sathi_agent import SathiAgent
from agents.dost_agent import DostAgent


# =====================================================================
# TEST 1 — Hindi (Devanagari)
# =====================================================================
def test_1_hindi_devanagari():
    """
    User: 'साथी, मशीन लर्निंग में supervised learning क्या होती है?'
    Expected: Hindi detection and Devanagari response instruction with English tech terms.
    """
    user_query = "साथी, मशीन लर्निंग में supervised learning क्या होती है?"
    lang = detect_language(user_query)
    assert lang == "HINDI", f"Expected HINDI, got {lang}"

    instruction = get_language_instruction(user_query)
    assert "Hindi (Devanagari)" in instruction or "Hindi" in instruction
    assert "technical terms" in instruction.lower() or "AI" in instruction
    assert "Spanish" in instruction  # Explicit prohibition


# =====================================================================
# TEST 2 — Hinglish
# =====================================================================
def test_2_hinglish():
    """
    User: 'Sathi, supervised learning kya hoti hai?'
    Expected: Natural Hinglish detection and Roman Hinglish instruction.
    """
    user_query = "Sathi, supervised learning kya hoti hai?"
    lang = detect_language(user_query)
    assert lang == "HINGLISH", f"Expected HINGLISH, got {lang}"

    instruction = get_language_instruction(user_query)
    assert "Hinglish" in instruction
    assert "Roman script" in instruction
    assert "Spanish" in instruction  # Explicit prohibition


# =====================================================================
# TEST 3 — English
# =====================================================================
def test_3_english():
    """
    User: 'Sathi, can you explain cloud computing?'
    Expected: English detection and English instruction.
    """
    user_query = "Sathi, can you explain cloud computing?"
    lang = detect_language(user_query)
    assert lang == "ENGLISH", f"Expected ENGLISH, got {lang}"

    instruction = get_language_instruction(user_query)
    assert "English" in instruction
    assert "Spanish" in instruction  # Explicit prohibition


# =====================================================================
# TEST 4 — Hinglish Follow-up Continuity
# =====================================================================
def test_4_hinglish_follow_up():
    """
    User: 'Sathi, supervised learning kya hoti hai?'
    Then: 'Thoda aur simple batao.'
    Expected: Both turns resolve to Hinglish.
    """
    turn1 = "Sathi, supervised learning kya hoti hai?"
    lang1 = detect_language(turn1)
    assert lang1 == "HINGLISH"

    turn2 = "Thoda aur simple batao."
    lang2 = detect_language(turn2, previous_language=lang1)
    assert lang2 == "HINGLISH", f"Follow-up turn should remain Hinglish, got {lang2}"


# =====================================================================
# TEST 5 — Hindi Follow-up Continuity
# =====================================================================
def test_5_hindi_follow_up():
    """
    User: 'साथी, AI क्या होता है?'
    Then: 'थोड़ा आसान करके बताओ।'
    Expected: Both turns resolve to Hindi.
    """
    turn1 = "साथी, AI क्या होता है?"
    lang1 = detect_language(turn1)
    assert lang1 == "HINDI"

    turn2 = "थोड़ा आसान करके बताओ।"
    lang2 = detect_language(turn2, previous_language=lang1)
    assert lang2 == "HINDI", f"Follow-up turn should remain Hindi, got {lang2}"


# =====================================================================
# TEST 6 — English Follow-up Continuity
# =====================================================================
def test_6_english_follow_up():
    """
    User: 'Dost, explain AI.'
    Then: 'Can you give me a simple example?'
    Expected: Both turns resolve to English.
    """
    turn1 = "Dost, explain AI."
    lang1 = detect_language(turn1)
    assert lang1 == "ENGLISH"

    turn2 = "Can you give me a simple example?"
    lang2 = detect_language(turn2, previous_language=lang1)
    assert lang2 == "ENGLISH", f"Follow-up turn should remain English, got {lang2}"


# =====================================================================
# TEST 7 — Routing
# =====================================================================
@pytest.mark.asyncio
async def test_7_routing():
    """
    User: 'Dost, AI kya hota hai?' -> Only Dost responds.
    User: 'Sathi, AI kya hota hai?' -> Only Sathi responds.
    User: 'साथी, मशीन लर्निंग में supervised learning क्या होती है?' -> Only Sathi responds.
    User: 'दोस्त, AI क्या होता है?' -> Only Dost responds.
    """
    state = RoomState("test-routing-room")

    bot1 = await BotRouter.select_bot(state, "Dost, AI kya hota hai?")
    assert bot1 == "roxstar-dost"

    bot2 = await BotRouter.select_bot(state, "Sathi, AI kya hota hai?")
    assert bot2 == "roxstar-sathi"

    bot3 = await BotRouter.select_bot(state, "साथी, मशीन लर्निंग में supervised learning क्या होती है?")
    assert bot3 == "roxstar-sathi"

    bot4 = await BotRouter.select_bot(state, "दोस्त, AI क्या होता है?")
    assert bot4 == "roxstar-dost"


# =====================================================================
# TEST 8 — Zero Tolerance for Spanish / Foreign Language
# =====================================================================
def test_8_zero_tolerance_foreign_language():
    """
    System prompts and instructions must explicitly prohibit Spanish, French,
    German, and any other foreign language, specifically mentioning
    '¿Cómo puedo ayudarte?'.
    """
    # Check Sathi Persona
    assert "Spanish" in SATHI_SYSTEM_PROMPT
    assert "¿Cómo puedo ayudarte?" in SATHI_SYSTEM_PROMPT
    assert "ABSOLUTE LANGUAGE RESTRICTION" in SATHI_SYSTEM_PROMPT

    # Check Dost Persona
    assert "Spanish" in DOST_SYSTEM_PROMPT
    assert "¿Cómo puedo ayudarte?" in DOST_SYSTEM_PROMPT
    assert "ABSOLUTE LANGUAGE RESTRICTION" in DOST_SYSTEM_PROMPT

    # Verify agent format_instructions does not leave raw unpopulated braces
    state = RoomState("test-zero-foreign")
    sathi = SathiAgent(state=state)
    dost = DostAgent(state=state)

    sathi_prompt = sathi.format_instructions()
    dost_prompt = dost.format_instructions()

    assert "{detected_language_instruction}" not in sathi_prompt
    assert "{detected_language_instruction}" not in dost_prompt
    assert "{room_context}" not in sathi_prompt
    assert "{room_context}" not in dost_prompt
    assert "{speaker_profile}" not in sathi_prompt
    assert "{speaker_profile}" not in dost_prompt

    # Verify that instructions for Hindi, Hinglish, and English all forbid Spanish
    for sample in ["Hello", "साथी, AI क्या है?", "Dost, API kya hoti hai?"]:
        instr = get_language_instruction(sample)
        assert "Spanish" in instr
