"""
Tests for opt-in multi-model consensus mode.

All LLM calls are mocked — no live API calls (per this task's quota rule,
no real dual-model calls are made anywhere in this round).

Scenarios covered
-----------------
1. Consensus disabled by default: consensus_check passes state through
   untouched and makes NO extra LLM call (mock called exactly once total —
   the primary holistic_recommend call, not twice).
2. Consensus enabled, mocked matching outputs → agreement_level "full".
3. Consensus enabled, mocked differing outputs → correct disagreements list.
4. Consensus requested but neither CONSENSUS_MODEL nor LLM_FALLBACK_MODELS
   configured → graceful decline (enabled=False + human-readable note),
   no crash, no LLM call at all.
5. consensus_result survives on SystemDesignRecommendation and serializes.

Conventions match the existing node tests (patch invoke_structured at the
module where it is looked up, minimal fixtures, explicit call counts).
"""

from __future__ import annotations

from unittest.mock import patch

from app.agent.nodes.consensus_check import (
    compare_recommendations,
    consensus_check,
)
from app.models.schemas import (
    CacheCandidate,
    CacheEngine,
    CacheRecommendation,
    ConsensusResult,
    DatabaseCandidate,
    DatabaseRecommendation,
    InstanceCandidate,
    InstanceRecommendation,
    LoadBalancerRecommendation,
    ResourceProfile,
    SystemDesignRecommendation,
    TechnicalNeeds,
    TrafficPattern,
    UserRequirements,
)


# ---------------------------------------------------------------------------
# Fixture helpers (mirroring tests/test_holistic_recommender.py conventions)
# ---------------------------------------------------------------------------


def _needs(**kw) -> TechnicalNeeds:
    base = dict(
        estimated_concurrency=100,
        resource_profile=ResourceProfile.BALANCED,
        traffic_pattern=TrafficPattern.STEADY,
        requires_gpu=False,
        scaling_recommendation="vertical / fixed size",
        needs_database=True,
        needs_cache=True,
        min_instances=1,
        max_instances=1,
        load_balancer_needed=False,
        reasoning="test",
    )
    base.update(kw)
    return TechnicalNeeds(**base)


def _rec(
    *,
    compute="t3.medium",
    db=("db.t3.medium", "PostgreSQL"),
    cache=("cache.t3.medium", CacheEngine.REDIS),
    lb_needed=False,
    lb_type=None,
) -> SystemDesignRecommendation:
    db_instance, db_engine = db
    cache_instance, cache_engine = cache
    return SystemDesignRecommendation(
        compute=InstanceRecommendation(
            recommended_instance=compute,
            why="primary reasoning",
            assumptions=[],
            confidence="high",
        ),
        database=DatabaseRecommendation(
            needed=True,
            recommended_instance=db_instance,
            engine_suggestion=db_engine,
            why="relational storage",
            confidence="high",
        ),
        cache=CacheRecommendation(
            needed=True,
            recommended_instance=cache_instance,
            engine=cache_engine,
            why="hot reads",
            confidence="high",
        ),
        load_balancer=LoadBalancerRecommendation(
            needed=lb_needed,
            load_balancer_type=lb_type,
            why="single instance needs no balancing",
        ),
        architecture_summary="test architecture",
    )


def _state(**kw) -> dict:
    base = {
        "requirements": UserRequirements(),
        "latest_user_message": None,
        "next_question": None,
        "pending_field": None,
        "repo_analysis": None,
        "repo_analysis_note": None,
        "technical_needs": _needs(),
        "instance_candidates": [
            InstanceCandidate(instance_type="t3.medium", vcpu=2, memory_gib=4.0),
            InstanceCandidate(instance_type="m5.large", vcpu=2, memory_gib=8.0),
        ],
        "database_candidates": [
            DatabaseCandidate(
                instance_type="db.t3.medium",
                family="General purpose",
                vcpu=2,
                memory_gib=4.0,
            ),
        ],
        "cache_candidates": [
            CacheCandidate(
                instance_type="cache.t3.medium",
                family="Standard",
                engine=CacheEngine.REDIS,
                vcpu=2,
                memory_gib=3.14,
            ),
        ],
        "recommendation": None,
        "system_design_recommendation": None,
        "terraform_files": None,
        "consensus_requested": False,
    }
    base.update(kw)
    return base


def _llm_env(monkeypatch, **env):
    defaults = {
        "API_KEY": "test-key",
        "BASE_URL": "https://openrouter.ai/api/v1",
        "MODEL_NAME": "primary/test-model",
    }
    defaults.update(env)
    for k, v in defaults.items():
        if v is None:
            monkeypatch.delenv(k, raising=False)
        else:
            monkeypatch.setenv(k, v)


# ---------------------------------------------------------------------------
# 1. Disabled by default — no extra LLM call, state untouched
# ---------------------------------------------------------------------------


