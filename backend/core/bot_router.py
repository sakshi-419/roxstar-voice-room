"""
backend/core/bot_router.py
--------------------------
Distributed bot routing engine for Roxstar Voice Room (Phase 5+).

Priority:
  1. Explicit Direct Addressing (normalized transcript matching)
  2. Multi-turn Follow-up Continuation (last_bot preserved)
  3. Persona / Context Affinity keywords
  4. Turn Alternation (Round-Robin)
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
    ("dost ji",    "dost"),
    ("dost jee",   "dost"),
    ("dostji",     "dost"),
    ("dostjee",    "dost"),
    ("dosth",      "dost"),
    ("dostu",      "dost"),
    ("saathi ji",  "sathi"),
    ("saathi jee", "sathi"),
    ("saathiji",   "sathi"),
    ("saathijee",  "sathi"),
    ("sathi ji",   "sathi"),
    ("sathi jee",  "sathi"),
    ("sathiji",    "sathi"),
    ("saathi",     "sathi"),
    ("shathi",     "sathi"),
    ("swathi",     "sathi"),
    ("sathy",      "sathi"),
    ("sati",       "sathi"),
], key=lambda x: -len(x[0]))


def normalize_transcript(text):
    text = unicodedata.normalize("NFKC", text).lower()
    text = re.sub(r"[^\w\s\u0900-\u097F]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    for wrong, right in _STT_CORRECTIONS:
        text = re.sub(r"\b" + re.escape(wrong) + r"\b", right, text)
    return text


_DOST_PATTERNS = re.compile(
    r"(?:(?:hey|hi|hello|namaste|hy|hai|hii|helo|arey|are|arre|bolo)\s+dost"
    r"|^dost\b|\bdost$"
    r"|\bdost\s+(?:suno|bolo|batao|bata|samjhao|samjha|mujhe|muje|ek|kya|kuch|aur|ji|yaar|na)"
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
    async def select_bot(cls, state, transcript):
        raw_text = transcript.strip()
        norm_text = normalize_transcript(raw_text)
        words = set(re.findall(r"\b\w+\b", norm_text))

        logger.info("ROUTE_INPUT", raw=raw_text[:80])
        logger.info("ROUTE_NORMALIZED", norm=norm_text[:80])

        dost_m = _DOST_PATTERNS.search(norm_text)
        sathi_m = _SATHI_PATTERNS.search(norm_text)

        if dost_m and not sathi_m:
            logger.info("ROUTE_SELECTED", bot="roxstar-dost", reason="explicit_address")
            return "roxstar-dost"
        if sathi_m and not dost_m:
            logger.info("ROUTE_SELECTED", bot="roxstar-sathi", reason="explicit_address")
            return "roxstar-sathi"
        if dost_m and sathi_m:
            selected = "roxstar-dost" if dost_m.start() <= sathi_m.start() else "roxstar-sathi"
            logger.info("ROUTE_SELECTED", bot=selected, reason="explicit_address_both_first_mention")
            return selected

        last_bot = await state.get_last_bot()
        if not last_bot:
            recent = await state.get_context_window(5)
            for turn in reversed(recent):
                if turn.bot_name:
                    last_bot = turn.bot_name
                    break

        if last_bot and RE_FOLLOW_UP.search(norm_text):
            logger.info("ROUTE_SELECTED", bot=last_bot, reason="follow_up_last_bot")
            return last_bot

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

        if last_bot == "roxstar-dost":
            logger.info("ROUTE_SELECTED", bot="roxstar-sathi", reason="alternation")
            return "roxstar-sathi"
        if last_bot == "roxstar-sathi":
            logger.info("ROUTE_SELECTED", bot="roxstar-dost", reason="alternation")
            return "roxstar-dost"

        logger.info("ROUTE_SELECTED", bot="roxstar-dost", reason="default_fallback")
        return "roxstar-dost"
