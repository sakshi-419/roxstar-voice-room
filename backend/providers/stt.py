"""
backend/providers/stt.py
------------------------
STT provider factory with fallback support.

Primary: Deepgram Nova-3 (language='multi' for seamless Hindi / Hinglish / English recognition)
Fallback: Google Cloud Speech-to-Text (language='hi-IN')
"""

from __future__ import annotations

from config import settings
from core.logger import get_logger
from livekit.agents import stt
from livekit.plugins import deepgram, google

logger = get_logger("roxstar.providers.stt")


def build_stt() -> stt.STT:
    """Build and return configured STT provider with automatic fallback."""
    providers: list[stt.STT] = []

    # 1. Primary STT: Deepgram Nova-3 multilingual
    if settings.deepgram_api_key:
        try:
            dg_stt = deepgram.STT(
                api_key=settings.deepgram_api_key,
                model="nova-3",
                language="multi",
                interim_results=True,
                punctuate=True,
            )
            providers.append(dg_stt)
            logger.info("stt_provider_registered", provider="deepgram", model="nova-3", language="multi")
        except Exception as exc:
            logger.error("deepgram_stt_init_failed", error=str(exc))

    # 2. Fallback STT: Google Cloud hi-IN
    try:
        g_stt = google.STT(
            languages="hi-IN",
            detect_language=True,
            interim_results=True,
        )
        providers.append(g_stt)
        logger.info("stt_fallback_registered", provider="google", language="hi-IN")
    except Exception as exc:
        logger.debug("google_stt_fallback_unavailable", reason=str(exc))

    if not providers:
        raise RuntimeError("No STT providers could be initialized. Please check DEEPGRAM_API_KEY in backend/.env.")

    if len(providers) > 1:
        return stt.FallbackAdapter(providers)
    return providers[0]
