"""
Pluggable job-store backends for the FastAPI job layer.

Two implementations satisfy the same interface:

- ``InMemoryJobStore`` — the original process-local dict store (default).
  Zero dependencies; appropriate for single-instance dev/demo use.
- ``RedisJobStore`` — persists job records in Redis with a TTL so jobs
  survive restarts and are shared across multiple backend instances.

Selection happens once at startup in :func:`build_job_store` based on
``get_redis_settings()`` — when REDIS_URL is unset the app behaves exactly
as it did before, matching the graceful-optional pattern used for Tavily,
GitHub MCP, and DATABASE_URL.  ``app/api/main.py`` consumes only the
:class:`JobStoreBackend` protocol and needs no branching of its own.

What is persisted
-----------------
The job API response fields and internal share metadata are serialized with
Pydantic. Share metadata stays out of the polling and SSE projection.
The full internal ``AgentState`` (live candidate lists, Pydantic objects)
is intentionally NOT persisted: it is process-local working memory for
the executing graph, wasteful to store, and redundant with the API
response surface.  ``update_state`` therefore only lifts
``next_question`` out of the state; nothing else is written.

Real-time progress streaming
----------------------------
Both stores accept an optional ``publisher`` (see ``app/api/event_bus.py``)
and publish the job's API snapshot (:func:`job_snapshot`) after every
``update_stage`` / ``update_status`` / ``update_retry_info`` call — i.e. from
the existing state-transition points, so there is no parallel event system to
keep in sync.  The published document is exactly the polling response
projection, so the SSE stream and ``GET /api/recommend/{job_id}`` can never
disagree, and a client can render both with one code path.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from pydantic import BaseModel

from app.agent.state import AgentState
from app.api.event_bus import JobEventBus
from app.models.repository import RepositoryProgress

logger = logging.getLogger(__name__)


JobStatus = Literal[
    "collecting",
    "awaiting_input",
    "running",
    "done",
    "error",
]


class FollowupExchange(BaseModel):
    """A single user follow-up question and the agent's grounded answer."""

    question: str
    answer: str
    timestamp: str


@dataclass
class Job:
    """Tracks a single agent execution across its full lifecycle."""

    job_id: str
    status: JobStatus
    current_stage: str
    state: AgentState
    next_question: str | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
    # Set while the LLM layer is retrying after a rate-limit response,
    # e.g. "Retrying after rate limit (attempt 2 of 4)".  Cleared back
    # to None when the retry succeeds so the UI can stop showing it.
    retry_info: str | None = None
    created_at: float = field(default_factory=lambda: __import__("time").time())
    followup_history: list[FollowupExchange] = field(default_factory=list)
    repository: RepositoryProgress | None = None
    # A repo job and its optional public report use independent IDs.
    share_id: str | None = None
    share_only: bool = False


class JobStoreBackend(Protocol):
    """Interface shared by the in-memory and Redis job stores.

    ``app/api/main.py`` consumes only these methods, so the two
    implementations are interchangeable without any branching logic
    in the route handlers or worker threads.
    """

    def get(self, job_id: str) -> Job | None: ...

    def put(self, job: Job) -> None: ...

    def update_stage(self, job_id: str, stage: str) -> None: ...

    def update_status(
        self,
        job_id: str,
        status: JobStatus,
        *,
        next_question: str | None = None,
        result: dict[str, Any] | None = None,
        error: str | None = None,
        only_if: tuple[JobStatus, ...] | None = None,
    ) -> bool: ...

    def update_state(self, job_id: str, state: Any) -> None: ...

    def update_repository(self, job_id: str, progress: RepositoryProgress, stage: str | None = None) -> None: ...

    def update_retry_info(self, job_id: str, retry_info: str | None) -> None: ...

    def add_followup(self, job_id: str, exchange: FollowupExchange) -> None: ...

    def ping(self) -> None:
        """Cheap liveness check on the backend's own connection.

        In-memory always succeeds; the Redis implementation performs one
        lightweight ``PING``.  Used by the readiness endpoint so health
        reporting depends on the store's *public* contract rather than a
        private attribute — a future internal refactor can't silently
        break ``GET /api/health/ready``.
        """
        ...


class JobRecord(BaseModel):
    """Serializable job snapshot with internal share metadata."""

    job_id: str
    status: JobStatus
    current_stage: str
    next_question: str | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
    retry_info: str | None = None
    created_at: float
    followup_history: list[FollowupExchange] = []
    repository: RepositoryProgress | None = None
    share_id: str | None = None
    share_only: bool = False


