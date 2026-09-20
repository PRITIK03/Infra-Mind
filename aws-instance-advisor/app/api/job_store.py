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
Only the fields already surfaced through the job API response
(``job_id``, ``status``, ``current_stage``, ``next_question``, ``result``,
``error``, ``retry_info``, ``created_at``) — serialized with Pydantic
``model_dump_json()`` / ``model_validate_json()``, never hand-built dicts.
The full internal ``AgentState`` (live candidate lists, Pydantic objects)
is intentionally NOT persisted: it is process-local working memory for
the executing graph, wasteful to store, and redundant with the API
response surface.  ``update_state`` therefore only lifts
``next_question`` out of the state; nothing else is written.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from pydantic import BaseModel

from app.agent.state import AgentState

logger = logging.getLogger(__name__)


JobStatus = Literal[
    "collecting",
    "awaiting_input",
    "running",
    "done",
    "error",
]


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
    ) -> None: ...

    def update_state(self, job_id: str, state: Any) -> None: ...

    def update_retry_info(self, job_id: str, retry_info: str | None) -> None: ...


class JobRecord(BaseModel):
    """Serializable projection of :class:`Job` — the API response surface.

    Exactly the fields ``_job_response()`` exposes, so a Redis round-trip
    never loses anything a polling client could observe.
    """

    job_id: str
    status: JobStatus
    current_stage: str
    next_question: str | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
    retry_info: str | None = None
    created_at: float


class InMemoryJobStore:
    """Thread-safe in-memory dict of job_id -> Job (original behavior)."""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def put(self, job: Job) -> None:
        with self._lock:
            self._jobs[job.job_id] = job

    def update_stage(self, job_id: str, stage: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                job.current_stage = stage

    def update_status(
        self,
        job_id: str,
        status: JobStatus,
        *,
        next_question: str | None = None,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            job.status = status
            if next_question is not None:
                job.next_question = next_question
            if result is not None:
                job.result = result
            if error is not None:
                job.error = error

    def update_state(self, job_id: str, state: Any) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                job.state = state
                if state.get("next_question"):
                    job.next_question = state["next_question"]

    def update_retry_info(self, job_id: str, retry_info: str | None) -> None:
        """Set or clear the real-time retry progress message."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                job.retry_info = retry_info




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
    ) -> None:
        self._redis = redis_client
        self._ttl_seconds = ttl_seconds
        self._key_prefix = key_prefix
        self._states: dict[str, Any] = {}
        self._states_lock = threading.Lock()

    @classmethod
    def from_url(
        cls,
        redis_url: str,
        *,
        ttl_seconds: int = 86_400,
        key_prefix: str = "inframind:job:",
    ) -> "RedisJobStore":
        """Build a store from a Redis URL using a shared connection pool."""
        import redis

        pool = redis.ConnectionPool.from_url(redis_url)
        return cls(
            redis.Redis(connection_pool=pool),
            ttl_seconds=ttl_seconds,
            key_prefix=key_prefix,
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
        )

    def _set_state(self, job_id: str, state: Any) -> None:
        with self._states_lock:
            self._states[job_id] = state

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
        record = self._load_record(job_id)
        if record is None:
            return
        record.current_stage = stage
        self._save_record(record)

    def update_status(
        self,
        job_id: str,
        status: JobStatus,
        *,
        next_question: str | None = None,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        record = self._load_record(job_id)
        if record is None:
            return
        record.status = status
        if next_question is not None:
            record.next_question = next_question
        if result is not None:
            record.result = result
        if error is not None:
            record.error = error
        self._save_record(record)

    def update_state(self, job_id: str, state: Any) -> None:
        self._set_state(job_id, state)
        next_question = state.get("next_question") if hasattr(state, "get") else None
        if next_question:
            record = self._load_record(job_id)
            if record is not None:
                record.next_question = next_question
                self._save_record(record)

    def update_retry_info(self, job_id: str, retry_info: str | None) -> None:
        """Set or clear the real-time retry progress message."""
        record = self._load_record(job_id)
        if record is None:
            return
        record.retry_info = retry_info
        self._save_record(record)



def build_job_store() -> JobStoreBackend:
    """Select the job-store backend from configuration.

    Uses the Redis-backed store when REDIS_URL is configured, otherwise
    the process-local in-memory store.  If the Redis package is missing
    or the initial connection fails, the app logs a warning and falls
    back to in-memory — Redis is an upgrade, never a hard requirement.
    """
    from app.config import get_redis_settings

    settings = get_redis_settings()
    if settings.redis_url is None:
        return InMemoryJobStore()

    try:
        store = RedisJobStore.from_url(settings.redis_url)
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
        return InMemoryJobStore()

