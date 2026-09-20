"""
backend/core/language_detector.py
-----------------------------------
Lightweight language detector for Roxstar AI Voice Room.

Detects whether a user''s text is Hindi (Devanagari), Hinglish (Roman-script Hindi),
or English, and returns an explicit language response instruction for the LLM.

This runs synchronously and must be fast (no network calls).
"""

from __future__ import annotations

import re

# --- Devanagari Unicode range ---
_RE_DEVANAGARI = re.compile(r"[\u0900-\u097F]")

# Common Hinglish Hindi words written in Roman script (high-signal markers)
# IMPORTANT: "sathi" and "dost" are excluded — they appear equally in English sentences
# addressed to the bots and should not bias language detection.
_HINGLISH_MARKERS = frozenset({
    # Verbs and helpers (high signal)
    "hai", "hain", "hoga", "tha", "the", "thi", "hoon",
    "karna", "karte", "karein", "karta", "karti", "kiya",
    "batao", "samjhao", "bolo", "suno", "dekho", "ruko",
    # Pronouns / common words (high signal)
    "mujhe", "mera", "meri", "mere", "tumhe", "tumhara", "aap", "apna",
    "yeh", "woh", "kaise", "kyun", "kab", "kahan", "kaun",
    "main", "hum", "tum", "nahi", "nahin",
    "agar", "toh", "lekin", "matlab", "waise", "seedha",
    # Expressions (high signal)
    "arrey", "achha", "theek", "bilkul", "haan",
    "samajh", "samjhao", "thoda", "zyada", "bahut", "acha",
    "bhai", "yaar",
    # Grammar particles (very high signal for Hinglish)
    "kya", "hota", "hoti", "mein", "wala", "wali", "pe", "ke", "ko",
    "kuch", "sab", "sirf", "pehle", "baad", "jaise", "aur",
    "se", "mein", "ab", "phir",
})

# Words that are addressed to the bot — strip these from language analysis
_BOT_NAMES = frozenset({"sathi", "saathi", "dost", "roxstar"})

# Minimum fraction of words (excluding bot names) that must be Hinglish markers
_HINGLISH_THRESHOLD = 0.22  # 22% of non-bot words

# Phrases that explicitly request a specific language response
_RE_FORCE_ENGLISH = re.compile(
    r"\b(in\s+english|english\s+mein|english\s+me|explain\s+in\s+english|"
    r"answer\s+in\s+english|respond\s+in\s+english|english\s+please|please\s+english|"
    r"now\s+explain\s+in\s+english|explain\s+it\s+in\s+english)\b",
    re.IGNORECASE,
)
_RE_FORCE_HINDI = re.compile(
    r"\b(hindi\s+mein|hindi\s+me|ab\s+hindi|hindi\s+mein\s+batao|"
    r"hindi\s+mein\s+samjhao|pure\s+hindi|hindi\s+mein\s+bolo)\b",
    re.IGNORECASE,
)
_RE_FORCE_HINGLISH = re.compile(
    r"\b(hinglish\s+mein|hinglish\s+me|mix\s+hindi|thoda\s+hindi)\b",
    re.IGNORECASE,
)


def detect_language(text: str) -> str:
    """
    Detect whether the text is HINDI, HINGLISH, or ENGLISH.

    Returns one of: "HINDI", "HINGLISH", "ENGLISH"
    """
    if not text or not text.strip():
        return "HINGLISH"

    # 1. Explicit override — user forces a language
    if _RE_FORCE_ENGLISH.search(text):
        return "ENGLISH"
    if _RE_FORCE_HINDI.search(text):
        return "HINDI"
    if _RE_FORCE_HINGLISH.search(text):
        return "HINGLISH"

    # 2. Devanagari characters → pure Hindi script
    devanagari_chars = len(_RE_DEVANAGARI.findall(text))
    total_chars = len(text.strip())
    if total_chars > 0 and devanagari_chars / total_chars > 0.15:
        return "HINDI"

    # 3. Extract words, removing bot names from consideration
    all_words = re.findall(r"\b[a-zA-Z]+\b", text.lower())
    # Filter out bot names — they don''t contribute to language detection
    words = [w for w in all_words if w not in _BOT_NAMES]

    if not words:
        # Only bot names or punctuation — check for non-Latin characters
        if _RE_DEVANAGARI.search(text):
            return "HINDI"
        return "HINGLISH"  # Default for bot-name-only messages

    marker_count = sum(1 for w in words if w in _HINGLISH_MARKERS)
    ratio = marker_count / len(words)

    if ratio >= _HINGLISH_THRESHOLD:
        return "HINGLISH"

    # 4. Default — English
    return "ENGLISH"


def get_language_instruction(text: str) -> str:
    """
    Detect language from user text and return an explicit LLM response instruction.
    This instruction is injected into the system prompt per turn.
    """
    lang = detect_language(text)

    if lang == "HINDI":
        return (
            "LANGUAGE RULE FOR THIS TURN: The user spoke in Hindi (Devanagari). "
            "Respond in natural conversational Hindi. You may keep common technical "
            "terms (AI, model, data, training, Python, SQL, API, algorithm, "
            "Machine Learning, Deep Learning) in English as Indians commonly use them. "
            "Do NOT respond in English. Do NOT use overly formal or bookish Hindi. "
            "Use natural conversational Hindi as spoken in everyday life."
        )
    elif lang == "HINGLISH":
        return (
            "LANGUAGE RULE FOR THIS TURN: The user spoke in Hinglish (Roman-script Hindi-English mix). "
            "Respond in natural Indian Hinglish. Mix conversational Hindi words with English naturally. "
            "For example: 'Machine Learning mein model data se patterns learn karta hai.' "
            "Keep technical terms in English (AI, model, training, data, Python, SQL, API, algorithm). "
            "Do NOT respond in pure formal English. Do NOT use Devanagari script. "
            "Sound like a friendly Indian conversationalist."
        )
    else:
        return (
            "LANGUAGE RULE FOR THIS TURN: The user spoke in English. "
            "Respond clearly in English. You may naturally include warm Indian expressions "
            "such as 'bilkul', 'achha', 'yaar' if it feels natural, but keep the "
            "response primarily in English."
        )
