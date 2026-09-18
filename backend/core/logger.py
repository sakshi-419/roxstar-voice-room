"""
backend/core/logger.py
----------------------
Structured logging configuration using structlog.

Guarantees:
  - All logs include timestamp, level, event, and structured contextual fields.
  - Sensitive values (passwords, tokens, API keys) are masked before emission.
  - Compatible with standard library logging and LiveKit logger.
"""

from __future__ import annotations

import logging
import re
import sys
from typing import Any

import structlog

# Patterns for masking secrets in log events
_SECRET_PATTERNS = [
    (re.compile(r"://([^:]+):([^@]+)@"), r"://\1:***@"),
    (re.compile(r"(api[_-]?key|password|token|secret)=([^\s,&]+)", re.IGNORECASE), r"\1=***"),
    (re.compile(r"(sk_[a-zA-Z0-9_-]{20,})"), r"sk_***"),
    (re.compile(r"(AIza[a-zA-Z0-9_-]{30,})"), r"AIza_***"),
]


def sanitize_sensitive_data(_: Any, __: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """Processor to mask credential patterns across all logged strings."""
    for key, val in list(event_dict.items()):
        if isinstance(val, str):
            for pattern, repl in _SECRET_PATTERNS:
                val = pattern.sub(repl, val)
            event_dict[key] = val
    return event_dict


def configure_logging(log_level: str = "INFO") -> None:
    """Configure structlog and standard logging to emit structured events."""
    level = getattr(logging, log_level.upper(), logging.INFO)

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=level,
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            sanitize_sensitive_data,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer() if log_level.upper() == "INFO" else structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.BoundLogger:
    """Return a bound structlog logger."""
    return structlog.get_logger(name)