def job_snapshot(
    *,
    job_id: str,
    status: JobStatus,
    current_stage: str,
    created_at: float,
    next_question: str | None = None,
    result: dict[str, Any] | None = None,
    error: str | None = None,
    retry_info: str | None = None,
    followup_history: list[dict[str, Any]] | None = None,
    repository: RepositoryProgress | None = None,
) -> dict[str, Any]:
    """Single source of truth for a job's JSON projection.

    Both the polling endpoint (``GET /api/recommend/{job_id}``) and every
    real-time event published by the stores build their document here, so a
    streaming client and a polling client can never disagree about the
    shape of a job's state — and a client can render both with one code
    path.  Field-visibility rules are deliberately the pre-existing ones:
    a result is only exposed once the job is ``done``, an error only once it
    is ``error``, and a question only while awaiting input.
    """
    snapshot: dict[str, Any] = {
        "job_id": job_id,
        "status": status,
        "current_stage": current_stage,
        "created_at": created_at,
    }
    if retry_info is not None:
        snapshot["retry_info"] = retry_info
    if status == "awaiting_input" and next_question is not None:
        snapshot["next_question"] = next_question
    if status == "done" and result is not None:
        snapshot["result"] = result
    if status == "error" and error is not None:
        snapshot["error"] = error
    if followup_history:
        snapshot["followup_history"] = followup_history
    if repository is not None:
        snapshot["repository"] = repository.model_dump(exclude_none=True)
    return snapshot


def job_snapshot_from_job(job: Job) -> dict[str, Any]:
    """Project a live :class:`Job` (in-memory store representation)."""
    return job_snapshot(
        job_id=job.job_id,
        status=job.status,
        current_stage=job.current_stage,
        created_at=job.created_at,
        next_question=job.next_question,
        result=job.result,
        error=job.error,
        retry_info=job.retry_info,
        followup_history=[exchange.model_dump() for exchange in job.followup_history],
        repository=job.repository,
    )


def job_snapshot_from_record(record: JobRecord) -> dict[str, Any]:
    """Project a :class:`JobRecord` (Redis store representation)."""
    return job_snapshot(
        job_id=record.job_id,
        status=record.status,
        current_stage=record.current_stage,
        created_at=record.created_at,
        next_question=record.next_question,
        result=record.result,
        error=record.error,
        retry_info=record.retry_info,
        followup_history=[exchange.model_dump() for exchange in record.followup_history],
        repository=record.repository,
    )