def test_consensus_disabled_by_default_makes_no_extra_call(monkeypatch):
    """consensus_requested=False → node passes through, zero LLM calls.

    The state's primary recommendation is returned byte-identical and the
    mocked holistic path is never invoked — the "exactly once, not twice"
    budget guarantee at the node level.
    """
    _llm_env(monkeypatch, CONSENSUS_MODEL=None, LLM_FALLBACK_MODELS=None)

    primary = _rec()
    state = _state(
        consensus_requested=False,
        system_design_recommendation=primary,
    )

    with patch(
        "app.agent.nodes.consensus_check.build_system_design_recommendation"
    ) as build_mock:
        out = consensus_check(state)

    build_mock.assert_not_called()
    assert out["system_design_recommendation"] is primary
    assert out["system_design_recommendation"].consensus_result is None


def test_consensus_requested_but_no_primary_is_noop(monkeypatch):
    """consensus requested with no primary recommendation → pass through."""
    _llm_env(monkeypatch, CONSENSUS_MODEL=None, LLM_FALLBACK_MODELS=None)
    state = _state(consensus_requested=True, system_design_recommendation=None)

    with patch(
        "app.agent.nodes.consensus_check.build_system_design_recommendation"
    ) as build_mock:
        out = consensus_check(state)

    build_mock.assert_not_called()
    assert out["system_design_recommendation"] is None


# ---------------------------------------------------------------------------
# 2. Enabled, matching outputs → agreement_level "full"
# ---------------------------------------------------------------------------


def test_consensus_matching_outputs_full_agreement(monkeypatch):
    """Both models choose identically on all four tiers → "full"."""
    _llm_env(
        monkeypatch,
        CONSENSUS_MODEL="secondary/test-model",
        LLM_FALLBACK_MODELS=None,
    )

    primary = _rec()
    secondary = _rec()  # identical choices
    state = _state(consensus_requested=True, system_design_recommendation=primary)

    with patch(
        "app.agent.nodes.consensus_check.build_system_design_recommendation",
        return_value=secondary,
    ) as build_mock:
        out = consensus_check(state)

    build_mock.assert_called_once()
    # The override must be the consensus model (never the primary).
    _, kwargs = build_mock.call_args
    assert kwargs["model_override"] == "secondary/test-model"

    rec = out["system_design_recommendation"]
    result = rec.consensus_result
    assert isinstance(result, ConsensusResult)
    assert result.enabled is True
    assert result.primary_model == "primary/test-model"
    assert result.secondary_model == "secondary/test-model"
    assert result.agreement_level == "full"
    assert result.agreements == ["compute", "database", "cache", "load_balancer"]
    assert result.disagreements == []
    # Primary recommendation itself is untouched (same tier choices).
    assert rec.compute.recommended_instance == "t3.medium"


# ---------------------------------------------------------------------------
# 3. Enabled, differing outputs → correct disagreements list
# ---------------------------------------------------------------------------


def test_consensus_differing_outputs_correct_disagreements(monkeypatch):
    """Two tiers differ → "partial" + exact disagreement records."""
    _llm_env(
        monkeypatch,
        CONSENSUS_MODEL="secondary/test-model",
        LLM_FALLBACK_MODELS=None,
    )

    primary = _rec()  # t3.medium / db.t3.medium / cache.t3.medium / no LB
    secondary = _rec(
        compute="m5.large",  # differs
        db=("db.t3.medium", "PostgreSQL"),  # same
        cache=("cache.t3.medium", CacheEngine.MEMCACHED),  # engine differs
        lb_needed=False,  # same ("not needed")
    )
    state = _state(consensus_requested=True, system_design_recommendation=primary)

    with patch(
        "app.agent.nodes.consensus_check.build_system_design_recommendation",
        return_value=secondary,
    ):
        out = consensus_check(state)

    result = out["system_design_recommendation"].consensus_result
    assert result.enabled is True
    assert result.agreement_level == "partial"
    assert result.agreements == ["database", "load_balancer"]
    assert [d.tier for d in result.disagreements] == ["compute", "cache"]

    compute_d = result.disagreements[0]
    assert compute_d.primary_choice == "t3.medium"
    assert compute_d.secondary_choice == "m5.large"
    cache_d = result.disagreements[1]
    assert "REDIS" in cache_d.primary_choice
    assert "MEMCACHED" in cache_d.secondary_choice


    cache_d = result.disagreements[1]
    assert "REDIS" in cache_d.primary_choice
    assert "MEMCACHED" in cache_d.secondary_choice


def test_consensus_three_diffs_significant_disagreement(monkeypatch):
    """3+ tiers differ → "significant_disagreement" (deterministic rule)."""
    _llm_env(
        monkeypatch,
        CONSENSUS_MODEL="secondary/test-model",
        LLM_FALLBACK_MODELS=None,
    )

    primary = _rec()
    secondary = _rec(
        compute="m5.large",
        db=("db.m5.large", "MySQL"),
        cache=("cache.t3.medium", CacheEngine.REDIS),  # same as primary
        lb_needed=True,
        lb_type="Application Load Balancer",
    )
    state = _state(consensus_requested=True, system_design_recommendation=primary)

    with patch(
        "app.agent.nodes.consensus_check.build_system_design_recommendation",
        return_value=secondary,
    ):
        out = consensus_check(state)

    result = out["system_design_recommendation"].consensus_result
    assert result.agreement_level == "significant_disagreement"
    assert result.agreements == ["cache"]
    assert [d.tier for d in result.disagreements] == [
        "compute",
        "database",
        "load_balancer",
    ]


