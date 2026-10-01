"""
FastAPI application exposing the LangGraph agent over HTTP.

Agent invocations can take 2-3+ minutes under free-tier LLM load, so all
work is dispatched to a background thread and clients poll via
GET /api/recommend/{job_id} for progress. The agent's multi-turn
requirement-collection loop is surfaced via the awaiting_input status +
POST /api/recommend/{job_id}/answer.

Real-time progress (Server-Sent Events)
--------------------------------------
GET /api/recommend/{job_id}/stream pushes those same snapshots as they
happen, for clients that can hold a connection open.  Polling remains
supported unchanged as the fallback, and events are published from the job
store's existing state-transition points (publish implemented in
app/api/job_store.py, transport in app/api/event_bus.py) so there is exactly
one source of truth for progress.

Module layout (Part A modularization)
-------------------------------------
This module owns the FastAPI app object, middleware, and the route
definitions only.  Everything else moved to focused modules and is
re-exported here so existing imports keep working:

    app/api/schemas.py         request bodies + validators
    app/api/rate_limit.py      per-IP request + concurrent-stream limiters
    app/api/runtime.py         the job store + event bus singletons
    app/api/job_runner.py      background graph runs, watchdog, run records
    app/api/sse.py             SSE frames, heartbeat, stream generator
    app/api/error_reporting.py Sentry wiring (optional)
    app/api/health.py          liveness/readiness checks

Thread-pool sizing and the wall-clock job timeout are documented in
app/api/job_runner.py, where the executor and JOB_* constants now live.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel  # noqa: F401  (re-exported for route typing)

from app.api.error_reporting import (
    capture_exception as _capture_exception,
    capture_message as _capture_message,
    init_sentry,
)
from app.api.health import build_readiness_report
from app.api.job_runner import (
    JOB_THREAD_POOL_SIZE,  # noqa: F401  (re-exported; see module docstring)
    JOB_TIMEOUT_SECONDS,  # noqa: F401  (re-exported; patched by tests)
    empty_state as _empty_state,
    graph_loop_sync as _graph_loop_sync,
    resume_with_answer_sync as _resume_with_answer_sync,
    submit_with_timeout as _submit_with_timeout,
)
from app.api.job_store import (
    FollowupExchange,  # noqa: F401  (re-exported convenience alias)
    Job,
    JobStatus,  # noqa: F401  (kept for callers/annotations that import it here)
    JobStoreBackend,  # noqa: F401
    job_snapshot_from_job,
)
from app.api.rate_limit import (
    RATE_LIMIT_MAX_REQUESTS,  # noqa: F401  (re-exported)
    RATE_LIMIT_WINDOW_SECONDS,  # noqa: F401  (re-exported)
    client_id as _client_id,
    recommend_rate_limiter,
    stream_limiter,
)
from app.api.runtime import event_bus, jobs
from app.api.schemas import AnswerRequest, FollowupRequest, RecommendRequest
from app.api.sse import (
    SSE_HEARTBEAT_SECONDS,  # noqa: F401  (re-exported; patched by tests)
    SSE_MEDIA_TYPE,
    sse_event_stream as _sse_event_stream,
)
from app.api.shutdown import (
    MAX_SHUTDOWN_GRACE_SECONDS,
    coordinator as shutdown_coordinator,
    drain_open_streams,
)
from app.config import get_api_settings
from app.logging_config import bind_job_id, configure_logging

logger = logging.getLogger(__name__)

# One structured-logging install for the whole process.  LOG_FORMAT=text
# gives the human-readable variant for local development.
configure_logging()

# ---------------------------------------------------------------------------
# Concurrency + timeout constants (overridable via env for larger hosts)
# ---------------------------------------------------------------------------

# Max simultaneous agent-run threads. Conservative for small cloud hosts
# (Render free/starter, Railway, Fly.io shared-cpu-1x).
JOB_THREAD_POOL_SIZE: int = int(os.getenv("JOB_THREAD_POOL_SIZE", "8"))

# Hard wall-clock limit for a single complete agent run, in seconds.
# A full run under free-tier rate limiting can legitimately take 3-4 min;
# 10 min is generous enough for paid keys while bounding any true hang.
JOB_TIMEOUT_SECONDS: float = float(os.getenv("JOB_TIMEOUT_SECONDS", "600"))

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------


# Request bodies live in app/api/schemas.py (imported above) — see that module
# for the field constraints and the whitespace-only validation rules.


# ---------------------------------------------------------------------------
# Optional error monitoring (Sentry) — never required, never blocking.
#
# Initialized BEFORE the FastAPI app is constructed: Sentry's FastAPI /
# Starlette integration patches the framework at init time, so initializing
# after `FastAPI(...)` exists can miss the instrumentation. When SENTRY_DSN
# is unset (or sentry-sdk isn't installed) this is a no-op and the app runs
# exactly as it did before.
# ---------------------------------------------------------------------------

# Error monitoring lives in app/api/error_reporting.py.  Initialization must
# still run here — before ``FastAPI(...)`` is constructed — because Sentry
# patches the framework at init time.  No-op when SENTRY_DSN is unset.
init_sentry()

api_settings = get_api_settings()

app = FastAPI(title="AWS Instance Advisor API", version="1.0.0")


async def _graceful_shutdown() -> None:
    """Coordinate process shutdown: drain streams, bound in-flight jobs.

    Invoked from the FastAPI lifespan handler below on SIGTERM.  Kept as a
    named function (rather than inline) so tests can trigger the full
    sequence directly without sending a real process signal:

    1. refuse new SSE connections (``stream_job_progress`` returns 503),
    2. publish one final snapshot to every open stream (each stream closes
       itself after yielding it),
    3. wait up to MAX_SHUTDOWN_GRACE_SECONDS for in-flight agent runs to
       finish, then proceed regardless — the cap is the point.
    """
    shutdown_coordinator.begin_draining()
    try:
        # drain_open_streams can block on a Redis round-trip — keep it off the
        # event loop, same discipline as the store reads in the routes.
        drained = await asyncio.to_thread(drain_open_streams)
    except Exception as exc:  # pragma: no cover - depends on transport
        drained = 0
        logger.warning("Shutdown: stream drain failed (%s)", exc)
    remaining = await shutdown_coordinator.wait_for_inflight(MAX_SHUTDOWN_GRACE_SECONDS)
    if remaining:
        logger.warning(
            "Shutdown: proceeding with %d in-flight job(s) after the grace period",
            remaining,
        )
    else:
        logger.info("Shutdown: drained %d stream(s), no in-flight jobs", drained)


@asynccontextmanager
async def _lifespan(app: FastAPI):  # noqa: ARG001
    """Startup yields immediately; shutdown drains via _graceful_shutdown."""
    yield
    await _graceful_shutdown()


app.router.lifespan_context = _lifespan

app.add_middleware(
    CORSMiddleware,
    allow_origins=(
        [api_settings.cors_allowed_origin]
        if api_settings.cors_allowed_origin
        else []
    ),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    try:
        response = await call_next(request)
    except HTTPException as exc:
        response = JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
            headers=exc.headers,
        )
    except Exception as exc:
        _capture_exception(exc)
        logger.exception("Unhandled error processing %s: %s", request.url.path, exc)
        response = JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Content-Security-Policy"] = "default-src 'self'"
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    if isinstance(exc, HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
            headers=exc.headers,
        )
    _capture_exception(exc)
    logger.exception("Unhandled error processing %s: %s", request.url.path, exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _job_response(job: Job) -> dict[str, Any]:
    """Polling response for a job — the pre-existing public shape.

    Delegates to ``job_store.job_snapshot_from_job`` so the polling response
    and the SSE event payloads are literally the same projection: a client
    can render a poll result and a stream event with one code path, and the
    two can never drift apart.
    """
    return job_snapshot_from_job(job)


# ---------------------------------------------------------------------------
# Routes
#
# Request bodies: app/api/schemas.py · rate limiting: app/api/rate_limit.py ·
# SSE frames/generator: app/api/sse.py · job execution: app/api/job_runner.py
# ---------------------------------------------------------------------------


@app.get("/api/health")
def health() -> dict[str, Any]:
    """Liveness probe. No LLM or live-data calls."""
    return {"status": "ok", "time": time.time()}


@app.get("/api/health/ready")
async def readiness() -> JSONResponse:
    """Readiness probe: is this instance configured to serve traffic?

    Cheap and local-only by design (see app/api/health.py): no model calls,
    no live-data fetches, just environment presence plus one Redis PING at
    most — safe for a load balancer or monitor to hit every few seconds.
    Returns 200 when the required config is present, 503 otherwise.
    """
    report, ready = await asyncio.to_thread(build_readiness_report)
    return JSONResponse(status_code=200 if ready else 503, content=report)


# Simple in-process cache so the landing page stat readout doesn't hammer
# Vantage on every page load.  TTL of 10 minutes is generous — instance
# counts don't change mid-session.
_stats_cache: dict[str, Any] = {}
_stats_cache_time: float = 0.0
_STATS_TTL_S: float = 300.0


@app.get("/api/stats")
def get_stats() -> dict[str, Any]:
    """
    Returns live counts of tracked instance types.
    Used by the landing page readout — cached for _STATS_TTL_S seconds.
    """
    global _stats_cache, _stats_cache_time
    now = time.time()
    if _stats_cache and (now - _stats_cache_time) < _STATS_TTL_S:
        return _stats_cache

    from app.tools.aws_instance_data import (
        fetch_ec2_instance_data,
        fetch_rds_instance_data,
        fetch_cache_instance_data,
        InstanceDataUnavailableError,
    )
    counts: dict[str, int] = {}
    for key, fetcher in [
        ("ec2", fetch_ec2_instance_data),
        ("rds", fetch_rds_instance_data),
        ("cache", fetch_cache_instance_data),
    ]:
        try:
            counts[key] = len(fetcher())
        except InstanceDataUnavailableError:
            counts[key] = 0

    _stats_cache = counts
    _stats_cache_time = now
    return counts


@app.post("/api/recommend")
def create_recommend_job(request: Request, req: RecommendRequest) -> dict[str, Any]:
    """Kick off a new agent run. Returns immediately with a job_id to poll."""
    client_id = _client_id(request)
    allowed, retry_after = recommend_rate_limiter.allow(client_id)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Too many recommendation requests. Please try again shortly.",
            headers={"Retry-After": str(retry_after)},
        )
    job_id = str(uuid.uuid4())
    state = _empty_state()
    state["latest_user_message"] = req.message
    state["consensus_requested"] = req.consensus

    job = Job(
        job_id=job_id,
        status="collecting",
        current_stage="Initializing",
        state=state,
    )
    jobs.put(job)
    _submit_with_timeout(_graph_loop_sync, job_id, state)

    return {"job_id": job_id}


@app.get("/api/recommend/{job_id}")
async def get_job_status(job_id: str) -> dict[str, Any]:
    """Poll the current state / progress / result of a job.

    The store read is wrapped in asyncio.to_thread so a Redis round-trip
    (when the Redis-backed store is configured) never blocks the event
    loop under concurrent polling — the same discipline already applied
    to the blocking graph execution.

    Unchanged by the streaming feature: this remains the polling interface
    (backward compatible, and the fallback for clients or intermediaries
    that can't hold an SSE connection open) and returns exactly the same
    document each streamed event carries.
    """
    job = await asyncio.to_thread(jobs.get, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return _job_response(job)


# ---------------------------------------------------------------------------
# Real-time progress streaming (Server-Sent Events)
#
# Frames + generator: app/api/sse.py.  Additive: the polling endpoint above
# keeps working unchanged, and this route pushes the very same snapshots as
# they happen, from the state transitions that already exist
# (JobStoreBackend.update_stage / update_status / update_retry_info) — there
# is no parallel event system.
# ---------------------------------------------------------------------------


@app.get("/api/recommend/{job_id}/stream")
async def stream_job_progress(request: Request, job_id: str) -> StreamingResponse:
    """Live job progress as Server-Sent Events.

    Behaviour:
      * the current state is sent immediately on connect, so a client that
        attaches mid-run (or after completion) is correct from frame one;
      * one event per state transition from the store's existing update
        points, including the timeout watchdog's terminal error;
      * the stream closes server-side after the terminal ``done``/``error``
        event, and also when the client disconnects.

    Each event's payload is the same JSON document
    ``GET /api/recommend/{job_id}`` returns, so polling and streaming clients
    share one rendering path.

    Concurrency is bounded per IP by open *streams* rather than by the
    requests-per-minute limiter: a single long-lived connection is not a
    burst of requests, and a per-minute window would miscount it (blocking a
    second legitimate tab, or never reflecting that a stream is still open).
    """
    # 404 before reserving a slot: an unknown/expired id must not consume a
    # client's stream budget.
    job = await asyncio.to_thread(jobs.get, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    # While the process is draining for shutdown, refuse new streams — the
    # client falls back to polling, which needs no long-lived connection.
    if shutdown_coordinator.draining:
        raise HTTPException(
            status_code=503,
            detail="Server is shutting down; please reconnect or poll.",
            headers={"Retry-After": "2"},
        )

    client_id = _client_id(request)
    if not stream_limiter.acquire(client_id):
        raise HTTPException(
            status_code=429,
            detail=(
                "Too many concurrent progress streams "
                f"(max {stream_limiter.max_streams} per client)."
            ),
            headers={"Retry-After": "5"},
        )

    try:
        subscription = await event_bus.subscribe(job_id)
    except Exception:
        # Never leak the slot if subscribing itself fails.
        stream_limiter.release(client_id)
        raise

    return StreamingResponse(
        _sse_event_stream(request, job_id, subscription, client_id),
        media_type=SSE_MEDIA_TYPE,
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # Proxies (nginx especially) buffer proxied responses by default,
            # which would hold frames back until their buffer fills.
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/share/{job_id}")
async def get_shared_result(job_id: str) -> dict[str, Any]:
    """Read-only alias of the polling endpoint, for share links.

    A new endpoint is only justified for the contract it enforces: a share
    link should only work for a completed result, so anything that is not
    ``status == "done"`` (in progress, awaiting input, failed, or expired)
    returns 404 instead of exposing progress or error detail.

    Access-control note: there is no auth on this app, and
    ``GET /api/recommend/{job_id}`` already returns a job's result to anyone
    holding its unguessable UUIDv4 — a pre-existing design characteristic of
    this backend (and the same reason the polling endpoint is safe to load
    balance), not a privacy regression introduced by sharing.  This alias
    adds the "finished results only" rule; genuine access control would need
    authn/authz on both routes, which is out of scope here.
    """
    job = await asyncio.to_thread(jobs.get, job_id)
    if job is None or job.status != "done":
        raise HTTPException(status_code=404, detail=f"Shared result {job_id} not found")
    return _job_response(job)


@app.post("/api/recommend/{job_id}/answer")
async def answer_question(request: Request, job_id: str, req: AnswerRequest) -> dict[str, Any]:
    """
    Provide the user's reply to a follow-up question. Only valid when
    the job is in 'awaiting_input' status. Resumes execution in the
    background.
    """
    client_id = _client_id(request)
    allowed, retry_after = recommend_rate_limiter.allow(client_id)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Too many recommendation requests. Please try again shortly.",
            headers={"Retry-After": str(retry_after)},
        )

    job = await asyncio.to_thread(jobs.get, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    if job.status != "awaiting_input":
        raise HTTPException(
            status_code=400,
            detail=f"Job is not awaiting input (current status: {job.status})",
        )

    _submit_with_timeout(_resume_with_answer_sync, job_id, req.answer)

    return {"job_id": job_id, "status": "running"}


@app.post("/api/recommend/{job_id}/followup")
async def ask_followup_question(
    request: Request,
    job_id: str,
    req: FollowupRequest,
) -> dict[str, Any]:
    """
    Ask a conversational follow-up question on an already completed job.
    Only valid when the job's status is 'done'.
    """
    client_id = _client_id(request)
    allowed, retry_after = recommend_rate_limiter.allow(client_id)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Too many recommendation requests. Please try again shortly.",
            headers={"Retry-After": str(retry_after)},
        )

    job = await asyncio.to_thread(jobs.get, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    if job.status != "done":
        raise HTTPException(
            status_code=400,
            detail=f"Job is not done (current status: {job.status})",
        )

    sdr = None
    technical_needs = None
    if job.result:
        sdr = job.result.get("system_design_recommendation")
        technical_needs = job.result.get("technical_needs")
    if sdr is None and job.state:
        sdr = job.state.get("system_design_recommendation")
        technical_needs = job.state.get("technical_needs")

    if sdr is None:
        raise HTTPException(
            status_code=400,
            detail="Job has no completed system design recommendation to answer questions about.",
        )

    from datetime import datetime, timezone
    from app.api.job_store import FollowupExchange
    from app.llm.followup import answer_followup

    answer = await asyncio.to_thread(
        answer_followup,
        sdr,
        technical_needs,
        req.question,
        job.followup_history,
    )

    now_iso = datetime.now(timezone.utc).isoformat()
    exchange = FollowupExchange(
        question=req.question,
        answer=answer,
        timestamp=now_iso,
    )
    await asyncio.to_thread(jobs.add_followup, job_id, exchange)

    updated_job = await asyncio.to_thread(jobs.get, job_id)
    history = (
        [e.model_dump() for e in updated_job.followup_history]
        if updated_job
        else [exchange.model_dump()]
    )

    return {
        "job_id": job_id,
        "answer": answer,
        "exchange": exchange.model_dump(),
        "followup_history": history,
    }


@app.get("/api/runs")
def get_runs(page: int = 1, page_size: int = 20) -> dict[str, Any]:
    """
    Return paginated run history from the observability store.

    When DATABASE_URL is not configured, returns an empty list with
    ``observability_configured: false`` — not an error.

    Query params:
      page      (int, default 1)      — 1-based page number
      page_size (int, default 20)     — rows per page, capped at 100
    """
    from app.observability import get_runs as _get_runs
    page = max(1, page)
    page_size = max(1, min(page_size, 100))
    return _get_runs(page=page, page_size=page_size)
