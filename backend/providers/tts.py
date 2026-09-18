"""
backend/providers/tts.py
------------------------
TTS provider factory with fallback support.

Primary: ElevenLabs (eleven_turbo_v2_5) with natural Hindi conversational voice
Fallback: Google Cloud TTS (Neural2 Hindi voices)
"""

from __future__ import annotations

from config import settings
from core.logger import get_logger
from livekit.agents import tts
from livekit.plugins import elevenlabs, google

logger = get_logger("roxstar.providers.tts")

# Default ElevenLabs Hindi voice IDs
# Dost: Warm male Hindi voice (e.g., standard male persona)
# Sathi: Warm female Hindi voice
DEFAULT_DOST_VOICE = "hpp4J3VqNfWAUOO0d1Us"
DEFAULT_SATHI_VOICE = "21m00Tcm4TlvDq8ikWAM"


def build_tts(bot_name: str = "dost") -> tts.TTS:
    """Build and return configured TTS provider with automatic fallback."""
    providers: list[tts.TTS] = []
    is_dost = "dost" in bot_name.lower()

    # 1. Primary TTS: ElevenLabs
    if settings.elevenlabs_api_key:
        voice_id = (settings.dost_voice_id if is_dost else settings.sathi_voice_id) or (
            DEFAULT_DOST_VOICE if is_dost else DEFAULT_SATHI_VOICE
        )
        try:
            el_tts = elevenlabs.TTS(
                api_key=settings.elevenlabs_api_key,
                voice_id=voice_id,
                model="eleven_turbo_v2_5",
            )
            providers.append(el_tts)
            logger.info(
                "tts_provider_registered",
                provider="elevenlabs",
                bot=bot_name,
                voice_id=voice_id[:8] + "***",
            )
        except Exception as exc:
            logger.error("elevenlabs_tts_init_failed", error=str(exc))

    # 2. Fallback TTS: Google Cloud TTS hi-IN Neural2
    google_voice = "hi-IN-Neural2-B" if is_dost else "hi-IN-Neural2-A"
    try:
        g_tts = google.TTS(
            language="hi-IN",
            voice_name=google_voice,
        )
        providers.append(g_tts)
        logger.info("tts_fallback_registered", provider="google", voice=google_voice)
    except Exception as exc:
        logger.debug("google_tts_fallback_unavailable", reason=str(exc))

    if not providers:
        raise RuntimeError("No TTS providers could be initialized. Please check ELEVENLABS_API_KEY in backend/.env.")

    if len(providers) > 1:
        return tts.FallbackAdapter(providers)
    return providers[0]
