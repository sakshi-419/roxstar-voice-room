"""
backend/providers/llm.py
------------------------
LLM provider factory with automatic fallback support.

Supported providers:
  - "groq"   : Ultra-low latency voice LLM (Primary: qwen/qwen3.8-27b, Fallback: allam-2-7b)
  - "google" : Google Gemini (Primary: gemini-3.6-flash, Fallback: gemini-3.5-flash)
  - "openai" : OpenAI / Compatible endpoint
"""

from __future__ import annotations

from config import settings
from core.logger import get_logger
from livekit.agents import llm
try:
    from livekit.plugins import groq
except ImportError:
    groq = None

try:
    from livekit.plugins import google
except ImportError:
    google = None

try:
    from livekit.plugins import openai
except ImportError:
    openai = None


logger = get_logger("roxstar.providers.llm")


def build_llm(timeout: float = 15.0) -> llm.LLM:
    """Build and return configured LLM provider with automatic fallback.

    Supports Groq and Google Gemini based on settings.llm_provider.
    Configures a 15-second timeout and retry logic via FallbackAdapter.
    """
    providers: list[llm.LLM] = []
    active_provider = settings.llm_provider.lower()

    # 1. Groq Provider (Voice-optimized LLaMA 3.3 70B + LLaMA 3.1 8B fallback)
    if active_provider == "groq":

        if not settings.groq_api_key:
            raise RuntimeError("GROQ_API_KEY is not configured in backend/.env.")

        primary_model = settings.llm_model or "groq/compound-mini"
        fallback_model = "allam-2-7b" if primary_model != "allam-2-7b" else "groq/compound-mini"

        # Primary Groq LLM (bounded tokens for ultra-fast voice responses and OTPM safety)
        try:
            primary_llm = groq.LLM(
                model=primary_model,
                api_key=settings.groq_api_key,
                temperature=0.7,
                max_completion_tokens=150,
            )
            providers.append(primary_llm)
            logger.info("llm_provider_registered", provider="groq", model=primary_model)
        except Exception as exc:
            logger.error("primary_llm_init_failed", provider="groq", model=primary_model, error=str(exc))

        # Fallback Groq LLM
        if fallback_model != primary_model:
            try:
                fallback_llm = groq.LLM(
                    model=fallback_model,
                    api_key=settings.groq_api_key,
                    temperature=0.7,
                    max_completion_tokens=150,
                )
                providers.append(fallback_llm)
                logger.info("llm_fallback_registered", provider="groq", model=fallback_model)
            except Exception as exc:
                logger.debug("fallback_llm_init_failed", provider="groq", model=fallback_model, error=str(exc))

    # 2. Google Gemini Provider
    elif active_provider == "google":

        if not settings.google_api_key:
            raise RuntimeError("GOOGLE_API_KEY is not configured in backend/.env.")

        primary_model = settings.llm_model or "gemini-3.6-flash"
        fallback_model = "gemini-3.5-flash" if primary_model != "gemini-3.5-flash" else "gemini-3-flash-preview"

        try:
            primary_llm = google.LLM(
                model=primary_model,
                api_key=settings.google_api_key,
                temperature=0.7,
            )
            providers.append(primary_llm)
            logger.info("llm_provider_registered", provider="google", model=primary_model)
        except Exception as exc:
            logger.error("primary_llm_init_failed", provider="google", model=primary_model, error=str(exc))

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
                logger.debug("fallback_llm_init_failed", provider="google", model=fallback_model, error=str(exc))

    # 3. OpenAI / OpenAI-compatible Provider
    elif active_provider == "openai":

        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured in backend/.env.")

        primary_model = settings.llm_model or "gpt-4o-mini"
        try:
            primary_llm = openai.LLM(
                model=primary_model,
                api_key=settings.openai_api_key,
                temperature=0.7,
            )
            providers.append(primary_llm)
            logger.info("llm_provider_registered", provider="openai", model=primary_model)
        except Exception as exc:
            logger.error("primary_llm_init_failed", provider="openai", model=primary_model, error=str(exc))

    else:
        raise ValueError(f"Unsupported LLM provider: {active_provider}")

    if not providers:
        raise RuntimeError(f"No LLM providers could be initialized for provider '{active_provider}'.")

    if len(providers) > 1:
        return llm.FallbackAdapter(
            providers,
            attempt_timeout=30.0,
            max_retry_per_llm=3,
            retry_interval=3.0,
        )
    return providers[0]
