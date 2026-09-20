"""
backend/core/language_detector.py
-----------------------------------
Lightweight, robust language detector for Roxstar AI Voice Room.

Detects whether a user's text is Hindi (Devanagari), Hinglish (Roman-script Hindi),
or English, with conversational follow-up continuity.
Strictly prevents Spanish or any foreign language output.
"""

from __future__ import annotations

import re

# --- Devanagari Unicode range ---
_RE_DEVANAGARI = re.compile(r"[\u0900-\u097F]")

# Common Hinglish Hindi words written in Roman script (high-signal markers)
# Exclude bot names ('sathi', 'dost') so addressing does not bias detection
_HINGLISH_MARKERS = frozenset({
    # Verbs and helpers (high signal)
    "hai", "hain", "hoga", "hogi", "hoge", "tha", "the", "thi", "hoon", "hun",
    "karna", "karte", "karein", "karta", "karti", "kiya", "kariye", "kar", "karo",
    "batao", "bataiye", "samjhao", "samjhaiye", "bolo", "suno", "dekho", "ruko",
    # Pronouns / common words (high signal)
    "mujhe", "mera", "meri", "mere", "tumhe", "tumhara", "tumhari", "aap", "apna", "apni", "apne",
    "yeh", "woh", "kaise", "kaisa", "kaisi", "kyun", "kyu", "kab", "kahan", "kaun", "kisko",
    "main", "hum", "tum", "nahi", "nahin", "na",
    "agar", "toh", "lekin", "matlab", "waise", "seedha", "ya",
    # Expressions (high signal)
    "arrey", "arey", "achha", "accha", "theek", "bilkul", "haan", "han",
    "samajh", "thoda", "zyada", "bahut", "bhai", "yaar",
    # Grammar particles (very high signal for Hinglish)
    "kya", "hota", "hoti", "hote", "mein", "wala", "wali", "wale", "pe", "par", "ke", "ko",
    "kuch", "sab", "sirf", "pehle", "baad", "jaise", "aur",
    "se", "ab", "phir", "fir",
})

# Bot names and honorifics that shouldn't skew detection
_BOT_NAMES = frozenset({"sathi", "saathi", "dost", "roxstar", "ji", "bhai", "yaar"})

# Generic short follow-ups that should inherit the previous language
_GENERIC_SHORT_FOLLOW_UPS = frozenset({
    "why", "why so", "how", "how so", "what about that", "what does that mean",
    "explain that again", "explain again", "can you explain", "tell me more",
    "one more example", "give an example", "give me an example",
    "can you give me a simple example", "can you give me an example",
    "give example", "more example", "more examples", "elaborate",
})

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


def detect_language(text: str, previous_language: str | None = None) -> str:
    """
    Detect whether the user text is HINDI, HINGLISH, or ENGLISH.
    Inherits previous_language for short conversational follow-ups.
    """
    if not text or not text.strip():
        return previous_language or "HINGLISH"

    cleaned = text.strip()

    # 1. Explicit override phrases
    if _RE_FORCE_ENGLISH.search(cleaned):
        return "ENGLISH"
    if _RE_FORCE_HINDI.search(cleaned):
        return "HINDI"
    if _RE_FORCE_HINGLISH.search(cleaned):
        return "HINGLISH"

    # 2. Devanagari script detection
    devanagari_chars = len(_RE_DEVANAGARI.findall(cleaned))
    if devanagari_chars >= 2 or (len(cleaned) > 0 and devanagari_chars / len(cleaned) > 0.1):
        return "HINDI"

    # 3. Word analysis in Latin script
    all_words = re.findall(r"\b[a-zA-Z]+\b", cleaned.lower())
    non_bot_words = [w for w in all_words if w not in _BOT_NAMES]

    if not non_bot_words:
        return previous_language or "HINGLISH"

    # 4. Check for short follow-up inheritance
    norm_phrase = " ".join(non_bot_words)
    has_hinglish = any(w in _HINGLISH_MARKERS for w in non_bot_words)

    if previous_language and not has_hinglish:
        if norm_phrase in _GENERIC_SHORT_FOLLOW_UPS:
            return previous_language

    # 5. Hinglish markers
    marker_count = sum(1 for w in non_bot_words if w in _HINGLISH_MARKERS)
    ratio = marker_count / len(non_bot_words)

    # In short queries (<= 5 words), even 1 Hinglish marker ('thoda', 'kya', 'batao', 'aur', 'hai') means Hinglish
    if len(non_bot_words) <= 5 and marker_count >= 1:
        return "HINGLISH"

    if ratio >= 0.18:
        return "HINGLISH"

    # 6. Default to English
    return "ENGLISH"


def get_language_instruction(text: str, previous_language: str | None = None) -> str:
    """
    Detect language from user text and return explicit LLM response instructions.
    Strictly forbids Spanish, French, German, or any foreign language.
    """
    lang = detect_language(text, previous_language=previous_language)

    if lang == "HINDI":
        return (
            "LANGUAGE RULE FOR THIS TURN: The user spoke in Hindi (Devanagari). "
            "Respond in natural, warm conversational Hindi using Devanagari script. "
            "Keep common technical terms (AI, machine learning, supervised learning, "
            "model, dataset, API, cloud computing, database, Python, etc.) naturally "
            "in English as spoken in India. "
            "Under NO circumstances respond in Spanish, French, German, or any foreign language. "
            "Do NOT use bookish or archaic Hindi. Keep your response concise (1 to 3 short sentences)."
        )
    elif lang == "HINGLISH":
        return (
            "LANGUAGE RULE FOR THIS TURN: The user spoke in Hinglish (Roman-script Hindi-English mix). "
            "Respond in natural Indian Hinglish using Roman script. Mix conversational Hindi words "
            "with English naturally (e.g. 'Supervised learning mein model labeled data se train hota hai...'). "
            "Keep technical terms in English (AI, machine learning, supervised learning, model, "
            "dataset, API, cloud computing, database, Python, etc.). "
            "Under NO circumstances respond in Spanish, French, German, or any foreign language. "
            "Do NOT use Devanagari script. Keep your response concise (1 to 3 short sentences)."
        )
    else:
        return (
            "LANGUAGE RULE FOR THIS TURN: The user spoke in English. "
            "Respond clearly, warmly, and naturally in English. "
            "Under NO circumstances respond in Spanish, French, German, or any foreign language. "
            "Keep your response concise (1 to 3 short sentences)."
        )
