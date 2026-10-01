"""
Background job execution: graph runs, the wall-clock timeout watchdog, and
run-history recording.

Extracted from ``app/api/main.py`` (Part A modularization) — ``main.py``
keeps the routes and calls into this module.  ``main.py`` also re-exports
these names, so existing imports (``from app.api.main import
_submit_with_timeout``) and the test suite keep working unchanged.

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

Wall-clock job timeout
----------------------
Each background job is submitted via executor.submit() and tracked with
Future.result(timeout=JOB_TIMEOUT_SECONDS).  A concurrent.futures.TimeoutError
marks the job as "error" with a clear message — this is an independent
safety net that fires regardless of what's happening inside the graph,
protecting against any future hang scenario, not just rate-limit loops.

Both constants are overridable via environment variables for larger hosts.
"""

from __future__ import annotations

import concurrent.futures
import os
import threading
import time
from typing import Any

from app.agent.graph import build_graph
from app.agent.state import AgentState
from app.api.error_reporting import capture_exception, capture_message
from app.api.jobs import label_for_node
from app.api.runtime import jobs
from app.api.shutdown import coordinator as shutdown_coordinator
from app.logging_config import bind_job_id
from app.models.schemas import SystemDesignRecommendation, UserRequirements

# Max simultaneous agent-run threads. Conservative for small cloud hosts
# (Render free/starter, Railway, Fly.io shared-cpu-1x).
JOB_THREAD_POOL_SIZE: int = int(os.getenv("JOB_THREAD_POOL_SIZE", "8"))

# Hard wall-clock limit for a single complete agent run, in seconds.
# A full run under free-tier rate limiting can legitimately take 3-4 min;
# 10 min is generous enough for paid keys while bounding any true hang.
JOB_TIMEOUT_SECONDS: float = float(os.getenv("JOB_TIMEOUT_SECONDS", "600"))


# Single shared executor for all background agent runs.
# Defined at module level so it is shared across requests and can be
# cleanly shut down on process exit.
_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=JOB_THREAD_POOL_SIZE,
    thread_name_prefix="agent-job",
)


def empty_state() -> AgentState:
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


def run_graph_with_streaming(
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


def _drive_job(job_id: str, state: AgentState, job_start: float) -> None:
    """Run graph passes until the agent finishes or asks a question.

    Shared by the initial run and the resume-after-answer path (which differ
    only in how they seed the state and status before calling this).  On any
    unhandled exception the job is marked errored — the original behavior.
    """
    try:
        while True:
            state = run_graph_with_streaming(job_id, state, collecting=True)

            if (
                state.get("system_design_recommendation") is not None
                or state.get("recommendation") is not None
            ):
                final = serialize_result(state)
                jobs.update_status(job_id, "done", result=final)
                record_completed_run(job_id, state, job_start)
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
        capture_exception(exc)


def graph_loop_sync(job_id: str, initial_state: AgentState) -> None:
    """
    Synchronous (thread-bound) driver that mirrors the CLI loop in
    app/main.py but writes progress into the shared JobStore.

    This function is submitted to _executor and monitored by
    submit_with_timeout, which enforces JOB_TIMEOUT_SECONDS as an
    independent wall-clock safety net.
    """
    job_start = time.monotonic()
    with bind_job_id(job_id):
        shutdown_coordinator.job_started()
        try:
            _drive_job(job_id, initial_state, job_start)
        finally:
            shutdown_coordinator.job_finished()


def resume_with_answer_sync(job_id: str, answer: str) -> None:
    """Resume a job in awaiting_input status after the user replies."""
    job = jobs.get(job_id)
    if job is None:
        return
    state = job.state
    state["latest_user_message"] = answer
    jobs.update_status(job_id, "running")
    job_start = time.monotonic()
    with bind_job_id(job_id):
        shutdown_coordinator.job_started()
        try:
            _drive_job(job_id, state, job_start)
        finally:
            shutdown_coordinator.job_finished()


def submit_with_timeout(fn, *args) -> None:
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
            capture_message(f"Job {job_id} timed out: {timeout_message}")
        except Exception:
            # The underlying fn already wrote its own error via jobs.update_status;
            # nothing to do here — exceptions from the future are already handled
            # inside graph_loop_sync / resume_with_answer_sync.
            pass

    threading.Thread(target=_watchdog, daemon=True, name=f"watchdog-{job_id}").start()


def record_completed_run(
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


def serialize_result(state: AgentState) -> dict[str, Any]:
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


__all__ = [
    "JOB_THREAD_POOL_SIZE",
    "JOB_TIMEOUT_SECONDS",
    "empty_state",
    "graph_loop_sync",
    "record_completed_run",
    "resume_with_answer_sync",
    "run_graph_with_streaming",
    "serialize_result",
    "submit_with_timeout",
]


