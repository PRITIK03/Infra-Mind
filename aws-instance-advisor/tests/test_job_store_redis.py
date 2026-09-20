"""
Tests for the pluggable job-store backends (app/api/job_store.py).

Covers:
  - RedisJobStore: persist/retrieve via fakeredis (no real Redis server),
    TTL set on every write, stage/status/retry_info/state updates matching
    the in-memory store's semantics.
  - build_job_store: in-memory default when REDIS_URL is unset, Redis
    selection when configured, and graceful fallback when Redis is
    unreachable.
  - The module-level ``jobs`` store in app/api/main.py remains the
    in-memory backend when REDIS_URL is unset (default test env).

No real Redis connection or LLM/live-data calls anywhere in this file.
"""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import patch

import fakeredis
import pytest

os.environ.setdefault("CORS_ALLOWED_ORIGIN", "http://localhost:3000")
os.environ.setdefault("PORT", "8000")

from app.api.job_store import (
    InMemoryJobStore,
    Job,
    JobRecord,
    RedisJobStore,
    build_job_store,
)
from app.models.schemas import UserRequirements

TTL_SECONDS = 86_400  # 24h default


def _make_state(next_question: str | None = None) -> dict[str, Any]:
    return {
        "requirements": UserRequirements(),
        "latest_user_message": "test message",
        "next_question": next_question,
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
    }


def _make_job(job_id: str = "redis-test-001") -> Job:
    return Job(
        job_id=job_id,
        status="collecting",
        current_stage="Initializing",
        state=_make_state(),
    )


@pytest.fixture()
def redis_store() -> RedisJobStore:
    """A RedisJobStore backed by an in-memory fakeredis server."""
    fake = fakeredis.FakeStrictRedis()
    return RedisJobStore(fake, ttl_seconds=TTL_SECONDS)

# ---------------------------------------------------------------------------
# RedisJobStore: persist + retrieve
# ---------------------------------------------------------------------------


def test_redis_store_put_and_get_round_trip(redis_store: RedisJobStore):
    job = _make_job()
    redis_store.put(job)

    loaded = redis_store.get(job.job_id)
    assert loaded is not None
    assert loaded.job_id == job.job_id
    assert loaded.status == "collecting"
    assert loaded.current_stage == "Initializing"
    assert loaded.next_question is None
    assert loaded.result is None
    assert loaded.error is None
    assert loaded.retry_info is None
    assert loaded.created_at == pytest.approx(job.created_at)


def test_redis_store_get_missing_returns_none(redis_store: RedisJobStore):
    assert redis_store.get("no-such-job") is None


def test_redis_store_persists_full_response_surface(redis_store: RedisJobStore):
    """Every field the API response exposes must survive the round trip."""
    job = _make_job()
    redis_store.put(job)
    redis_store.update_status(
        job.job_id,
        "done",
        result={"system_design_recommendation": {"compute": {"instance": "t3.medium"}}},
    )
    redis_store.update_retry_info(job.job_id, "Retrying after rate limit (attempt 2 of 4)")

    loaded = redis_store.get(job.job_id)
    assert loaded is not None
    assert loaded.status == "done"
    assert loaded.result == {
        "system_design_recommendation": {"compute": {"instance": "t3.medium"}}
    }
    assert loaded.retry_info == "Retrying after rate limit (attempt 2 of 4)"


# ---------------------------------------------------------------------------
# TTL-based expiry
# ---------------------------------------------------------------------------


def test_redis_store_sets_ttl_on_put(redis_store: RedisJobStore):
    job = _make_job("ttl-test-put")
    redis_store.put(job)
    ttl = redis_store._redis.ttl(redis_store._key(job.job_id))
    assert 0 < ttl <= TTL_SECONDS


def test_redis_store_refreshes_ttl_on_updates(redis_store: RedisJobStore):
    job = _make_job("ttl-test-update")
    redis_store.put(job)
    # Shrink the TTL artificially, then confirm an update restores it.
    redis_store._redis.expire(redis_store._key(job.job_id), 10)
    redis_store.update_stage(job.job_id, "Researching compute options")
    ttl = redis_store._redis.ttl(redis_store._key(job.job_id))
    assert 10 < ttl <= TTL_SECONDS


# ---------------------------------------------------------------------------
# Updates match in-memory semantics
# ---------------------------------------------------------------------------


