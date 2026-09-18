"""
backend/core/latency_tracker.py
-------------------------------
Tracks and aggregates latencies for:
  - STT (speech-to-text recognition latency)
  - LLM (first token / completion latency)
  - TTS (time to first audio chunk)
  - turn_total (total end-to-end turn latency)

Emits structured events and provides P50/P90/P99 rolling stats.
"""

from __future__ import annotations

import math
import time
from collections import deque
from contextlib import contextmanager
from typing import Generator

from core.logger import get_logger

logger = get_logger("roxstar.latency")


class LatencyTracker:
    """In-memory rolling latency tracker for agent session turns."""

    def __init__(self, window_size: int = 100) -> None:
        self.window_size = window_size
        self._samples: dict[str, deque[float]] = {
            "stt": deque(maxlen=window_size),
            "llm": deque(maxlen=window_size),
            "tts": deque(maxlen=window_size),
            "turn_total": deque(maxlen=window_size),
        }

    def record(self, metric: str, duration_ms: float, extra: dict | None = None) -> None:
        """Record a single latency observation in milliseconds."""
        if metric not in self._samples:
            self._samples[metric] = deque(maxlen=self.window_size)

        self._samples[metric].append(duration_ms)

        log_payload = {
            "metric": metric,
            "duration_ms": round(duration_ms, 2),
        }
        if extra:
            log_payload.update(extra)

        logger.info("latency_recorded", **log_payload)

    @contextmanager
    def measure(self, metric: str, extra: dict | None = None) -> Generator[None, None, None]:
        """Context manager to measure and record execution time of a block."""
        t0 = time.perf_counter()
        try:
            yield
        finally:
            duration_ms = (time.perf_counter() - t0) * 1000.0
            self.record(metric, duration_ms, extra=extra)

    def get_stats(self) -> dict[str, dict[str, float | int]]:
        """Return P50, P90, P99, avg, and count per metric."""
        stats: dict[str, dict[str, float | int]] = {}

        for metric, values in self._samples.items():
            if not values:
                stats[metric] = {"count": 0, "avg": 0.0, "p50": 0.0, "p90": 0.0, "p99": 0.0}
                continue

            sorted_vals = sorted(values)
            count = len(sorted_vals)
            avg = sum(sorted_vals) / count

            def _pct(p: float) -> float:
                idx = max(0, min(count - 1, math.ceil(p * count) - 1))
                return round(sorted_vals[idx], 2)

            stats[metric] = {
                "count": count,
                "avg": round(avg, 2),
                "p50": _pct(0.50),
                "p90": _pct(0.90),
                "p99": _pct(0.99),
            }

        return stats
