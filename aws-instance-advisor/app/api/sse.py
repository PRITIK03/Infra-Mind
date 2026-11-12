"""
Server-Sent Events plumbing for real-time job progress.

Extracted from ``app/api/main.py`` (Part A modularization) — the frame
format, heartbeat constant, and the stream generator now live in one place,
and ``main.py`` keeps only the route that wires them together.

The generator emits the same JSON document the polling endpoint returns
(``job_store.job_snapshot``), so a streaming client and a polling client
share one rendering path.
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
from collections.abc import AsyncIterator
from typing import Any

from fastapi import Request

from app.api.event_bus import TERMINAL_STATUSES, EventSubscription
from app.api.job_store import job_snapshot_from_job
from app.api.rate_limit import stream_limiter
from app.api.runtime import jobs
from app.logging_config import bind_job_id

SSE_MEDIA_TYPE = "text/event-stream"
_HEARTBEAT_FRAME = ": keep-alive\n\n"

# Idle SSE streams wake up every this many seconds to (a) emit a comment
# heartbeat so proxies don't drop a quiet connection and (b) notice a client
# that has gone away.  15s is comfortably inside typical proxy idle timeouts.
SSE_HEARTBEAT_SECONDS: float = float(os.getenv("SSE_HEARTBEAT_SECONDS", "15"))

# Final-event marker attached to the drain snapshot sent when this process is
# shutting down.  The generator recognizes it and closes the stream after
# yielding it — a clean last frame instead of a connection cut mid-event.
SHUTDOWN_NOTICE = (
    "server shutting down — this stream is closing; "
    "reconnect or poll to check the job"
)


class StreamRegistry:
    """Tracks which jobs currently have at least one open SSE stream.

    Refcounted per job_id; the only consumer is the graceful-shutdown drain
    (``shutdown.drain_open_streams``), which needs to know *which jobs* to
    send a final event for.  The registry holds counts, never payloads.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, int] = {}

    def register(self, job_id: str) -> None:
        with self._lock:
            self._jobs[job_id] = self._jobs.get(job_id, 0) + 1

    def unregister(self, job_id: str) -> None:
        with self._lock:
            current = self._jobs.get(job_id, 0)
            if current <= 1:
                self._jobs.pop(job_id, None)
            else:
                self._jobs[job_id] = current - 1

    def open_jobs(self) -> list[str]:
        """Snapshot of job_ids with at least one open stream."""
        with self._lock:
            return list(self._jobs)

    def clear(self) -> None:
        """Drop all registrations (test helper only)."""
        with self._lock:
            self._jobs.clear()


stream_registry = StreamRegistry()


def sse_frame(payload: dict[str, Any]) -> str:
    """Render one SSE data frame.

    ``json.dumps`` escapes newlines inside strings, so a payload is always a
    single ``data:`` line.  That matters: an unescaped newline would end the
    event early in every SSE client.
    """
    return f"data: {json.dumps(payload, separators=(',', ':'))}\n\n"


async def sse_event_stream(
    request: Request,
    job_id: str,
    subscription: EventSubscription,
    client_id: str,
) -> AsyncIterator[str]:
    """Generator behind the SSE endpoint: current state, then live updates.

    Owns the stream-registry registration, the subscription, and the
    concurrency slot and releases all three in ``finally``, which runs on
    the terminal event, on a detected client disconnect, and on task
    cancellation (how an ASGI server tears a stream down when the browser
    goes away).  That last case is the classic SSE leak — without it the
    backend keeps producing frames for nobody.

    A shutdown drain snapshot is recognized by its notice field: it is
    yielded as the final frame and the stream closes cleanly.
    """
    with bind_job_id(job_id):
        stream_registry.register(job_id)
        try:
            # The subscription is already active, so a transition landing
            # between this read and the first yield is queued rather than
            # lost.
            job = await asyncio.to_thread(jobs.get, job_id)
            if job is None:
                # Only reachable if the job vanished between the route's 404
                # check and here (e.g. Redis TTL expiry).  Terminate, don't hang.
                yield sse_frame(
                    {
                        "job_id": job_id,
                        "status": "error",
                        "current_stage": "Unknown",
                        "error": f"Job {job_id} not found",
                    }
                )
                return

            last_payload = job_snapshot_from_job(job)
            yield sse_frame(last_payload)
            if last_payload.get("status") in TERMINAL_STATUSES:
                # Connected after the job finished: that snapshot *is* the
                # final event, so there is nothing left to wait for.
                return

            while True:
                event = await subscription.next_event(timeout=SSE_HEARTBEAT_SECONDS)
                if event is None:
                    # Idle window: emit a heartbeat and use the wake-up to
                    # check whether the client is still there.
                    if subscription.closed or await request.is_disconnected():
                        break
                    yield _HEARTBEAT_FRAME
                    continue
                if event == last_payload:
                    continue  # duplicate snapshot — nothing new to report
                last_payload = event
                yield sse_frame(event)
                if event.get("status") in TERMINAL_STATUSES:
                    break  # terminal: close server-side, events are finished
                if "notice" in event:
                    break  # shutdown drain: final frame was just sent, close
        finally:
            stream_registry.unregister(job_id)
            subscription.close()
            stream_limiter.release(client_id)


__all__ = [
    "SHUTDOWN_NOTICE",
    "SSE_HEARTBEAT_SECONDS",
    "SSE_MEDIA_TYPE",
    "sse_event_stream",
    "sse_frame",
    "stream_registry",
]
