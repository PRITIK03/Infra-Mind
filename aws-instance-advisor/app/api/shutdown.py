"""
Graceful shutdown coordination (Part B production readiness).

On SIGTERM (the signal Render/Railway/Fly send before killing a container),
uvicorn stops accepting new connections and then invokes the FastAPI
lifespan shutdown handler.  This module coordinates what happens next:

1. No new SSE streams: ``begin_draining`` flips a process-wide flag the
   stream route checks (503 while draining).  SSE is what makes this
   necessary — before streaming, this app only had short-lived requests.
2. A final event for open streams: ``drain_open_streams`` (in sse.py, using
   the registry there) sends every open stream one last snapshot naming
   the situation, then the generator closes — clients see a clean final
   frame (and fall back to polling) instead of a connection cut mid-event.
3. Bounded in-flight wait: agent runs execute on threads that cannot be
   forcibly killed, so we track them with a counter and let them finish
   within ``MAX_SHUTDOWN_GRACE_SECONDS`` (default 10s), then proceed with
   shutdown regardless.  The cap is the whole point — uvicorn has its own
   timeout too, and an uncapped wait just moves the kill further out.

Thread-safe by design: the coordinator is a plain lock-guarded object; the
draining flag is visible to request handlers on the event loop and to
worker threads alike.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading

logger = logging.getLogger(__name__)

# Upper bound on how long shutdown waits for in-flight agent runs to finish
# before proceeding anyway.  Jobs that outlive this keep their thread but
# the process exits; the job's store record stays queryable until TTL.
MAX_SHUTDOWN_GRACE_SECONDS: float = float(os.getenv("MAX_SHUTDOWN_GRACE_SECONDS", "10"))


class ShutdownCoordinator:
    """Tracks drain state and in-flight background jobs."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._draining = False
        self._in_flight = 0

    @property
    def draining(self) -> bool:
        with self._lock:
            return self._draining

    def begin_draining(self) -> None:
        """Refuse new SSE connections from this point on (idempotent)."""
        with self._lock:
            if not self._draining:
                self._draining = True
                logger.info("Shutdown: draining — no new SSE streams will be accepted")

    def job_started(self) -> None:
        with self._lock:
            self._in_flight += 1

    def job_finished(self) -> None:
        with self._lock:
            self._in_flight = max(0, self._in_flight - 1)

    def in_flight_count(self) -> int:
        with self._lock:
            return self._in_flight

    def reset(self) -> None:
        """Restore the pre-shutdown state (test helper only)."""
        with self._lock:
            self._draining = False
            self._in_flight = 0

    async def wait_for_inflight(self, timeout: float) -> int:
        """Wait (at most *timeout* seconds) for in-flight jobs to finish.

        Returns the number of jobs still running when the wait ended —
        0 means everything finished inside the grace period.
        """
        import time

        deadline = time.monotonic() + max(0.0, timeout)
        while time.monotonic() < deadline:
            if self.in_flight_count() == 0:
                return 0
            await asyncio.sleep(0.05)
        return self.in_flight_count()


coordinator = ShutdownCoordinator()


def drain_open_streams() -> int:
    """Send a final clean event to every open SSE stream.

    Publishes one last snapshot per job-with-open-streams through the event
    bus; the stream generator recognizes the notice field, yields it, and
    closes.  Runs synchronously (store read + bus publish can block on a
    Redis round-trip, so callers should run this in a thread).

    Returns the number of jobs the drain notice was sent for.
    """
    from app.api import sse as sse_module
    from app.api.job_store import job_snapshot_from_job
    from app.api.runtime import event_bus, jobs

    job_ids = sse_module.stream_registry.open_jobs()
    sent = 0
    for job_id in job_ids:
        try:
            job = jobs.get(job_id)
            if job is None:
                continue
            snapshot = job_snapshot_from_job(job)
            snapshot["notice"] = sse_module.SHUTDOWN_NOTICE
            event_bus.publish(job_id, snapshot)
            sent += 1
        except Exception as exc:
            logger.warning("Shutdown: failed to drain stream for %s (%s)", job_id, exc)
    if sent:
        logger.info("Shutdown: sent final events to %d streamed job(s)", sent)
    return sent