def test_compare_recommendations_is_deterministic(monkeypatch):
    """Pure compare fn: same inputs → same outputs, no LLM involved."""
    _llm_env(monkeypatch, CONSENSUS_MODEL=None, LLM_FALLBACK_MODELS=None)
    a, b = _rec(), _rec(compute="c5.large")
    r1 = compare_recommendations(a, b, primary_model="m1", secondary_model="m2")
    r2 = compare_recommendations(a, b, primary_model="m1", secondary_model="m2")
    assert r1.agreement_level == r2.agreement_level == "partial"
    assert r1.model_dump() == r2.model_dump()


    r1 = compare_recommendations(a, b, primary_model="m1", secondary_model="m2")
    r2 = compare_recommendations(a, b, primary_model="m1", secondary_model="m2")
    assert r1.agreement_level == r2.agreement_level == "partial"
    assert r1.model_dump() == r2.model_dump()


# ---------------------------------------------------------------------------
# 4. Requested but unconfigured → graceful decline, no crash, no call
# ---------------------------------------------------------------------------


def test_consensus_unconfigured_declines_gracefully(monkeypatch):
    """No CONSENSUS_MODEL and no fallbacks → enabled=False + clear note."""
    _llm_env(monkeypatch, CONSENSUS_MODEL=None, LLM_FALLBACK_MODELS=None)

    primary = _rec()
    state = _state(consensus_requested=True, system_design_recommendation=primary)

    with patch(
        "app.agent.nodes.consensus_check.build_system_design_recommendation"
    ) as build_mock:
        out = consensus_check(state)  # must not raise

    build_mock.assert_not_called()  # "No extra LLM call was made."
    rec = out["system_design_recommendation"]
    result = rec.consensus_result
    assert isinstance(result, ConsensusResult)
    assert result.enabled is False
    assert result.secondary_model == ""
    assert result.agreement_level is None
    assert result.note is not None and "CONSENSUS_MODEL" in result.note
    # Primary recommendation passes through with only the result attached.
    assert rec.compute.recommended_instance == "t3.medium"


def test_consensus_falls_back_to_first_fallback_model(monkeypatch):
    """Unset CONSENSUS_MODEL → LLM_FALLBACK_MODELS[0] is used, not a decline."""
    _llm_env(
        monkeypatch,
        CONSENSUS_MODEL=None,
        LLM_FALLBACK_MODELS="fallback/model-a,fallback/model-b",
    )

    primary = _rec()
    state = _state(consensus_requested=True, system_design_recommendation=primary)

    with patch(
        "app.agent.nodes.consensus_check.build_system_design_recommendation",
        return_value=_rec(),
    ) as build_mock:
        out = consensus_check(state)

    _, kwargs = build_mock.call_args
    assert kwargs["model_override"] == "fallback/model-a"
    result = out["system_design_recommendation"].consensus_result
    assert result.enabled is True
    assert result.secondary_model == "fallback/model-a"


def test_consensus_second_call_failure_never_breaks_run(monkeypatch):
    """A failing second opinion degrades to enabled=False, not an exception."""
    from app.agent.nodes.holistic_recommender import HolisticRecommendationError

    _llm_env(monkeypatch, CONSENSUS_MODEL="secondary/test-model")

    primary = _rec()
    state = _state(consensus_requested=True, system_design_recommendation=primary)

    with patch(
        "app.agent.nodes.consensus_check.build_system_design_recommendation",
        side_effect=HolisticRecommendationError("bad JSON from second model"),
    ):
        out = consensus_check(state)  # must not raise

    result = out["system_design_recommendation"].consensus_result
    assert result.enabled is False
    assert "unchanged" in (result.note or "")


# ---------------------------------------------------------------------------
# 5. Serialization — consensus_result survives model_dump (API surface)
# ---------------------------------------------------------------------------


def test_consensus_result_serializes_with_recommendation(monkeypatch):
    """The attached result round-trips through model_dump(mode='json')."""
    _llm_env(
        monkeypatch,
        CONSENSUS_MODEL="secondary/test-model",
        LLM_FALLBACK_MODELS=None,
    )

    primary = _rec()
    state = _state(consensus_requested=True, system_design_recommendation=primary)

    with patch(
        "app.agent.nodes.consensus_check.build_system_design_recommendation",
        return_value=_rec(compute="m5.large"),
    ):
        out = consensus_check(state)

    dumped = out["system_design_recommendation"].model_dump(mode="json")
    assert dumped["consensus_result"]["enabled"] is True
    assert dumped["consensus_result"]["agreement_level"] == "partial"
    assert dumped["consensus_result"]["disagreements"][0]["tier"] == "compute"
