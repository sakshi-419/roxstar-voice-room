"""
backend/core/bot_router.py
--------------------------
Distributed bot routing engine for Roxstar Voice Room.

Priority:
  1. STOP / INTERRUPT command (ruko, stop, bas, chup, wait, etc.) -> "STOP"
  2. Explicit Direct Addressing (normalized transcript matching for Dost / Sathi)
  3. Conversational Continuity (retain active last_bot for ongoing discussion)
  4. Persona / Context Affinity keywords
  5. Default Fallback -> roxstar-dost
"""

from __future__ import annotations

import re
import unicodedata
from typing import TYPE_CHECKING

from core.logger import get_logger

if TYPE_CHECKING:
    from core.room_state import RoomState

logger = get_logger("roxstar.core.router")

# STT mishearing corrections (longest-match first)
_STT_CORRECTIONS = sorted([
    ("साथी जी",    "sathi"),
    ("साथी",       "sathi"),
    ("दोस्त जी",   "dost"),
    ("दोस्त भाई",  "dost"),
    ("दोस्त",      "dost"),
    ("dost ji",    "dost"),
    ("dost jee",   "dost"),
    ("dostji",     "dost"),
    ("dostjee",    "dost"),
    ("dost bhai",  "dost"),
    ("dosth",      "dost"),
    ("dostu",      "dost"),
    ("saathi ji",  "sathi"),
    ("saathi jee", "sathi"),
    ("saathiji",   "sathi"),
    ("saathijee",  "sathi"),
    ("sathi ji",   "sathi"),
    ("sathi jee",  "sathi"),
    ("sathi bhai", "sathi"),
    ("sathiji",    "sathi"),
    ("saathi",     "sathi"),
    ("shathi",     "sathi"),
    ("swathi",     "sathi"),
    ("sathy",      "sathi"),
    ("sati",       "sathi"),
], key=lambda x: -len(x[0]))


