"""
backend/providers/llm.py
------------------------
LLM provider factory with fallback support.

Primary: Google Gemini 3.6 Flash
Fallback: Google Gemini 3.5 Flash
"""

from __future__ import annotations

from config import settings
from core.logger import get_logger
from livekit.agents import llm
from livekit.plugins import google

logger = get_logger("roxstar.providers.llm")


def build_llm(timeout: float = 15.0) -> llm.LLM:
    """Build and return configured LLM provider with automatic fallback.

    Configures a 15-second timeout (minimum required by Gemini is 10s) to prevent
    'deadline is too short' errors.
    """
    providers: list[llm.LLM] = []

    if not settings.google_api_key:
        raise RuntimeError("GOOGLE_API_KEY is not configured in backend/.env.")

    primary_model = settings.llm_model or "gemini-3.6-flash"
    fallback_model = "gemini-3.5-flash" if primary_model != "gemini-3.5-flash" else "gemini-3-flash-preview"

    # 1. Primary Gemini LLM
    try:
        primary_llm = google.LLM(
            model=primary_model,
            api_key=settings.google_api_key,
            temperature=0.7,
        )
        providers.append(primary_llm)
        logger.info("llm_provider_registered", provider="google", model=primary_model)
    except Exception as exc:
        logger.error("primary_llm_init_failed", model=primary_model, error=str(exc))

    # 2. Fallback Gemini LLM (distinct from primary)
    if fallback_model != primary_model:
        try:
            fallback_llm = google.LLM(
                model=fallback_model,
                api_key=settings.google_api_key,
                temperature=0.7,
            )
            providers.append(fallback_llm)
            logger.info("llm_fallback_registered", provider="google", model=fallback_model)
        except Exception as exc:
            logger.debug("fallback_llm_init_failed", model=fallback_model, error=str(exc))

    if not providers:
        raise RuntimeError("No LLM providers could be initialized.")

    if len(providers) > 1:
        return llm.FallbackAdapter(
            providers,
            attempt_timeout=timeout,
            max_retry_per_llm=2,
            retry_interval=1.0,
        )
    return providers[0]
