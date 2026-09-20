"""
backend/providers/tts.py
------------------------
TTS provider factory with robust fallback support.

Supported providers:
  - Deepgram Aura (Ultra-fast, high quality, robust, authenticated):
      - Dost (Male): aura-2-orion-en
      - Sathi (Female): aura-2-luna-en
  - ElevenLabs (if configured and working):
      - Dost: hpp4J3VqNfWAUOO0d1Us
      - Sathi: EXAVITQu4vr4xnSDxMaL
  - Google Cloud TTS (Neural2 Hindi voices):
      - Dost: hi-IN-Neural2-B
      - Sathi: hi-IN-Neural2-A
"""

from __future__ import annotations

import os

from config import settings
from core.logger import get_logger
from livekit.agents import tts
from livekit.plugins import deepgram

try:
    from livekit.plugins import elevenlabs
except ImportError:
    elevenlabs = None

logger = get_logger("roxstar.providers.tts")

DEFAULT_DOST_VOICE = "IKne3meq5aSn9XLyUdCD"
DEFAULT_SATHI_VOICE = "EXAVITQu4vr4xnSDxMaL"

# Deepgram Aura voices (low latency, clear Indian Hindi/Hinglish and English pronunciation)
DG_DOST_VOICE = "aura-2-orion-en"   # Male, warm, conversational
DG_SATHI_VOICE = "aura-2-luna-en"   # Female, warm, friendly


def build_tts(bot_name: str = "dost") -> tts.TTS:
    """Build and return configured TTS provider with automatic fallback."""
    providers: list[tts.TTS] = []
    is_dost = "dost" in bot_name.lower()
    pref_provider = (settings.tts_provider or "deepgram").lower()

    # 1. Deepgram TTS (fast, reliable, fully authenticated with DEEPGRAM_API_KEY)
    dg_voice = DG_DOST_VOICE if is_dost else DG_SATHI_VOICE
    dg_tts = None
    if settings.deepgram_api_key:
        try:
            dg_tts = deepgram.TTS(
                api_key=settings.deepgram_api_key,
                model=dg_voice,
            )
        except Exception as exc:
            logger.error("deepgram_tts_init_failed", error=str(exc))

    # 2. ElevenLabs TTS (if key exists)
    el_tts = None
    if settings.elevenlabs_api_key and elevenlabs:
        voice_id = (settings.dost_voice_id if is_dost else settings.sathi_voice_id) or (
            DEFAULT_DOST_VOICE if is_dost else DEFAULT_SATHI_VOICE
        )
        try:
            el_tts = elevenlabs.TTS(
                api_key=settings.elevenlabs_api_key,
                voice_id=voice_id,
                model="eleven_multilingual_v2",
                language="hi",
                voice_settings=elevenlabs.VoiceSettings(
                    stability=0.65,
                    similarity_boost=0.82,
                    style=0.35,
                    speed=0.92,
                    use_speaker_boost=True,
                ),
                apply_text_normalization="auto",
            )
        except Exception as exc:
            logger.error("elevenlabs_tts_init_failed", error=str(exc))

    # If Deepgram is requested or ElevenLabs is not available, use Deepgram directly
    if pref_provider == "deepgram" or not el_tts:
        if dg_tts:
            providers.append(dg_tts)
            logger.info("tts_provider_registered", provider="deepgram", bot=bot_name, voice=dg_voice)
        elif el_tts:
            providers.append(el_tts)
            logger.info("tts_provider_registered", provider="elevenlabs", bot=bot_name)
    else:
        if el_tts:
            providers.append(el_tts)
            logger.info("tts_provider_registered", provider="elevenlabs", bot=bot_name)
        if dg_tts:
            providers.append(dg_tts)
            logger.info("tts_fallback_registered", provider="deepgram", bot=bot_name, voice=dg_voice)

    # 3. Fallback: Google Cloud TTS hi-IN Neural2 (if explicit credentials file exists)
    google_creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if google_creds_path and os.path.exists(google_creds_path):
        google_voice = "hi-IN-Neural2-B" if is_dost else "hi-IN-Neural2-A"
        try:
            from livekit.plugins import google
            g_tts = google.TTS(
                credentials_file=google_creds_path,
                language="hi-IN",
                voice_name=google_voice,
            )
            providers.append(g_tts)
            logger.info("tts_fallback_registered", provider="google", voice=google_voice)
        except Exception as exc:
            logger.debug("google_tts_fallback_unavailable", reason=str(exc))

    if not providers:
        raise RuntimeError("No TTS providers could be initialized. Please check DEEPGRAM_API_KEY in backend/.env.")

    if len(providers) > 1:
        return tts.FallbackAdapter(providers)
    return providers[0]