class InMemoryJobStore:
    """Thread-safe in-memory dict of job_id -> Job (original behavior).

    An optional ``publisher`` receives the job's API snapshot after every
    state transition, which is what feeds the SSE progress stream.  With no
    publisher configured the store behaves exactly as it did before the
    streaming feature existed (publish becomes a no-op).
    """

    def __init__(self, publisher: JobEventBus | None = None) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._publisher = publisher

    def _publish(self, job_id: str, snapshot: dict[str, Any]) -> None:
        """Publish one state snapshot, outside the store lock.

        Streaming is best-effort: a bus failure must never break the job
        run that is producing the events, so it is logged and swallowed.
        """
        if self._publisher is None:
            return
        try:
            self._publisher.publish(job_id, snapshot)
        except Exception as exc:  # pragma: no cover - depends on transport
            logger.warning("Failed to publish job event for %s: %s", job_id, exc)

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def put(self, job: Job) -> None:
        with self._lock:
            self._jobs[job.job_id] = job

    def update_stage(self, job_id: str, stage: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status in ("error", "done"):
                return
            job.current_stage = stage
            snapshot = job_snapshot_from_job(job)
        self._publish(job_id, snapshot)

    def update_repository(self, job_id: str, progress: RepositoryProgress, stage: str | None = None) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status in ("error", "done"):
                return
            job.repository = progress
            if stage is not None:
                job.current_stage = stage
            snapshot = job_snapshot_from_job(job)
        self._publish(job_id, snapshot)

    def update_status(
        self,
        job_id: str,
        status: JobStatus,
        *,
        next_question: str | None = None,
        result: dict[str, Any] | None = None,
        error: str | None = None,
        only_if: tuple[JobStatus, ...] | None = None,
    ) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status in ("error", "done") or (only_if and job.status not in only_if):
                return False
            job.status = status
            if next_question is not None:
                job.next_question = next_question
            if result is not None:
                job.result = result
            if error is not None:
                job.error = error
            snapshot = job_snapshot_from_job(job)
        self._publish(job_id, snapshot)
        return True

    def update_state(self, job_id: str, state: Any) -> None:
        # Deliberately does not publish: `next_question` (the only part of the
        # state on the API surface) is always accompanied by an
        # update_status("awaiting_input"), so publishing here would only
        # duplicate that event.
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None and job.status not in ("error", "done"):
                job.state = state
                if state.get("next_question"):
                    job.next_question = state["next_question"]

    def update_retry_info(self, job_id: str, retry_info: str | None) -> None:
        """Set or clear the real-time retry progress message."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status == "error":
                return
            job.retry_info = retry_info
            snapshot = job_snapshot_from_job(job)
        self._publish(job_id, snapshot)

    def add_followup(self, job_id: str, exchange: FollowupExchange) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                job.followup_history.append(exchange)

    def ping(self) -> None:
        """In-memory store: nothing external to reach, always healthy."""
        return None





class RedisJobStore:
    """Redis-backed job store with TTL-based expiry.

    One JSON document per job under ``{key_prefix}{job_id}``, written via
    ``SET key value EX ttl`` on every mutation so the expiry is refreshed
    from the last update and Redis never grows unbounded.

    Uses the synchronous ``redis`` package (redis-py) with a connection
    pool — consistent with the sync-SQLAlchemy-in-a-blended-sync/async-app
    pattern already used for ``observability.py``.  Callers running on the
    event loop wrap reads in ``asyncio.to_thread`` so a Redis round-trip
    never blocks concurrent polling.

    Per-process runtime state (the live AgentState and jobs created before
    the first read) is kept in a small process-local dict, preserving the
    in-memory store's semantics for the executing worker thread.
    """

    def __init__(
        self,
        redis_client: Any,
        *,
        ttl_seconds: int = 86_400,  # 24h
        key_prefix: str = "inframind:job:",
        publisher: JobEventBus | None = None,
    ) -> None:
        self._redis = redis_client
        self._ttl_seconds = ttl_seconds
        self._key_prefix = key_prefix
        self._states: dict[str, Any] = {}
        self._states_lock = threading.Lock()
        self._publisher = publisher

    @classmethod
    def from_url(
        cls,
        redis_url: str,
        *,
        ttl_seconds: int = 86_400,
        key_prefix: str = "inframind:job:",
        publisher: JobEventBus | None = None,
    ) -> "RedisJobStore":
        """Build a store from a Redis URL using a shared connection pool."""
        import redis

        pool = redis.ConnectionPool.from_url(redis_url)
        return cls(
            redis.Redis(connection_pool=pool),
            ttl_seconds=ttl_seconds,
            key_prefix=key_prefix,
            publisher=publisher,
        )

    # -- internal helpers ---------------------------------------------------

    def _key(self, job_id: str) -> str:
        return f"{self._key_prefix}{job_id}"

    def _save_record(self, record: JobRecord) -> None:
        self._redis.set(
            self._key(record.job_id),
            record.model_dump_json(),
            ex=self._ttl_seconds,
        )

    def _load_record(self, job_id: str) -> JobRecord | None:
        raw = self._redis.get(self._key(job_id))
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return JobRecord.model_validate_json(raw)

    def _mutate_record(
        self, job_id: str, update: Callable[[JobRecord], bool], *, publish: bool = True,
    ) -> bool:
        # A timed-out worker and a polling replica can race. Retry the
        # update against the current record if another writer wins.
        from redis.exceptions import WatchError

        key = self._key(job_id)
        with self._redis.pipeline() as pipe:
            for _ in range(8):
                try:
                    pipe.watch(key)
                    raw = pipe.get(key)
                    if raw is None:
                        return False
                    record = JobRecord.model_validate_json(raw)
                    if not update(record):
                        return False
                    pipe.multi()
                    pipe.set(key, record.model_dump_json(), ex=self._ttl_seconds)
                    pipe.execute()
                    break
                except WatchError:
                    continue
            else:
                raise WatchError("Job record changed repeatedly")
        if publish:
            self._publish(job_id, record)
        return True

    def _record_to_job(self, record: JobRecord) -> Job:
        with self._states_lock:
            state = self._states.get(record.job_id, {})
        return Job(
            job_id=record.job_id,
            status=record.status,
            current_stage=record.current_stage,
            state=state,
            next_question=record.next_question,
            result=record.result,
            error=record.error,
            retry_info=record.retry_info,
            created_at=record.created_at,
            followup_history=list(record.followup_history),
            repository=record.repository,
            share_id=record.share_id,
            share_only=record.share_only,
        )

    @staticmethod
    def _record_from_job(job: Job) -> JobRecord:
        return JobRecord(
            job_id=job.job_id,
            status=job.status,
            current_stage=job.current_stage,
            next_question=job.next_question,
            result=job.result,
            error=job.error,
            retry_info=job.retry_info,
            created_at=job.created_at,
            followup_history=list(job.followup_history),
            repository=job.repository,
            share_id=job.share_id,
            share_only=job.share_only,
        )

    def _set_state(self, job_id: str, state: Any) -> None:
        with self._states_lock:
            self._states[job_id] = state

    def _publish(self, job_id: str, record: JobRecord) -> None:
        """Publish one state snapshot after a durable write.

        Streaming is best-effort: a Pub/Sub failure must never break the job
        run producing the events, so it is logged and swallowed.
        """
        if self._publisher is None:
            return
        try:
            self._publisher.publish(job_id, job_snapshot_from_record(record))
        except Exception as exc:  # pragma: no cover - depends on transport
            logger.warning("Failed to publish job event for %s: %s", job_id, exc)

    # -- JobStoreBackend interface ------------------------------------------

    def get(self, job_id: str) -> Job | None:
        record = self._load_record(job_id)
        if record is None:
            return None
        return self._record_to_job(record)

    def put(self, job: Job) -> None:
        self._set_state(job.job_id, job.state)
        self._save_record(self._record_from_job(job))

    def update_stage(self, job_id: str, stage: str) -> None:
        def update(record: JobRecord) -> bool:
            if record.status in ("error", "done"):
                return False
            record.current_stage = stage
            return True

        self._mutate_record(job_id, update)

    def update_repository(self, job_id: str, progress: RepositoryProgress, stage: str | None = None) -> None:
        def update(record: JobRecord) -> bool:
            if record.status in ("error", "done"):
                return False
            record.repository = progress
            if stage is not None:
                record.current_stage = stage
            return True

        self._mutate_record(job_id, update)

    def update_status(
        self,
        job_id: str,
        status: JobStatus,
        *,
        next_question: str | None = None,
        result: dict[str, Any] | None = None,
        error: str | None = None,
        only_if: tuple[JobStatus, ...] | None = None,
    ) -> bool:
        def update(record: JobRecord) -> bool:
            if record.status in ("error", "done") or (only_if and record.status not in only_if):
                return False
            record.status = status
            if next_question is not None:
                record.next_question = next_question
            if result is not None:
                record.result = result
            if error is not None:
                record.error = error
            return True

        return self._mutate_record(job_id, update)

    def update_state(self, job_id: str, state: Any) -> None:
        # Does not publish: `next_question` (the only state on the API
        # surface) always arrives with update_status("awaiting_input").
        self._set_state(job_id, state)
        next_question = state.get("next_question") if hasattr(state, "get") else None
        if next_question:
            def update(record: JobRecord) -> bool:
                if record.status in ("error", "done"):
                    return False
                record.next_question = next_question
                return True

            self._mutate_record(job_id, update, publish=False)

    def update_retry_info(self, job_id: str, retry_info: str | None) -> None:
        """Set or clear the real-time retry progress message."""
        def update(record: JobRecord) -> bool:
            if record.status == "error":
                return False
            record.retry_info = retry_info
            return True

        self._mutate_record(job_id, update)

    def add_followup(self, job_id: str, exchange: FollowupExchange) -> None:
        def update(record: JobRecord) -> bool:
            record.followup_history.append(exchange)
            return True

        self._mutate_record(job_id, update, publish=False)

    def ping(self) -> None:
        """One lightweight Redis PING; raises on an unreachable server."""
        self._redis.ping()



def build_job_store(publisher: JobEventBus | None = None) -> JobStoreBackend:
    """Select the job-store backend from configuration.

    Uses the Redis-backed store when REDIS_URL is configured, otherwise
    the process-local in-memory store.  If the Redis package is missing
    or the initial connection fails, the app logs a warning and falls
    back to in-memory — Redis is an upgrade, never a hard requirement.

    ``publisher`` is an optional event bus (see ``app/api/event_bus.py``)
    that receives the job's API snapshot after every state transition, which
    is what drives the SSE progress stream.  Omitting it keeps the store's
    pre-streaming behaviour exactly.
    """
    from app.config import get_redis_settings

    settings = get_redis_settings()
    if settings.redis_url is None:
        return InMemoryJobStore(publisher=publisher)

    try:
        store = RedisJobStore.from_url(settings.redis_url, publisher=publisher)
        # Fail fast at startup rather than on the first job write.
        store._redis.ping()
        logger.info("Job store: Redis-backed (REDIS_URL configured)")
        return store
    except Exception as exc:  # pragma: no cover - depends on local env
        logger.warning(
            "REDIS_URL is configured but Redis is unavailable (%s); "
            "falling back to the in-memory job store.",
            exc,
        )
        return InMemoryJobStore(publisher=publisher)

