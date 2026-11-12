"""
Process-wide application singletons: the job store and the event bus.

Built once at import time from configuration (``REDIS_URL`` selects the
Redis-backed variants, otherwise the in-process fallbacks) and shared by
every module that touches job state — the HTTP routes, the SSE stream, and
the background job runner.

This lives in its own module so those modules can depend on the store
without importing the FastAPI app module, which imports them back.
``app/api/main.py`` re-exports ``jobs`` / ``event_bus`` unchanged.
"""

from __future__ import annotations

from app.api.event_bus import JobEventBus, build_event_bus
from app.api.job_store import JobStoreBackend, build_job_store

# Pluggable publish/subscribe backend for the SSE progress stream.  Selected
# from the same REDIS_URL as the job store and handed to the store, so every
# state transition is published from the existing update points — there is no
# parallel event system.
event_bus: JobEventBus = build_event_bus()
jobs: JobStoreBackend = build_job_store(publisher=event_bus)

__all__ = ["event_bus", "jobs"]
