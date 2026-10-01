"""
Per-client request limiting and concurrent-stream limiting.

Extracted from ``app/api/main.py`` (Part A modularization) — no behavior
change; ``main.py`` re-exports every public name here so route code and the
test suite are unaffected.

Two different limiters, because the two traffic shapes are different:

* :class:`InMemoryRateLimiter` — a small process-local sliding window used
  for expensive public POSTs (recommend / answer / followup).
* :class:`InMemoryConcurrentStreamLimiter` — counts *concurrently open* SSE
  streams per client IP.  A long-lived streaming connection is not a burst
  of requests, so the sliding window is deliberately not applied to it (see
  the class docstring for the reasoning).

Both are deliberately in-process: they are a cheap abuse guard for a
single-instance deployment, not a distributed quota system. With multiple
replicas each instance enforces its own share, which is the same scope as
the in-memory job store.
"""

from __future__ import annotations

import os
import threading
import time
from collections import deque

from fastapi import Request


def client_id(request: Request) -> str:
    """Client identity used by both limiters.

    The single source of truth for IP extraction: the streaming endpoint
    reuses this rather than reimplementing proxy/None handling.
    """
    return request.client.host if request.client else "unknown"


class InMemoryRateLimiter:
    """Small process-local sliding-window limiter for expensive public requests."""

    def __init__(self, max_requests: int, window_seconds: float) -> None:
        self.max_requests = max(1, max_requests)
        self.window_seconds = max(1.0, window_seconds)
        self._requests: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, client_id: str, now: float | None = None) -> tuple[bool, int]:
        current = time.monotonic() if now is None else now
        with self._lock:
            timestamps = self._requests.setdefault(client_id, deque())
            cutoff = current - self.window_seconds
            while timestamps and timestamps[0] <= cutoff:
                timestamps.popleft()
            if len(timestamps) >= self.max_requests:
                retry_after = max(1, int(self.window_seconds - (current - timestamps[0])))
                return False, retry_after
            timestamps.append(current)
            return True, 0

    def clear(self) -> None:
        """Clear state for tests and controlled in-process maintenance."""
        with self._lock:
            self._requests.clear()


RATE_LIMIT_MAX_REQUESTS = int(os.getenv("RATE_LIMIT_MAX_REQUESTS", "5"))
RATE_LIMIT_WINDOW_SECONDS = float(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))
recommend_rate_limiter = InMemoryRateLimiter(
    RATE_LIMIT_MAX_REQUESTS,
    RATE_LIMIT_WINDOW_SECONDS,
)

# Cap on *concurrently open* progress streams per client IP.
MAX_CONCURRENT_STREAMS_PER_IP: int = int(os.getenv("MAX_CONCURRENT_STREAMS_PER_IP", "5"))


class InMemoryConcurrentStreamLimiter:
    """Bounds concurrently open SSE streams per client IP.

    A long-lived streaming connection is architecturally different from
    repeated quick REST calls, so the requests-per-minute limiter is
    deliberately NOT applied to the stream endpoint: a sliding request
    window would either reject a legitimate second tab (the connection
    itself costs one "request" that stays open) or, if incremented once on
    connect, would never reflect that the connection is still held.

    Instead this counts *open* streams and releases a slot the moment the
    generator finishes — on the terminal event, on client disconnect, or on
    task cancellation.  Kept small (default 5) because each open stream
    holds a subscription and an event loop task.
    """

    def __init__(self, max_streams: int) -> None:
        self.max_streams = max(1, max_streams)
        self._active: dict[str, int] = {}
        self._lock = threading.Lock()

    def acquire(self, client_id: str) -> bool:
        """Reserve a slot; returns False when the client is at the cap."""
        with self._lock:
            current = self._active.get(client_id, 0)
            if current >= self.max_streams:
                return False
            self._active[client_id] = current + 1
            return True

    def release(self, client_id: str) -> None:
        """Return a slot (idempotent — safe to call on paths that never acquired)."""
        with self._lock:
            current = self._active.get(client_id, 0)
            if current <= 1:
                self._active.pop(client_id, None)
            else:
                self._active[client_id] = current - 1

    def active_count(self, client_id: str) -> int:
        with self._lock:
            return self._active.get(client_id, 0)

    def clear(self) -> None:
        """Clear state for tests and controlled in-process maintenance."""
        with self._lock:
            self._active.clear()


stream_limiter = InMemoryConcurrentStreamLimiter(MAX_CONCURRENT_STREAMS_PER_IP)
