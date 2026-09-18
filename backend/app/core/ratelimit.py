"""Small in-memory rate limiters (single API process)."""
from __future__ import annotations

import threading
import time


class MinInterval:
    """Allow one hit per ``seconds`` per key. ``check`` returns how long the
    caller still has to wait (0 = allowed, and the hit is recorded)."""

    def __init__(self, seconds: float):
        self.seconds = seconds
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()

    def check(self, key: str) -> float:
        now = time.monotonic()
        with self._lock:
            last = self._last.get(key)
            if last is not None and now - last < self.seconds:
                return self.seconds - (now - last)
            self._last[key] = now
            if len(self._last) > 20000:  # keep memory bounded
                cutoff = now - 3600
                self._last = {k: v for k, v in self._last.items() if v > cutoff}
            return 0.0


class FailureThrottle:
    """Counts failures per key in a sliding window. Used to throttle logins."""

    def __init__(self, max_failures: int, window_seconds: float):
        self.max_failures = max_failures
        self.window = window_seconds
        self._hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def _recent(self, key: str, now: float) -> list[float]:
        hits = [t for t in self._hits.get(key, []) if now - t < self.window]
        if hits:
            self._hits[key] = hits
        else:
            self._hits.pop(key, None)
        return hits

    def blocked_for(self, key: str) -> float:
        now = time.monotonic()
        with self._lock:
            hits = self._recent(key, now)
            if len(hits) < self.max_failures:
                return 0.0
            return max(0.0, self.window - (now - hits[0]))

    def fail(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            self._recent(key, now)
            self._hits.setdefault(key, []).append(now)

    def reset(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)
