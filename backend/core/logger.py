"""
backend/core/logger.py
----------------------
Structured logging configuration using structlog with a non-blocking
QueueHandler back-end.

The event loop is NEVER blocked by log I/O:
  - All log records are placed on an in-memory queue (non-blocking).
  - A single background daemon thread drains the queue and writes to stdout.
  - structlog is wired to use standard logging so both share the same queue.
"""

from __future__ import annotations

import logging
import logging.handlers
import queue
import re
import sys
import threading
from typing import Any

import structlog

# ---------------------------------------------------------------------------
# Secret masking
# ---------------------------------------------------------------------------
_SECRET_PATTERNS = [
    (re.compile(r"://([^:]+):([^@]+)@"), r"://\1:***@"),
    (re.compile(r"(api[_-]?key|password|token|secret)=([^\s,&]+)", re.IGNORECASE), r"\1=***"),
    (re.compile(r"(sk_[a-zA-Z0-9_-]{20,})"), r"sk_***"),
    (re.compile(r"(AIza[a-zA-Z0-9_-]{30,})"), r"AIza_***"),
]


def sanitize_sensitive_data(_: Any, __: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """Mask credential patterns across all logged strings."""
    for key, val in list(event_dict.items()):
        if isinstance(val, str):
            for pattern, repl in _SECRET_PATTERNS:
                val = pattern.sub(repl, val)
            event_dict[key] = val
    return event_dict


# ---------------------------------------------------------------------------
# Non-blocking queue-backed logging setup
# ---------------------------------------------------------------------------

# Module-level state so configure_logging() is idempotent
_listener: logging.handlers.QueueListener | None = None
_log_queue: queue.SimpleQueue | None = None
_configured = False


def configure_logging(log_level: str = "INFO") -> None:
    """Configure structlog + stdlib logging with a non-blocking QueueHandler.

    All I/O is moved to a background daemon thread so the asyncio event loop
    is never blocked by console writes or file flushes.
    """
    global _listener, _log_queue, _configured
    if _configured:
        return
    _configured = True

    level = getattr(logging, log_level.upper(), logging.INFO)

    # 1. Build the real (blocking) stdout handler for the background thread
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(level)
    stdout_handler.setFormatter(logging.Formatter("%(message)s"))

    # 2. Create a queue and wire QueueHandler -> QueueListener -> stdout_handler
    _log_queue = queue.SimpleQueue()
    queue_handler = logging.handlers.QueueHandler(_log_queue)
    queue_handler.setLevel(level)

    listener = logging.handlers.QueueListener(
        _log_queue,
        stdout_handler,
        respect_handler_level=True,
    )
    listener.start()          # starts daemon thread
    _listener = listener

    # 3. Root stdlib logger: only the non-blocking QueueHandler attached
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(queue_handler)
    root.setLevel(level)

    # Silence overly verbose third-party loggers
    for noisy in ("httpx", "httpcore", "urllib3", "websockets", "aiohttp"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    # 4. Wire structlog to emit through stdlib logging (goes through queue)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            sanitize_sensitive_data,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            # Always use ConsoleRenderer for human-readable logs (async-safe since
            # the actual I/O happens on the background thread via QueueHandler)
            structlog.dev.ConsoleRenderer(colors=False),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.BoundLogger:
    """Return a bound structlog logger that uses the non-blocking queue backend."""
    return structlog.get_logger(name)
