"""
backend/providers/stt.py
------------------------
STT provider factory with fallback support.

Primary: Deepgram Nova-3 (language='multi' for seamless Hindi / Hinglish / English recognition)
Fallback: Google Cloud Speech-to-Text (only when GOOGLE_APPLICATION_CREDENTIALS explicitly configured)
"""

from __future__ import annotations

import os

from config import settings
from core.logger import get_logger
from livekit.agents import stt
from livekit.plugins import deepgram

logger = get_logger("roxstar.providers.stt")


def build_stt() -> stt.STT:
    """Build and return configured STT provider with automatic fallback.

    Deepgram Nova-3 is the primary STT. Google Cloud STT is only initialized
    if explicit Google Cloud service account credentials (GOOGLE_APPLICATION_CREDENTIALS)
    are present on the filesystem, avoiding ADC discovery hangs.
    """
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

    # 2. Fallback STT: Google Cloud hi-IN (only if explicit credentials file is set and exists)
    google_creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if google_creds_path and os.path.exists(google_creds_path):
        try:
            from livekit.plugins import google
            g_stt = google.STT(
                credentials_file=google_creds_path,
                languages="hi-IN",
                detect_language=True,
                interim_results=True,
            )
            providers.append(g_stt)
            logger.info("stt_fallback_registered", provider="google", language="hi-IN")
        except Exception as exc:
            logger.debug("google_stt_fallback_unavailable", reason=str(exc))
    else:
        logger.debug(
            "google_stt_fallback_skipped",
            reason="GOOGLE_APPLICATION_CREDENTIALS not configured or file not found",
        )

    if not providers:
        raise RuntimeError("No STT providers could be initialized. Please check DEEPGRAM_API_KEY in backend/.env.")

    if len(providers) > 1:
        return stt.FallbackAdapter(providers)
    return providers[0]
