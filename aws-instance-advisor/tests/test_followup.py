"""
Tests for conversational follow-up on completed recommendations.

Covers:
  - POST /api/recommend/{job_id}/followup produces one LLM call and appends to history.
  - History persists across subsequent calls and appears in GET /api/recommend/{job_id}.
  - Rejected on non-done jobs (HTTP 400).
  - Rejected on non-existent jobs (HTTP 404).
  - Rate limiting applies (HTTP 429).
  - Follow-up persists in both InMemoryJobStore and RedisJobStore (fakeredis).
  - "Requires new data" prompt scenario produces honest decline without fabricated data.
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any
from unittest.mock import MagicMock, patch

import fakeredis
import httpx
import pytest
from langchain_core.messages import AIMessage

os.environ.setdefault("CORS_ALLOWED_ORIGIN", "http://localhost:3000")
os.environ.setdefault("PORT", "8000")

from app.api.job_store import (
    FollowupExchange,
    InMemoryJobStore,
    Job,
    RedisJobStore,
)
from app.api.main import app, jobs as api_jobs_store, recommend_rate_limiter
from app.llm.followup import answer_followup
from app.models.schemas import (
    CacheEngine,
    CacheRecommendation,
    DatabaseRecommendation,
    EstimatedCost,
    InstanceRecommendation,
    LoadBalancerRecommendation,
    ResourceProfile,
    SystemDesignRecommendation,
    TechnicalNeeds,
    TrafficPattern,
    UserRequirements,
)

_TRANSPORT = httpx.ASGITransport(app=app)


def _async_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=_TRANSPORT, base_url="http://testserver")


def _http(method: str, path: str, **kwargs) -> httpx.Response:
    async def _do() -> httpx.Response:
        async with _async_client() as c:
            return await c.request(method, path, **kwargs)

    return asyncio.run(_do())


def _get(path: str) -> httpx.Response:
    return _http("GET", path)


def _post(path: str, json: Any = None) -> httpx.Response:
    return _http("POST", path, json=json)


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    recommend_rate_limiter.clear()


def _sample_sdr() -> SystemDesignRecommendation:
    return SystemDesignRecommendation(
        compute=InstanceRecommendation(
            recommended_instance="t3.medium",
            why="Optimal CPU/RAM ratio for steady web workload.",
            assumptions=["steady traffic"],
            confidence="high",
        ),
        database=DatabaseRecommendation(
            needed=True,
            recommended_instance="db.t3.medium",
            engine_suggestion="PostgreSQL",
            why="Relational ACID storage.",
            assumptions=["standard relational DB"],
            confidence="high",
        ),
        cache=CacheRecommendation(
            needed=True,
            recommended_instance="cache.t3.medium",
            engine=CacheEngine.REDIS,
            why="Session caching and query acceleration.",
            assumptions=["session cache"],
            confidence="high",
        ),
        load_balancer=LoadBalancerRecommendation(
            needed=True,
            load_balancer_type="Application Load Balancer",
            why="Terminates TLS and distributes HTTP traffic.",
        ),
        architecture_summary="Standard 3-tier architecture with ALB, EC2, RDS PostgreSQL, and ElastiCache Redis.",
        estimated_cost=EstimatedCost(
            compute_monthly_low=30.36,
            compute_monthly_high=60.72,
            database_monthly=49.64,
            cache_monthly=24.82,
            total_monthly_low=104.82,
            total_monthly_high=135.18,
        ),
    )


def _sample_technical_needs() -> TechnicalNeeds:
    return TechnicalNeeds(
        estimated_concurrency=50,
        resource_profile=ResourceProfile.BALANCED,
        traffic_pattern=TrafficPattern.STEADY,
        requires_gpu=False,
        scaling_recommendation="Horizontal scaling 1 to 2 instances",
        needs_database=True,
        needs_cache=True,
        min_instances=1,
        max_instances=2,
        load_balancer_needed=True,
        reasoning="Steady traffic with peak periods warrants 1-2 instances behind an ALB.",
    )


def _create_done_job(job_id: str = "done-job-123") -> Job:
    sdr = _sample_sdr()
    tn = _sample_technical_needs()
    state = {
        "requirements": UserRequirements(),
        "latest_user_message": "test",
        "next_question": None,
        "pending_field": None,
        "technical_needs": tn,
        "instance_candidates": [],
        "database_candidates": [],
        "cache_candidates": [],
        "recommendation": None,
        "system_design_recommendation": sdr,
        "terraform_files": {"main.tf": "# tf"},
        "consensus_requested": False,
    }
    result = {
        "system_design_recommendation": sdr.model_dump(mode="json"),
        "technical_needs": tn.model_dump(mode="json"),
        "terraform_files": {"main.tf": "# tf"},
    }
    job = Job(
        job_id=job_id,
        status="done",
        current_stage="Generating Terraform",
        state=state,
        result=result,
    )
    api_jobs_store.put(job)
    return job


def test_followup_on_done_job_calls_llm_once_and_appends_history():
    """Asking a follow-up question invokes LLM once and appends to job history."""
    job_id = f"test-done-{int(time.time())}"
    _create_done_job(job_id)

    mock_llm_answer = (
        "t3.medium was chosen because it provides 2 vCPUs and 4 GiB RAM, "
        "which fits your balanced workload profile without over-provisioning."
    )

    with patch("app.llm.followup._call_with_failover") as mock_failover:
        mock_failover.return_value = mock_llm_answer

        resp = _post(
            f"/api/recommend/{job_id}/followup",
            json={"question": "Why did you choose t3.medium over m5.large?"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["job_id"] == job_id
        assert data["answer"] == mock_llm_answer
        assert len(data["followup_history"]) == 1
        assert data["followup_history"][0]["question"] == "Why did you choose t3.medium over m5.large?"
        assert data["followup_history"][0]["answer"] == mock_llm_answer
        assert mock_failover.call_count == 1

        # Follow-up history is visible via polling GET endpoint
        get_resp = _get(f"/api/recommend/{job_id}")
        assert get_resp.status_code == 200
        get_data = get_resp.json()
        assert "followup_history" in get_data
        assert len(get_data["followup_history"]) == 1

        # Second question appends to history (total 2)
        mock_failover.return_value = "Redis was selected for sub-millisecond session caching."
        resp2 = _post(
            f"/api/recommend/{job_id}/followup",
            json={"question": "Why Redis instead of Memcached?"},
        )
        assert resp2.status_code == 200
        data2 = resp2.json()
        assert len(data2["followup_history"]) == 2
        assert data2["followup_history"][1]["question"] == "Why Redis instead of Memcached?"


def test_followup_rejected_on_non_done_job():
    """Follow-up is rejected with HTTP 400 when the job is not in 'done' status."""
    for invalid_status in ("collecting", "awaiting_input", "running", "error"):
        job_id = f"test-{invalid_status}-{int(time.time())}"
        job = Job(
            job_id=job_id,
            status=invalid_status,  # type: ignore[arg-type]
            current_stage="Testing",
            state={},
        )
        api_jobs_store.put(job)

        resp = _post(
            f"/api/recommend/{job_id}/followup",
            json={"question": "Any question"},
        )
        assert resp.status_code == 400
        assert f"Job is not done (current status: {invalid_status})" in resp.json()["detail"]


def test_followup_rejected_when_job_not_found():
    """Follow-up on an unknown job ID returns HTTP 404."""
    resp = _post(
        "/api/recommend/00000000-0000-0000-0000-000000000999/followup",
        json={"question": "Hello?"},
    )
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


def test_followup_rate_limiting():
    """Follow-up endpoint is protected by the same per-IP rate limiter."""
    job_id = f"test-rl-{int(time.time())}"
    _create_done_job(job_id)

    with patch("app.llm.followup._call_with_failover", return_value="Short answer"):
        responses = [
            _post(f"/api/recommend/{job_id}/followup", json={"question": f"Question {i}"})
            for i in range(5)
        ]
        blocked = _post(f"/api/recommend/{job_id}/followup", json={"question": "Question 6"})

    assert all(r.status_code == 200 for r in responses)
    assert blocked.status_code == 429
    assert blocked.headers["retry-after"].isdigit()


def test_followup_requires_new_data_honest_decline():
    """When the question requires data not in the recommendation, model declines honestly."""
    sdr = _sample_sdr()
    tn = _sample_technical_needs()

    honest_decline_text = (
        "Spot instance pricing and availability were not evaluated as part of this "
        "on-demand architecture analysis. To determine spot savings and interruption risks, "
        "please start a new analysis."
    )

    mock_chat_model = MagicMock()
    mock_chat_model.invoke.return_value = AIMessage(content=honest_decline_text)

    with patch("app.llm.client.get_chat_model", return_value=mock_chat_model):
        answer = answer_followup(
            system_design_recommendation=sdr,
            technical_needs=tn,
            question="What is the spot price for these instances?",
            prior_history=[],
        )

        assert answer == honest_decline_text
        # Verify prompt messages sent to model included the critical instruction
        call_args = mock_chat_model.invoke.call_args[0][0]
        system_content = "\n".join(m.content for m in call_args if hasattr(m, "content"))
        assert "CRITICAL INSTRUCTIONS" in system_content
        assert "never fabricate numbers" in system_content.lower()


def test_followup_persists_in_both_job_stores():
    """FollowupExchange persists in both InMemoryJobStore and RedisJobStore."""
    job_id = "test-store-sync-1"
    exchange = FollowupExchange(
        question="What is the DB?",
        answer="PostgreSQL on db.t3.medium.",
        timestamp="2026-09-21T13:30:00Z",
    )

    # 1. InMemoryJobStore
    mem_store = InMemoryJobStore()
    job_mem = Job(
        job_id=job_id,
        status="done",
        current_stage="Done",
        state={},
    )
    mem_store.put(job_mem)
    mem_store.add_followup(job_id, exchange)

    loaded_mem = mem_store.get(job_id)
    assert loaded_mem is not None
    assert len(loaded_mem.followup_history) == 1
    assert loaded_mem.followup_history[0].question == exchange.question
    assert loaded_mem.followup_history[0].answer == exchange.answer

    # 2. RedisJobStore (fakeredis)
    fake_redis_client = fakeredis.FakeRedis()
    redis_store = RedisJobStore(fake_redis_client)
    job_redis = Job(
        job_id=job_id,
        status="done",
        current_stage="Done",
        state={},
    )
    redis_store.put(job_redis)
    redis_store.add_followup(job_id, exchange)

    loaded_redis = redis_store.get(job_id)
    assert loaded_redis is not None
    assert len(loaded_redis.followup_history) == 1
    assert loaded_redis.followup_history[0].question == exchange.question
    assert loaded_redis.followup_history[0].answer == exchange.answer
    assert loaded_redis.followup_history[0].timestamp == exchange.timestamp
