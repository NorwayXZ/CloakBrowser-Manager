"""Panel-side log entries, written into the Manager's own log.

The panel sends its warnings and errors here in small batches so a problem
report has both halves in one manager.log. The panel already masks secrets;
this module masks them again (a page can be buggy) and caps both entry size
and rate, so a runaway loop in the page cannot flood the log or the disk.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from collections import deque

logger = logging.getLogger("cloakbrowser.frontend")

RATE_WINDOW_SECONDS = 60.0
RATE_LIMIT = 300  # entries per window; the rest are dropped

_URL_CREDENTIALS_RE = re.compile(r"([a-z][a-z0-9+.-]*://)[^\s/@:]+:[^\s/@]+@", re.IGNORECASE)
_SECRET_VALUE_RE = re.compile(
    r"((?:password|passwd|pwd|token|secret|api[_-]?key|authorization|cookie)[\"']?\s*[:=]\s*[\"']?)[^\s\"',;&]+",
    re.IGNORECASE,
)
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")

_LEVELS = {"info": logging.INFO, "warn": logging.WARNING, "error": logging.ERROR}


def redact(text: str) -> str:
    text = _URL_CREDENTIALS_RE.sub(r"\1***:***@", text)
    return _SECRET_VALUE_RE.sub(r"\1***", text)


def _clean(text: str | None) -> str:
    if not text:
        return ""
    # Newlines would let one entry pose as several log lines.
    return _CONTROL_RE.sub(" ", redact(text)).replace("\n", " ⏎ ").strip()


class RateLimiter:
    """Sliding-window counter shared by all requests of this process."""

    def __init__(self, limit: int = RATE_LIMIT, window: float = RATE_WINDOW_SECONDS, clock=time.monotonic):
        self.limit = limit
        self.window = window
        self.clock = clock
        self._stamps: deque[float] = deque()
        self._lock = threading.Lock()

    def take(self, count: int) -> int:
        """Reserve up to ``count`` slots; returns how many were granted."""
        with self._lock:
            now = self.clock()
            while self._stamps and now - self._stamps[0] >= self.window:
                self._stamps.popleft()
            granted = max(0, min(count, self.limit - len(self._stamps)))
            self._stamps.extend([now] * granted)
            return granted


_limiter = RateLimiter()


def write_entries(entries: list[dict], limiter: RateLimiter | None = None) -> tuple[int, int]:
    """Log the entries that fit the rate limit; returns (accepted, dropped)."""
    granted = (limiter or _limiter).take(len(entries))
    for entry in entries[:granted]:
        level = _LEVELS.get(entry.get("level", "error"), logging.ERROR)
        parts = [f"[{_clean(entry.get('route')) or '-'}]"]
        action = _clean(entry.get("action"))
        if action:
            parts.append(f"{action}:")
        parts.append(_clean(entry.get("message")) or "(empty)")
        detail = _clean(entry.get("detail"))
        if detail:
            parts.append(f"| {detail}")
        at = _clean(entry.get("at"))
        if at:
            parts.append(f"(client {at})")
        logger.log(level, " ".join(parts))
    dropped = len(entries) - granted
    if dropped:
        logger.warning("Dropped %d panel log entries over the rate limit", dropped)
    return granted, dropped