def normalize_transcript(text: str) -> str:
    """Normalize transcript for reliable matching of Hindi, Hinglish and English."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text).lower()
    text = re.sub(r"[^\w\s\u0900-\u097F]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    for wrong, right in _STT_CORRECTIONS:
        if any(ord(c) > 127 for c in wrong):
            text = text.replace(wrong, right)
        else:
            text = re.sub(r"\b" + re.escape(wrong) + r"\b", right, text)
    return text


# STOP / Interruption regex covering Hindi, Hinglish, and English
RE_STOP = re.compile(
    r"\b(?:stop|atop|bas|ruko|ruk\s*jao|ruk|chup|shant|wait|hold\s*on|ek\s*second|ek\s*sec)(?:\s+(?:karo|jao|ho\s*jao|raho|it|dost|sathi|yaar|bhai|ji|please))*\b",
    re.IGNORECASE,
)

_DOST_PATTERNS = re.compile(
    r"(?:(?:hey|hi|hello|namaste|hy|hai|hii|helo|arey|are|arre|bolo)\s+dost"
    r"|^dost\b|\bdost$"
    r"|\bdost\s+(?:suno|bolo|batao|bata|samjhao|samjha|mujhe|muje|ek|kya|kuch|aur|ji|yaar|bhai|na)"
    r"|(?<!\w)dost(?!\w))",
    re.IGNORECASE,
)

_SATHI_PATTERNS = re.compile(
    r"(?:(?:hey|hi|hello|namaste|hy|hai|hii|helo|arey|are|arre|bolo)\s+sathi"
    r"|^sathi\b|\bsathi$"
    r"|\bsathi\s+(?:suno|bolo|batao|bata|samjhao|samjha|mujhe|muje|ek|kya|kuch|aur|ji|na)"
    r"|(?<!\w)sathi(?!\w))",
    re.IGNORECASE,
)

RE_FOLLOW_UP = re.compile(
    r"\b(?:simple|asan|aasan|aur|wahi|phir|fir|aage|example|examples|"
    r"samjhao|samjha|repeat|dubara|dobara|detail|explain|topic|"
    r"uski|uske|iska|iske|batao|bataiye|bata|concept|matlab|meaning|"
    r"isme|usme|phirse|thoda|simply|simplify|elaborate|jara|zara)\b",
    re.IGNORECASE,
)

SATHI_AFFINITY_KEYWORDS = frozenset({
    "sad","feeling","feel","feelings","udas","dukh","heart","poem",
    "poetry","shayari","upset","lonely","stress","tension","calm",
    "sukoon","shanti","emotions","crying","rula","pareshan","dard",
    "pyar","relationship","empathy","soch","zindagi","peace","soul",
    "anxiety","depression","dil","ehsaas","khamosh","tanha",
})

DOST_AFFINITY_KEYWORDS = frozenset({
    "bhai","yaar","code","coding","tech","python","bug","software",
    "cricket","match","game","gaming","joke","masti","party",
    "energy","fun","cool","bro","dude","hacks","computer","score",
    "fast","chill","kick","rockstar","gadget","crypto","ai",
})


class BotRouter:
    @classmethod
    def is_stop_command(cls, transcript: str) -> bool:
        """Check if transcript is an explicit STOP/interruption command.
        Pure stops (e.g. 'ruko', 'stop karo', 'ek second', 'stop dost') return True.
        Direct addresses to a bot (e.g. 'Dost, ek second', 'Dost, wait') return False so the addressed bot responds.
        """
        if not transcript:
            return False
        norm = normalize_transcript(transcript)
        if not RE_STOP.search(norm):
            return False
        dost_m = _DOST_PATTERNS.search(norm)
        sathi_m = _SATHI_PATTERNS.search(norm)
        if dost_m and dost_m.start() == 0 and not re.search(r"\b(?:stop|atop|bas|ruko|chup|shant)\b", norm):
            return False
        if sathi_m and sathi_m.start() == 0 and not re.search(r"\b(?:stop|atop|bas|ruko|chup|shant)\b", norm):
            return False
        return True

    @classmethod
    async def select_bot(cls, state: RoomState, transcript: str) -> str:
        raw_text = transcript.strip()
        norm_text = normalize_transcript(raw_text)
        words = set(re.findall(r"\b\w+\b", norm_text))

        logger.info("ROUTE_INPUT", raw=raw_text[:80])
        logger.info("ROUTE_NORMALIZED", norm=norm_text[:80])

        # Priority 1: STOP / Interruption command
        if cls.is_stop_command(norm_text):
            logger.info("ROUTE_SELECTED", bot="STOP", reason="stop_interrupt_command")
            return "STOP"

        # Priority 2: Direct address (explicit Dost vs Sathi)
        dost_m = _DOST_PATTERNS.search(norm_text)
        sathi_m = _SATHI_PATTERNS.search(norm_text)

        if dost_m and not sathi_m:
            logger.info("ROUTE_SELECTED", bot="roxstar-dost", reason="explicit_address")
            return "roxstar-dost"
        if sathi_m and not dost_m:
            logger.info("ROUTE_SELECTED", bot="roxstar-sathi", reason="explicit_address")
            return "roxstar-sathi"
        if dost_m and sathi_m:
            # If both mentioned, whichever was addressed first takes precedence
            selected = "roxstar-dost" if dost_m.start() <= sathi_m.start() else "roxstar-sathi"
            logger.info("ROUTE_SELECTED", bot=selected, reason="explicit_address_both_first_mention")
            return selected

        # Priority 3: Conversational Continuity (keep active speaker during conversation)
        last_bot = await state.get_last_bot()
        if not last_bot:
            recent = await state.get_context_window(5)
            for turn in reversed(recent):
                if turn.bot_name:
                    last_bot = turn.bot_name
                    break

        if last_bot:
            # During an active discussion with a bot, keep that bot as the current conversational speaker
            # Do NOT alternate bots automatically when a conversation is already active
            logger.info("ROUTE_SELECTED", bot=last_bot, reason="conversation_continuity")
            return last_bot

        # Priority 4: Initial Turn Affinity (No active bot yet in the room)
        sathi_score = sum(1 for w in words if w in SATHI_AFFINITY_KEYWORDS)
        dost_score = sum(1 for w in words if w in DOST_AFFINITY_KEYWORDS)

        if sathi_score > dost_score:
            logger.info("ROUTE_SELECTED", bot="roxstar-sathi", reason="persona_affinity",
                        sathi_score=sathi_score, dost_score=dost_score)
            return "roxstar-sathi"
        if dost_score > sathi_score:
            logger.info("ROUTE_SELECTED", bot="roxstar-dost", reason="persona_affinity",
                        dost_score=dost_score, sathi_score=sathi_score)
            return "roxstar-dost"

        # Priority 5: Default Fallback -> exactly one bot (roxstar-dost)
        logger.info("ROUTE_SELECTED", bot="roxstar-dost", reason="default_fallback")
        return "roxstar-dost"