def test_redis_store_update_stage(redis_store: RedisJobStore):
    job = _make_job("stage-test")
    redis_store.put(job)
    redis_store.update_stage(job.job_id, "Building final recommendation")
    assert redis_store.get(job.job_id).current_stage == "Building final recommendation"


def test_redis_store_update_stage_missing_job_is_noop(redis_store: RedisJobStore):
    redis_store.update_stage("missing", "x")  # must not raise
    assert redis_store.get("missing") is None


def test_redis_store_update_status_partial_fields(redis_store: RedisJobStore):
    """Only non-None kwargs are written — same merge semantics as in-memory."""
    job = _make_job("status-test")
    redis_store.put(job)

    redis_store.update_status(job.job_id, "awaiting_input", next_question="How many users?")
    loaded = redis_store.get(job.job_id)
    assert loaded.status == "awaiting_input"
    assert loaded.next_question == "How many users?"
    assert loaded.error is None

    # A later status update without next_question must not clear it.
    redis_store.update_status(job.job_id, "running")
    loaded = redis_store.get(job.job_id)
    assert loaded.status == "running"
    assert loaded.next_question == "How many users?"


def test_redis_store_update_status_error(redis_store: RedisJobStore):
    job = _make_job("error-test")
    redis_store.put(job)
    redis_store.update_status(job.job_id, "error", error="RuntimeError: boom")
    loaded = redis_store.get(job.job_id)
    assert loaded.status == "error"
    assert loaded.error == "RuntimeError: boom"


def test_redis_store_update_retry_info_set_and_clear(redis_store: RedisJobStore):
    job = _make_job("retry-test")
    redis_store.put(job)

    redis_store.update_retry_info(job.job_id, "Retrying after rate limit (attempt 1 of 4)")
    assert (
        redis_store.get(job.job_id).retry_info
        == "Retrying after rate limit (attempt 1 of 4)"
    )

    redis_store.update_retry_info(job.job_id, None)
    assert redis_store.get(job.job_id).retry_info is None


def test_redis_store_update_state_lifts_next_question(redis_store: RedisJobStore):
    """update_state keeps the live state process-local but persists
    next_question so polling clients see it — same observable behavior
    as the in-memory store."""
    job = _make_job("state-test")
    redis_store.put(job)

    state = _make_state(next_question="What is your expected traffic?")
    redis_store.update_state(job.job_id, state)

    loaded = redis_store.get(job.job_id)
    assert loaded.next_question == "What is your expected traffic?"
    # The live state object is available in-process (for _resume_with_answer_sync).
    assert loaded.state is state


def test_redis_store_update_state_without_question_leaves_record(redis_store: RedisJobStore):
    job = _make_job("state-test-2")
    redis_store.put(job)
    redis_store.update_state(job.job_id, _make_state(next_question=None))
    assert redis_store.get(job.job_id).next_question is None


# ---------------------------------------------------------------------------
# Serialization uses Pydantic JSON round-trip (not hand-built dicts)
# ---------------------------------------------------------------------------


def test_redis_store_raw_value_is_pydantic_json(redis_store: RedisJobStore):
    job = _make_job("json-test")
    redis_store.put(job)
    raw = redis_store._redis.get(redis_store._key(job.job_id))
    record = JobRecord.model_validate_json(raw)
    assert record.job_id == job.job_id
    assert record.status == "collecting"


# ---------------------------------------------------------------------------
# build_job_store selection
# ---------------------------------------------------------------------------


def test_build_job_store_defaults_to_in_memory_when_redis_url_unset(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    store = build_job_store()
    assert isinstance(store, InMemoryJobStore)


def test_build_job_store_uses_redis_when_configured(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    with patch(
        "app.api.job_store.RedisJobStore.from_url",
        return_value=RedisJobStore(fakeredis.FakeStrictRedis()),
    ) as from_url:
        store = build_job_store()
    from_url.assert_called_once_with("redis://localhost:6379/0")
    assert isinstance(store, RedisJobStore)


def test_build_job_store_falls_back_when_redis_unavailable(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    with patch(
        "app.api.job_store.RedisJobStore.from_url",
        side_effect=ConnectionError("connection refused"),
    ):
        store = build_job_store()
    assert isinstance(store, InMemoryJobStore)


# ---------------------------------------------------------------------------
# app/api/main.py uses the in-memory store when REDIS_URL is unset
# (the test suite runs with REDIS_URL unset by default)
# ---------------------------------------------------------------------------


def test_main_module_store_is_in_memory_by_default():
    from app.api.main import jobs

    assert isinstance(jobs, InMemoryJobStore)

