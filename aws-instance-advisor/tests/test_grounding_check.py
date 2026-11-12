"""
Tests for the grounding / consistency check node.

All LLM calls (invoke_structured) are mocked — no live API calls.

Scenarios covered:
  1. Clean recommendation → grounding_passed=True, grounding_notes=[].
  2. Contradictory recommendation → first check fails → repair LLM call
     is made with the issues appended → second check passes →
     grounding_passed=True on repaired result.
  3. Repair fails second check → grounding_passed=False, grounding_notes
     populated (honest failure, never suppressed).
  4. Repair LLM call raises StructuredOutputError → grounding_passed=False
     flagged on the *original* recommendation.
  5. state missing system_design_recommendation → no-op, state unchanged.
  6. Grounding check itself raises StructuredOutputError → treated as
     unverified (logged, not crashed).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.agent.nodes.grounding_check import (
    GroundingResult,
    _run_grounding_check,
    grounding_check,
)
from app.llm.structured import StructuredOutputError
from app.models.schemas import (
    CacheCandidate,
    CacheEngine,
    CacheRecommendation,
    DatabaseCandidate,
    DatabaseRecommendation,
    EstimatedCost,
    InstanceCandidate,
    InstanceRecommendation,
    LoadBalancerRecommendation,
    RepoAnalysis,
    ResourceProfile,
    SystemDesignRecommendation,
    TechnicalNeeds,
    TrafficPattern,
    UserRequirements,
    WorkloadType,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_invoke():
    model = MagicMock()
    with patch("app.agent.nodes.grounding_check.invoke_structured", model), patch(
        "app.agent.nodes.holistic_recommender.invoke_structured", model
    ):
        yield model


def _needs(**kw) -> TechnicalNeeds:
    base = dict(
        estimated_concurrency=1,
        resource_profile=ResourceProfile.BALANCED,
        traffic_pattern=TrafficPattern.STEADY,
        requires_gpu=False,
        scaling_recommendation="vertical / single instance",
        needs_database=False,
        needs_cache=False,
        min_instances=1,
        max_instances=1,
        load_balancer_needed=False,
        reasoning="batch job, single worker slot",
    )
    base.update(kw)
    return TechnicalNeeds(**base)


def _sdr(
    *,
    architecture_summary: str = "Single EC2 instance, no DB, no cache.",
    scaling_why: str = "Vertical scaling suits single-slot batch job.",
    lb_needed: bool = False,
) -> SystemDesignRecommendation:
    return SystemDesignRecommendation(
        compute=InstanceRecommendation(
            recommended_instance="m5.large",
            why=scaling_why,
            assumptions=[],
            confidence="medium",
        ),
        database=DatabaseRecommendation(
            needed=False,
            why="no DB required",
            confidence="high",
        ),
        cache=CacheRecommendation(
            needed=False,
            why="no cache required",
            confidence="high",
        ),
        load_balancer=LoadBalancerRecommendation(
            needed=lb_needed,
            why="single instance, no LB needed",
        ),
        architecture_summary=architecture_summary,
    )


def _contradictory_sdr() -> SystemDesignRecommendation:
    """
    Classic batch-job scaling contradiction:
    min==max==1 (single instance) but architecture_summary talks about
    horizontal auto-scaling.  This is exactly the hand-fixed bug the
    grounding check automates.
    """
    return _sdr(
        architecture_summary=(
            "Use horizontal auto-scaling to distribute batch jobs across "
            "multiple EC2 instances for peak throughput."
        ),
        scaling_why=(
            "Horizontal scaling allows auto scaling of worker nodes "
            "across the fleet."
        ),
    )


def _base_state(**overrides) -> dict:
    state: dict = {
        "requirements": UserRequirements(
            workload_type=WorkloadType.BATCH_PROCESSING,
            registered_users=None,
            traffic_pattern=TrafficPattern.STEADY,
        ),
        "latest_user_message": None,
        "next_question": None,
        "pending_field": None,
        "technical_needs": _needs(),
        "instance_candidates": [
            InstanceCandidate(
                instance_type="m5.large", vcpu=2, memory_gib=8.0,
                hourly_price_usd=0.096,
            )
        ],
        "database_candidates": [],
        "cache_candidates": [],
        "recommendation": None,
        "system_design_recommendation": _sdr(),
        "terraform_files": None,
    }
    state.update(overrides)
    return state


# ---------------------------------------------------------------------------
# 1. Clean recommendation passes straight through
# ---------------------------------------------------------------------------

def test_clean_recommendation_passes(mock_invoke):
    """A recommendation with no contradictions → grounding_passed=True, no notes."""
    mock_invoke.return_value = GroundingResult(passed=True, issues=[])

    state = _base_state()
    out = grounding_check(state)

    sdr = out["system_design_recommendation"]
    assert sdr.grounding_passed is True
    assert sdr.grounding_notes == []
    # Only one LLM call needed (the initial check).
    assert mock_invoke.call_count == 1


# ---------------------------------------------------------------------------
# 2. Contradictory → repair → second check passes
# ---------------------------------------------------------------------------

def test_contradiction_triggers_repair_and_second_check_passes(mock_invoke):
    """
    First grounding check fails → repair call produces a fixed SDR →
    second check passes → grounding_passed=True on the repaired SDR.
    """
    contradiction_issue = (
        "architecture_summary references horizontal auto-scaling "
        "but min_instances == max_instances == 1."
    )
    first_check = GroundingResult(passed=False, issues=[contradiction_issue])
    repaired_sdr = _sdr(
        architecture_summary="Single EC2 instance runs the batch job serially.",
        scaling_why="Vertical scaling: single worker slot.",
    )
    second_check = GroundingResult(passed=True, issues=[])

    # Calls in order: first_check, repair (SDR), second_check
    mock_invoke.side_effect = [first_check, repaired_sdr, second_check]

    state = _base_state(system_design_recommendation=_contradictory_sdr())
    out = grounding_check(state)

    sdr = out["system_design_recommendation"]
    assert sdr.grounding_passed is True
    assert sdr.grounding_notes == []
    # The repaired SDR's architecture_summary should be the fixed one.
    assert "horizontal auto-scaling" not in sdr.architecture_summary.lower() or \
           "single ec2" in sdr.architecture_summary.lower()

    # Three total calls: initial check, repair LLM call, second check.
    assert mock_invoke.call_count == 3

    # The repair prompt must mention the issue so the model knows what to fix.
    repair_call_prompt: str = mock_invoke.call_args_list[1][0][1]  # (schema, prompt)
    assert contradiction_issue in repair_call_prompt
    assert "CRITICAL CORRECTIONS REQUIRED" in repair_call_prompt


# ---------------------------------------------------------------------------
# 3. Repair fails second check → honest failure flagged
# ---------------------------------------------------------------------------

def test_repair_still_failing_sets_grounding_failed(mock_invoke):
    """
    After repair, second check still fails → grounding_passed=False and
    grounding_notes populated on the returned SDR.
    """
    issue = "horizontal scaling language with min==max==1"
    first_check = GroundingResult(passed=False, issues=[issue])
    repaired_sdr = _contradictory_sdr()  # repair returned equally bad output
    second_check = GroundingResult(passed=False, issues=[issue])

    mock_invoke.side_effect = [first_check, repaired_sdr, second_check]

    state = _base_state(system_design_recommendation=_contradictory_sdr())
    out = grounding_check(state)

    sdr = out["system_design_recommendation"]
    assert sdr.grounding_passed is False
    assert issue in sdr.grounding_notes
    assert mock_invoke.call_count == 3


# ---------------------------------------------------------------------------
# 4. Repair LLM call raises → flag original recommendation
# ---------------------------------------------------------------------------

def test_repair_llm_failure_flags_original(mock_invoke):
    """
    If the repair LLM call raises StructuredOutputError, the original
    recommendation is flagged grounding_passed=False with the issues.
    """
    issue = "auto-scaling summary contradicts single instance"
    first_check = GroundingResult(passed=False, issues=[issue])

    mock_invoke.side_effect = [
        first_check,
        StructuredOutputError("model timed out"),
    ]

    original_sdr = _contradictory_sdr()
    state = _base_state(system_design_recommendation=original_sdr)
    out = grounding_check(state)

    sdr = out["system_design_recommendation"]
    assert sdr.grounding_passed is False
    assert issue in sdr.grounding_notes
    # Only two calls: initial check + repair attempt (which failed).
    assert mock_invoke.call_count == 2


# ---------------------------------------------------------------------------
# 5. Missing system_design_recommendation → no-op
# ---------------------------------------------------------------------------

def test_missing_sdr_is_noop(mock_invoke):
    """When no SDR is present in state, the node passes through silently."""
    state = _base_state(system_design_recommendation=None)
    out = grounding_check(state)

    assert out["system_design_recommendation"] is None
    mock_invoke.assert_not_called()


# ---------------------------------------------------------------------------
# 6. Grounding check LLM call itself fails → unverified (no crash)
# ---------------------------------------------------------------------------

def test_grounding_check_llm_failure_is_unverified(mock_invoke):
    """
    If the grounding check's own LLM call raises StructuredOutputError,
    preserve an explicit unverified result, with no repair or extra model calls.
    """
    mock_invoke.side_effect = StructuredOutputError("parse error")

    state = _base_state(system_design_recommendation=_sdr())
    out = grounding_check(state)

    sdr = out["system_design_recommendation"]
    assert sdr.grounding_passed is None
    assert "unavailable" in sdr.grounding_notes[0].lower()
    assert any("unavailable" in finding.message for finding in sdr.well_architected_review)
    assert mock_invoke.call_count == 1


# ---------------------------------------------------------------------------
# 7. GroundingResult schema itself validates correctly
# ---------------------------------------------------------------------------

def test_grounding_result_passed_empty_issues():
    r = GroundingResult(passed=True, issues=[])
    assert r.passed is True
    assert r.issues == []


def test_grounding_result_failed_with_issues():
    r = GroundingResult(
        passed=False,
        issues=["summary references cache but cache.needed=False"],
    )
    assert r.passed is False
    assert len(r.issues) == 1


@pytest.mark.parametrize("invalid_tier", ["compute", "database", "cache", "missing_database", "missing_cache", "cache_alternative"])
def test_invalid_repair_cannot_reach_export(mock_invoke, invalid_tier):
    from app.agent.nodes.terraform_generator import generate_terraform

    state = _base_state()
    repair = _sdr()
    if invalid_tier == "compute":
        repair.compute.recommended_instance = "m99.impossible"
    elif "database" in invalid_tier:
        state["technical_needs"].needs_database = True
        state["database_candidates"] = [
            DatabaseCandidate(instance_type="db.t3.medium", family="General", vcpu=2, memory_gib=4),
        ]
        if invalid_tier == "database":
            repair.database = DatabaseRecommendation(
                needed=True, recommended_instance="db.m99.impossible", why="invented", confidence="high",
            )
    else:
        state["technical_needs"].needs_cache = True
        state["cache_candidates"] = [
            CacheCandidate(instance_type="cache.t3.micro", family="Standard", engine=CacheEngine.VALKEY, vcpu=2, memory_gib=0.5),
        ]
        if invalid_tier == "cache":
            repair.cache = CacheRecommendation(
                needed=True, recommended_instance="cache.t3.micro", engine=CacheEngine.REDIS,
                why="wrong pair", confidence="high",
            )
        elif invalid_tier == "cache_alternative":
            repair.cache = CacheRecommendation(
                needed=True, recommended_instance="cache.t3.micro", engine=CacheEngine.VALKEY,
                alternative_instance="cache.m99.impossible", why="incomplete pair", confidence="high",
            )
    original = state["system_design_recommendation"]
    mock_invoke.side_effect = [GroundingResult(passed=False, issues=["Contradictory summary"]), repair]

    result = grounding_check(state)["system_design_recommendation"]

    assert result.compute == original.compute
    assert result.database == original.database
    assert result.cache == original.cache
    assert result.grounding_passed is False
    assert "retained" in result.grounding_notes[-1]
    assert mock_invoke.call_count == 2
    assert "m99.impossible" not in generate_terraform(state)["terraform_files"]["main.tf"]


def test_repair_preserves_database_target_and_rebuilds_derived_fields(mock_invoke):
    state = _base_state(
        target_rds_engine="MySQL",
        repo_analysis=RepoAnalysis(has_dockerfile=True, analysis_note="Containerized API"),
        repo_analysis_note="Some files were excluded.",
    )
    state["system_design_recommendation"].repo_analysis_note = state["repo_analysis_note"]
    state["requirements"].database_engine = "MySQL"
    state["technical_needs"].needs_database = True
    state["database_candidates"] = [DatabaseCandidate(
        instance_type="db.t3.medium", family="General", vcpu=2, memory_gib=4,
        hourly_prices_by_engine={"MySQL": 0.017, "PostgreSQL": 0.018},
    )]
    repair = _sdr()
    repair.database = DatabaseRecommendation(
        needed=True, recommended_instance="db.t3.medium", engine_suggestion="PostgreSQL",
        why="Model changed the target", confidence="high",
    )
    repair.estimated_cost = EstimatedCost(total_monthly_low=0, total_monthly_high=0)
    repair.grounding_passed = True
    mock_invoke.side_effect = [
        GroundingResult(passed=False, issues=["Contradictory summary"]),
        repair,
        GroundingResult(passed=False, issues=["Still contradictory"]),
    ]

    result = grounding_check(state)["system_design_recommendation"]

    assert result.database.engine_suggestion == "MySQL"
    assert result.estimated_cost.database_monthly == 12.41
    assert result.estimated_cost.total_monthly_low == 82.49
    assert result.containerized_alternative.recommended is True
    assert result.repo_analysis_note == state["repo_analysis_note"]
    assert any("Still contradictory" in finding.message for finding in result.well_architected_review)
    assert mock_invoke.call_count == 3


def test_repair_keeps_external_database_and_never_adds_rds(mock_invoke):
    state = _base_state()
    state["requirements"].database_engine = "external"
    repair = _sdr()
    repair.database = DatabaseRecommendation(
        needed=True, recommended_instance="db.m99.impossible", why="Invented replacement", confidence="high",
    )
    mock_invoke.side_effect = [
        GroundingResult(passed=False, issues=["Contradictory summary"]),
        repair,
        GroundingResult(passed=True),
    ]
    result = grounding_check(state)["system_design_recommendation"]
    assert result.database.needed is False
    assert result.database.recommended_instance is None
    assert "Keep the existing database" in result.database.why


def test_unavailable_second_check_does_not_certify_repair(mock_invoke):
    mock_invoke.side_effect = [
        GroundingResult(passed=False, issues=["Contradictory summary"]),
        _sdr(),
        StructuredOutputError("auditor timeout"),
    ]
    result = grounding_check(_base_state())["system_design_recommendation"]
    assert result.grounding_passed is None
    assert "Contradictory summary" in result.grounding_notes
    assert "unavailable" in result.grounding_notes[-1]
    assert mock_invoke.call_count == 3
