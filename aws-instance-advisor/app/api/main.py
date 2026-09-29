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

Thread-pool sizing
------------------
We use an explicit ThreadPoolExecutor rather than the default
asyncio.to_thread executor (which uses ThreadPoolExecutor(max_workers=None),
defaulting to min(32, os.cpu_count() + 4) — potentially 36 threads on a
4-core box, or just the OS default on a constrained host).

On a small Render/Railway/Fly instance (1–2 vCPUs, 512 MB – 1 GB RAM),
each agent thread holds a live HTTP connection + LangGraph state + LLM
response buffers. Running many concurrent threads on such a host causes
memory pressure and scheduler thrashing before the concurrency limit
matters. JOB_THREAD_POOL_SIZE=8 is deliberately conservative: it
allows meaningful concurrency (8 simultaneous agent runs) while leaving
headroom for the FastAPI worker, uvicorn I/O loop, and OS overhead.

If a job hangs (even after the LLM-layer fixes), JOB_TIMEOUT_SECONDS
ensures the slot is returned within a bounded time.  Adjust both
constants via environment variables for larger hosts.

Wall-clock job timeout
----------------------
Each background job is submitted via executor.submit() and tracked with
Future.result(timeout=JOB_TIMEOUT_SECONDS).  A concurrent.futures.TimeoutError
marks the job as "error" with a clear message — this is an independent
safety net that fires regardless of what's happening inside the graph,
protecting against any future hang scenario, not just rate-limit loops.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
import os
import threading
import time
import uuid
from collections import deque
from collections.abc import AsyncIterator
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, field_validator

from app.agent.graph import build_graph
from app.agent.state import AgentState
from app.api.event_bus import (
    TERMINAL_STATUSES,
    EventSubscription,
    JobEventBus,
    build_event_bus,
)
from app.api.job_store import (
    Job,
    JobStatus,
    JobStoreBackend,
    build_job_store,
    job_snapshot_from_job,
)
from app.api.jobs import label_for_node
from app.config import get_api_settings
from app.models.schemas import SystemDesignRecommendation, UserRequirements

logger = logging.getLogger(__name__)

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


class RecommendRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=10_000)
    consensus: bool = Field(
        default=False,
        description=(
            "Opt-in multi-model consensus.  When true, the final holistic "
            "recommendation is generated once more against a second model "
            "(CONSENSUS_MODEL, else the first LLM_FALLBACK_MODELS entry) and "
            "compared deterministically — at the cost of one extra full LLM "
            "call.  Defaults to False: consensus never runs unless explicitly "
            "requested."
        ),
    )

    @field_validator("message")
    @classmethod
    def validate_message(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("message must contain non-whitespace text")
        return value


class AnswerRequest(BaseModel):
    answer: str = Field(..., min_length=1, max_length=2_000)

    @field_validator("answer")
    @classmethod
    def validate_answer(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("answer must contain non-whitespace text")
        return value


class FollowupRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2_000)

    @field_validator("question")
    @classmethod
    def validate_question(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("question must contain non-whitespace text")
        return value


# ---------------------------------------------------------------------------
# Optional error monitoring (Sentry) — never required, never blocking.
#
# Initialized BEFORE the FastAPI app is constructed: Sentry's FastAPI /
# Starlette integration patches the framework at init time, so initializing
# after `FastAPI(...)` exists can miss the instrumentation. When SENTRY_DSN
# is unset (or sentry-sdk isn't installed) this is a no-op and the app runs
# exactly as it did before.
# ---------------------------------------------------------------------------

_sentry_enabled: bool = False


def init_sentry(dsn: str | None = None, *, traces_sample_rate: float | None = None) -> bool:
    """Initialize Sentry error monitoring if a DSN is configured.

    Returns True when Sentry was initialized, False when it was skipped.
    Skipping is the normal case (no SENTRY_DSN configured) and is never an
    error — matching the Tavily / GitHub-MCP / DATABASE_URL / REDIS_URL
    graceful-optional pattern.

    The import is deferred so a deployment without sentry-sdk installed
    still starts up cleanly.
    """
    global _sentry_enabled

    from app.config import get_sentry_settings

    settings = get_sentry_settings()
    if dsn is None:
        dsn = settings.sentry_dsn
    if not dsn:
        # No DSN configured — leave Sentry disabled.
        _sentry_enabled = False
        return False

    if traces_sample_rate is None:
        traces_sample_rate = settings.traces_sample_rate

    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration

        sentry_sdk.init(
            dsn=dsn,
            integrations=[FastApiIntegration()],
            # Error monitoring only by default; tracing is opt-in via
            # SENTRY_TRACES_SAMPLE_RATE to avoid burning free-tier quota.
            traces_sample_rate=traces_sample_rate,
            send_default_pii=False,
        )
        _sentry_enabled = True
        logger.info("Error monitoring: Sentry initialized")
        return True
    except Exception as exc:  # pragma: no cover - depends on local env
        _sentry_enabled = False
        logger.warning(
            "SENTRY_DSN is configured but Sentry could not be initialized (%s); "
            "continuing without error monitoring.",
            exc,
        )
        return False


def _capture_exception(exc: BaseException) -> None:
    """Report an already-handled exception to Sentry, if it's enabled.

    Used for errors this module catches deliberately (graph failures, job
    timeouts) — those never propagate to FastAPI, so the automatic
    integration cannot see them. No-ops when Sentry is unconfigured.
    """
    if not _sentry_enabled:
        return
    try:
        import sentry_sdk

        sentry_sdk.capture_exception(exc)
    except Exception:  # pragma: no cover - observability must never crash
        pass


def _capture_message(message: str) -> None:
    """Report a non-exception job failure (e.g. wall-clock timeout) to Sentry.

    No-ops when Sentry is unconfigured, same as _capture_exception.
    """
    if not _sentry_enabled:
        return
    try:
        import sentry_sdk

        sentry_sdk.capture_message(message, level="error")
    except Exception:  # pragma: no cover - observability must never crash
        pass


init_sentry()

api_settings = get_api_settings()

app = FastAPI(title="AWS Instance Advisor API", version="1.0.0")

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


# Pluggable publish/subscribe backend for the SSE progress stream
# (app/api/event_bus.py).  Selected from the same REDIS_URL as the job store
# and passed to the store so every state transition is published from the
# existing update points — no parallel event system.
event_bus: JobEventBus = build_event_bus()
jobs: JobStoreBackend = build_job_store(publisher=event_bus)


def _client_id(request: Request) -> str:
    """Client identity used by the rate limiter and the stream limiter.

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

# Idle SSE streams wake up every this many seconds to (a) emit a comment
# heartbeat so proxies don't drop a quiet connection and (b) notice a client
# that has gone away.  15s is comfortably inside typical proxy idle timeouts.
SSE_HEARTBEAT_SECONDS: float = float(os.getenv("SSE_HEARTBEAT_SECONDS", "15"))

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

# Single shared executor for all background agent runs.
# Defined at module level so it is shared across requests and can be
# cleanly shut down on process exit.
_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=JOB_THREAD_POOL_SIZE,
    thread_name_prefix="agent-job",
)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _empty_state() -> AgentState:
    return {
        "requirements": UserRequirements(),
        "latest_user_message": None,
        "next_question": None,
        "pending_field": None,
        "repo_analysis": None,
        "repo_analysis_note": None,
        "technical_needs": None,
        "instance_candidates": None,
        "database_candidates": None,
        "cache_candidates": None,
        "recommendation": None,
        "system_design_recommendation": None,
        "terraform_files": None,
        "consensus_requested": False,
    }


def _run_graph_with_streaming(
    job_id: str,
    state: AgentState,
    collecting: bool = False,
) -> AgentState:
    """
    Run one graph pass using .stream() so we surface per-node stage
    labels to the job. Returns the final state after the full pass.

    Sets the thread-local retry context var so that invoke_structured
    calls made from any node in this pass automatically update
    job.retry_info without requiring any changes to node signatures.
    The context var is cleared after the pass completes.
    """
    from app.llm.retry import _retry_context

    def _retry_cb(attempt: int, max_attempts: int) -> None:
        jobs.update_retry_info(
            job_id,
            f"Retrying after rate limit (attempt {attempt} of {max_attempts})",
        )

    def _clear_retry_cb(attempt: int, max_attempts: int) -> None:  # noqa: ARG001
        # Sentinel: called with attempt=0 to signal "clear".
        jobs.update_retry_info(job_id, None)

    token = _retry_context.set(_retry_cb)
    try:
        graph = build_graph()
        final_state: AgentState = state

        for chunk in graph.stream(state):
            node_name = next(iter(chunk.keys()))
            stage_label = label_for_node(node_name)
            jobs.update_stage(job_id, stage_label)
            final_state = chunk[node_name]
            jobs.update_state(job_id, final_state)
            # Clear retry_info after each node completes successfully.
            jobs.update_retry_info(job_id, None)
    finally:
        _retry_context.reset(token)

    return final_state


def _graph_loop_sync(job_id: str, initial_state: AgentState) -> None:
    """
    Synchronous (thread-bound) driver that mirrors the CLI loop in
    app/main.py but writes progress into the shared JobStore.

    Runs passes of graph.stream(state) until either a final
    recommendation is produced or the agent asks a follow-up question.
    On any unhandled exception the job is marked errored.

    This function is submitted to _executor and monitored by
    _submit_with_timeout, which enforces JOB_TIMEOUT_SECONDS as an
    independent wall-clock safety net.
    """
    state = initial_state
    job_start = time.monotonic()
    try:
        while True:
            state = _run_graph_with_streaming(job_id, state, collecting=True)

            if (
                state.get("system_design_recommendation") is not None
                or state.get("recommendation") is not None
            ):
                final = _serialize_result(state)
                jobs.update_status(job_id, "done", result=final)
                _record_completed_run(job_id, state, job_start)
                return

            if state.get("next_question"):
                jobs.update_status(
                    job_id,
                    "awaiting_input",
                    next_question=state["next_question"],
                )
                return

            jobs.update_status(
                job_id,
                "error",
                error="No recommendation or follow-up question was produced.",
            )
            return

    except Exception as exc:
        jobs.update_status(job_id, "error", error=f"{type(exc).__name__}: {exc}")
        _capture_exception(exc)


def _resume_with_answer_sync(job_id: str, answer: str) -> None:
    """Resume a job in awaiting_input status after the user replies."""
    job = jobs.get(job_id)
    if job is None:
        return
    state = job.state
    state["latest_user_message"] = answer
    jobs.update_status(job_id, "running")
    job_start = time.monotonic()
    try:
        while True:
            state = _run_graph_with_streaming(job_id, state, collecting=True)

            if (
                state.get("system_design_recommendation") is not None
                or state.get("recommendation") is not None
            ):
                final = _serialize_result(state)
                jobs.update_status(job_id, "done", result=final)
                _record_completed_run(job_id, state, job_start)
                return

            if state.get("next_question"):
                jobs.update_status(
                    job_id,
                    "awaiting_input",
                    next_question=state["next_question"],
                )
                return

            jobs.update_status(
                job_id,
                "error",
                error="No recommendation or follow-up question was produced.",
            )
            return

    except Exception as exc:
        jobs.update_status(job_id, "error", error=f"{type(exc).__name__}: {exc}")
        _capture_exception(exc)


def _submit_with_timeout(fn, *args) -> None:
    """
    Submit *fn(*args)* to the shared executor and watch it with a
    daemon thread that enforces JOB_TIMEOUT_SECONDS.

    If the future does not complete in time, the job is marked as
    "error" with a clear timeout message.  The underlying thread
    continues running until it naturally exits (Python threads cannot
    be forcibly killed), but the job slot is freed from the caller's
    perspective and the executor queue is unblocked.

    The job_id is always the first positional argument by convention.
    """
    job_id: str = args[0]
    future = _executor.submit(fn, *args)

    def _watchdog() -> None:
        try:
            future.result(timeout=JOB_TIMEOUT_SECONDS)
        except concurrent.futures.TimeoutError:
            timeout_message = (
                f"Job timed out after {JOB_TIMEOUT_SECONDS:.0f}s — "
                "the agent took too long to respond. Please try again."
            )
            jobs.update_status(job_id, "error", error=timeout_message)
            # Job timeouts are swallowed here (the job is marked errored, no
            # exception propagates to FastAPI), so report explicitly.
            _capture_message(f"Job {job_id} timed out: {timeout_message}")
        except Exception:
            # The underlying fn already wrote its own error via jobs.update_status;
            # nothing to do here — exceptions from the future are already handled
            # inside _graph_loop_sync / _resume_with_answer_sync.
            pass

    import threading
    threading.Thread(target=_watchdog, daemon=True, name=f"watchdog-{job_id}").start()


def _record_completed_run(
    job_id: str,
    state: AgentState,
    job_start: float,
) -> None:
    """
    Fire-and-forget observability record for a successfully completed job.
    Extracts grounding status and cost from the final state and calls
    persist_run, which logs to stdout and optionally writes to the DB.
    """
    try:
        from app.observability import persist_run
        from app.config import get_llm_settings

        total_latency_s = time.monotonic() - job_start

        # Model name from config — this is the model that produced the run.
        try:
            model_used = get_llm_settings().model_name
        except Exception:
            model_used = None

        # Retry count: read from the job's current retry_info string.
        # retry_info is None (success) or a string like "Retrying … (attempt N of M)".
        # We track the highest attempt number seen; for a clean run it's 0.
        job = jobs.get(job_id)
        retry_count = 0
        if job is not None and job.retry_info:
            import re
            m = re.search(r"attempt (\d+)", job.retry_info)
            if m:
                retry_count = int(m.group(1))

        # Grounding result and cost from the recommendation.
        grounding_passed: bool | None = None
        cost_low: float | None = None
        cost_high: float | None = None

        sdr = state.get("system_design_recommendation")
        if sdr is not None:
            if hasattr(sdr, "grounding_passed"):
                grounding_passed = sdr.grounding_passed
            cost = getattr(sdr, "estimated_cost", None)
            if cost is not None:
                cost_low = getattr(cost, "total_monthly_low", None)
                cost_high = getattr(cost, "total_monthly_high", None)

        recommendation_snapshot = None
        if sdr is not None:
            cache_engine = getattr(getattr(sdr, "cache", None), "engine", None)
            technical_needs = state.get("technical_needs")
            recommendation_snapshot = {
                "compute_instance": getattr(getattr(sdr, "compute", None), "recommended_instance", None),
                "compute_monthly": getattr(cost, "compute_monthly_low", None) if cost is not None else None,
                "database_instance": getattr(getattr(sdr, "database", None), "recommended_instance", None),
                "database_engine": getattr(getattr(sdr, "database", None), "engine_suggestion", None),
                "database_monthly": getattr(cost, "database_monthly", None) if cost is not None else None,
                "cache_instance": getattr(getattr(sdr, "cache", None), "recommended_instance", None),
                "cache_engine": getattr(cache_engine, "value", cache_engine),
                "cache_monthly": getattr(cost, "cache_monthly", None) if cost is not None else None,
                "load_balancer_type": getattr(getattr(sdr, "load_balancer", None), "load_balancer_type", None),
                "min_instances": getattr(technical_needs, "min_instances", None),
                "max_instances": getattr(technical_needs, "max_instances", None),
            }

        persist_run(
            job_id=job_id,
            total_latency_s=total_latency_s,
            model_used=model_used,
            retry_count=retry_count,
            grounding_passed=grounding_passed,
            estimated_cost_low=cost_low,
            estimated_cost_high=cost_high,
            recommendation_snapshot=recommendation_snapshot,
        )
    except Exception as exc:
        # Observability must never crash the response path.
        import logging
        logging.getLogger(__name__).warning(
            "Observability record failed for job %s: %s", job_id, exc
        )


def _serialize_result(state: AgentState) -> dict[str, Any]:
    rec = state.get("system_design_recommendation")
    v1_rec = state.get("recommendation")
    tf_files = state.get("terraform_files")
    tn = state.get("technical_needs")
    requirements = state.get("requirements")
    candidates = state.get("instance_candidates")
    result: dict[str, Any] = {}
    if rec is not None:
        if isinstance(rec, SystemDesignRecommendation):
            result["system_design_recommendation"] = rec.model_dump(mode="json")
        else:
            result["system_design_recommendation"] = rec
    if v1_rec is not None:
        if hasattr(v1_rec, "model_dump"):
            result["recommendation"] = v1_rec.model_dump(mode="json")
        else:
            result["recommendation"] = v1_rec
    if tf_files is not None:
        result["terraform_files"] = tf_files
    # Include technical_needs and instance_candidates so the frontend can
    # render ScalingRangeBar and CandidateLandscape from real data.
    if tn is not None:
        if hasattr(tn, "model_dump"):
            result["technical_needs"] = tn.model_dump(mode="json")
        else:
            result["technical_needs"] = tn
    if requirements is not None:
        if hasattr(requirements, "model_dump"):
            result["user_requirements"] = requirements.model_dump(mode="json")
        else:
            result["user_requirements"] = requirements
    if candidates:
        result["instance_candidates"] = [
            c.model_dump(mode="json") if hasattr(c, "model_dump") else c
            for c in candidates
        ]
    return result


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
# ---------------------------------------------------------------------------


@app.get("/api/health")
def health() -> dict[str, Any]:
    """Liveness probe. No LLM or live-data calls."""
    return {"status": "ok", "time": time.time()}


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
# Additive: the polling endpoint above keeps working unchanged.  This pushes
# the very same snapshots as they happen, from the state transitions that
# already exist (JobStoreBackend.update_stage / update_status /
# update_retry_info) — there is no parallel event system.
# ---------------------------------------------------------------------------

SSE_MEDIA_TYPE = "text/event-stream"
_HEARTBEAT_FRAME = ": keep-alive\n\n"


def _sse_frame(payload: dict[str, Any]) -> str:
    """Render one SSE data frame.

    ``json.dumps`` escapes newlines inside strings, so a payload is always a
    single ``data:`` line.  That matters: an unescaped newline would end the
    event early in every SSE client.
    """
    return f"data: {json.dumps(payload, separators=(',', ':'))}\n\n"


async def _sse_event_stream(
    request: Request,
    job_id: str,
    subscription: EventSubscription,
    client_id: str,
) -> AsyncIterator[str]:
    """Generator behind the SSE endpoint: current state, then live updates.

    Owns the subscription and the concurrency slot and releases both in
    ``finally``, which runs on the terminal event, on a detected client
    disconnect, and on task cancellation (how an ASGI server tears a stream
    down when the browser goes away).  That last case is the classic SSE
    leak — without it the backend keeps producing frames for nobody.
    """
    try:
        # The subscription is already active, so a transition landing between
        # this read and the first yield is queued rather than lost.
        job = await asyncio.to_thread(jobs.get, job_id)
        if job is None:
            # Only reachable if the job vanished between the route's 404
            # check and here (e.g. Redis TTL expiry).  Terminate, don't hang.
            yield _sse_frame(
                {
                    "job_id": job_id,
                    "status": "error",
                    "current_stage": "Unknown",
                    "error": f"Job {job_id} not found",
                }
            )
            return

        last_payload = _job_response(job)
        yield _sse_frame(last_payload)
        if last_payload.get("status") in TERMINAL_STATUSES:
            # Connected after the job finished: that snapshot *is* the final
            # event, so there is nothing left to wait for.
            return

        while True:
            event = await subscription.next_event(timeout=SSE_HEARTBEAT_SECONDS)
            if event is None:
                # Idle window: emit a heartbeat and use the wake-up to check
                # whether the client is still there.
                if subscription.closed or await request.is_disconnected():
                    break
                yield _HEARTBEAT_FRAME
                continue
            if event == last_payload:
                continue  # duplicate snapshot — nothing new to report
            last_payload = event
            yield _sse_frame(event)
            if event.get("status") in TERMINAL_STATUSES:
                break  # terminal: close server-side, no further events exist
    finally:
        subscription.close()
        stream_limiter.release(client_id)


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
