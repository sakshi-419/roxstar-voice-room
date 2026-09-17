"""
backend/config.py
-----------------
Centralised application configuration loaded from environment variables.
Uses pydantic-settings so every value is typed and validated at startup.
Missing required values raise a clear ValidationError — no secrets are
hard-coded here.
"""

from __future__ import annotations

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All configuration for the Roxstar AI Voice Room backend.

    Values are read from environment variables (case-insensitive) and from
    a .env file in the backend/ directory if present.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── LiveKit Cloud ──────────────────────────────────────────────────────────
    livekit_url: str = ""
    livekit_api_key: str = ""
    livekit_api_secret: str = ""

    # ── Redis ─────────────────────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"
    redis_password: str = ""
    redis_tls: bool = False

    # ── STT ───────────────────────────────────────────────────────────────────
    stt_provider: str = "deepgram"          # deepgram | google_stt
    deepgram_api_key: str = ""

    # ── LLM ───────────────────────────────────────────────────────────────────
    llm_provider: str = "google"            # google | openai
    llm_model: str = "gemini-2.0-flash"
    google_api_key: str = ""
    openai_api_key: str = ""

    # ── TTS ───────────────────────────────────────────────────────────────────
    tts_provider: str = "elevenlabs"        # elevenlabs | google_tts
    elevenlabs_api_key: str = ""
    dost_voice_id: str = ""                 # ElevenLabs male Hindi voice ID
    sathi_voice_id: str = ""               # ElevenLabs female Hindi voice ID

    # ── Token Server ──────────────────────────────────────────────────────────
    token_server_port: int = 8000
    token_ttl_seconds: int = 3600

    # ── Logging ───────────────────────────────────────────────────────────────
    log_level: str = "INFO"

    # ── Validators ────────────────────────────────────────────────────────────
    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR"}
        upper = v.upper()
        if upper not in allowed:
            raise ValueError(f"log_level must be one of {allowed}, got {v!r}")
        return upper

    @field_validator("stt_provider")
    @classmethod
    def validate_stt_provider(cls, v: str) -> str:
        allowed = {"deepgram", "google_stt"}
        if v not in allowed:
            raise ValueError(f"stt_provider must be one of {allowed}, got {v!r}")
        return v

    @field_validator("llm_provider")
    @classmethod
    def validate_llm_provider(cls, v: str) -> str:
        allowed = {"google", "openai"}
        if v not in allowed:
            raise ValueError(f"llm_provider must be one of {allowed}, got {v!r}")
        return v

    @field_validator("tts_provider")
    @classmethod
    def validate_tts_provider(cls, v: str) -> str:
        allowed = {"elevenlabs", "google_tts"}
        if v not in allowed:
            raise ValueError(f"tts_provider must be one of {allowed}, got {v!r}")
        return v


# Module-level singleton — import this everywhere instead of creating new instances.
# Example:  from config import settings
settings = Settings()
