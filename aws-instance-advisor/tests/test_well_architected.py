"""
Tests for the deterministic Well-Architected-style review.

Every rule is exercised in isolation with plain Python objects — no LLM call,
no network, no fixtures beyond local Pydantic models.  One test per rule
covering both the fire and no-fire case.

The module under test (app.analysis.well_architected) is a pure function, so
these assertions are exhaustive rather than probabilistic.
"""

from __future__ import annotations

from unittest.mock import patch

from app.analysis.well_architected import build_well_architected_review
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
)


# ---------------------------------------------------------------------------
# Fixture helpers
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
        min_instances=2,
        max_instances=4,
        load_balancer_needed=True,
        reasoning="test fixture",
    )
    base.update(kw)
    return TechnicalNeeds(**base)


def _sdr(**kw) -> SystemDesignRecommendation:
    base = dict(
        compute=InstanceRecommendation(
            recommended_instance="m5.large",
            why="balanced",
            assumptions=[],
            confidence="high",
        ),
        database=DatabaseRecommendation(
            needed=True,
            recommended_instance="db.m5.large",
            engine_suggestion="PostgreSQL",
            why="relational",
            confidence="high",
        ),
        cache=CacheRecommendation(
            needed=True,
            recommended_instance="cache.m5.large",
            engine=CacheEngine.REDIS,
            why="hot reads",
            confidence="high",
        ),
        load_balancer=LoadBalancerRecommendation(
            needed=True,
            load_balancer_type="Application Load Balancer",
            why="multi instance",
        ),
        architecture_summary="test architecture",
        estimated_cost=EstimatedCost(total_monthly_low=100.0, total_monthly_high=200.0),
    )
    base.update(kw)
    return SystemDesignRecommendation(**base)


def _pillars(findings):
    return [(f.pillar, f.severity) for f in findings]


# ---------------------------------------------------------------------------
# Rule 1 — reliability: min_instances == 1 (no redundancy)
# ---------------------------------------------------------------------------


def test_rule_no_compute_redundancy_fires():
    findings = build_well_architected_review(
        _sdr(), _needs(min_instances=1, load_balancer_needed=True)
    )
    hit = [f for f in findings if f.pillar == "reliability"]
    assert len(hit) == 1
    assert hit[0].severity == "warning"
    assert "min_instances is 1" in hit[0].message


def test_rule_no_compute_redundancy_does_not_fire():
    findings = build_well_architected_review(
        _sdr(), _needs(min_instances=2, max_instances=4, load_balancer_needed=True)
    )
    assert not [f for f in findings if f.pillar == "reliability"]


# ---------------------------------------------------------------------------
# Rule 2 — performance_efficiency: max_instances > 1 without a load balancer
# ---------------------------------------------------------------------------


def test_rule_max_instances_without_lb_fires():
    findings = build_well_architected_review(
        _sdr(load_balancer=LoadBalancerRecommendation(needed=False, why="none")),
        _needs(min_instances=2, max_instances=4, load_balancer_needed=False),
    )
    hit = [f for f in findings if "would not distribute" in f.message]
    assert len(hit) == 1
    assert hit[0].pillar == "performance_efficiency"
    assert hit[0].severity == "warning"


def test_rule_max_instances_without_lb_does_not_fire_when_lb_present():
    findings = build_well_architected_review(
        _sdr(), _needs(min_instances=2, max_instances=4, load_balancer_needed=True)
    )
    assert not [f for f in findings if "would not distribute" in f.message]


def test_rule_max_instances_without_lb_does_not_fire_when_single_instance():
    findings = build_well_architected_review(
        _sdr(load_balancer=LoadBalancerRecommendation(needed=False, why="none")),
        _needs(min_instances=1, max_instances=1, load_balancer_needed=False),
    )
    assert not [f for f in findings if "would not distribute" in f.message]


# ---------------------------------------------------------------------------
# Rule 3 — performance_efficiency: min_instances == 1 and no load balancer
# ---------------------------------------------------------------------------


def test_rule_single_instance_no_lb_fires():
    findings = build_well_architected_review(
        _sdr(load_balancer=LoadBalancerRecommendation(needed=False, why="none")),
        _needs(min_instances=1, max_instances=1, load_balancer_needed=False),
    )
    hit = [f for f in findings if "point of contention" in f.message]
    assert len(hit) == 1
    assert hit[0].pillar == "performance_efficiency"
    assert hit[0].severity == "info"


def test_rule_single_instance_no_lb_does_not_fire_when_min_above_one():
    findings = build_well_architected_review(
        _sdr(load_balancer=LoadBalancerRecommendation(needed=False, why="none")),
        _needs(min_instances=2, max_instances=2, load_balancer_needed=False),
    )
    assert not [f for f in findings if "point of contention" in f.message]


# ---------------------------------------------------------------------------
# Rule 4 — operational_excellence: grounding_passed is False
# ---------------------------------------------------------------------------


def test_rule_grounding_failed_fires_and_cites_notes():
    findings = build_well_architected_review(
        _sdr(
            grounding_passed=False,
            grounding_notes=["summary claims auto-scaling but max_instances == 1"],
        ),
        _needs(),
    )
    hit = [f for f in findings if f.pillar == "operational_excellence"
           and f.severity == "warning"]
    assert len(hit) == 1
    assert "max_instances == 1" in hit[0].message


def test_rule_grounding_failed_fires_without_notes():
    findings = build_well_architected_review(
        _sdr(grounding_passed=False, grounding_notes=[]), _needs()
    )
    hit = [f for f in findings if f.pillar == "operational_excellence"
           and f.severity == "warning"]
    assert len(hit) == 1
    assert "no issue detail was recorded" in hit[0].message


def test_rule_grounding_failed_does_not_fire_when_passed():
    findings = build_well_architected_review(
        _sdr(grounding_passed=True, grounding_notes=[]), _needs()
    )
    assert not [f for f in findings if f.pillar == "operational_excellence"
                and f.severity == "warning"]


def test_rule_grounding_failed_does_not_fire_when_not_run():
    """grounding_passed is None (check has not run) → no finding."""
    findings = build_well_architected_review(
        _sdr(grounding_passed=None, grounding_notes=[]), _needs()
    )
    assert not [f for f in findings if f.pillar == "operational_excellence"
                and f.severity == "warning"]


# ---------------------------------------------------------------------------
# Rule 5 — security: mirror of the Terraform baseline-SG warning
# ---------------------------------------------------------------------------


def test_rule_security_baseline_always_fires():
    for needs in (_needs(), _needs(min_instances=1), _needs(max_instances=1)):
        findings = build_well_architected_review(_sdr(), needs)
        hit = [f for f in findings if f.pillar == "security"]
        assert len(hit) == 1, "security baseline finding must always be present"
        assert hit[0].severity == "info"
        assert "security groups" in hit[0].message


# ---------------------------------------------------------------------------
# Rule 6 — cost_optimization: memory-bound profile but no cache tier
# ---------------------------------------------------------------------------


def test_rule_cache_absent_for_read_heavy_fires():
    findings = build_well_architected_review(
        _sdr(cache=CacheRecommendation(needed=False, why="no cache", confidence="high")),
        _needs(resource_profile=ResourceProfile.MEMORY_BOUND),
    )
    hit = [f for f in findings if "cache tier could absorb" in f.message]
    assert len(hit) == 1
    assert hit[0].pillar == "cost_optimization"
    assert hit[0].severity == "info"


def test_rule_cache_absent_for_read_heavy_does_not_fire_when_cache_needed():
    findings = build_well_architected_review(
        _sdr(), _needs(resource_profile=ResourceProfile.MEMORY_BOUND)
    )
    assert not [f for f in findings if "cache tier could absorb" in f.message]


def test_rule_cache_absent_for_read_heavy_does_not_fire_for_other_profiles():
    for profile in (
        ResourceProfile.BALANCED,
        ResourceProfile.CPU_BOUND,
        ResourceProfile.GPU_BOUND,
        ResourceProfile.UNKNOWN,
    ):
        findings = build_well_architected_review(
            _sdr(cache=CacheRecommendation(needed=False, why="no cache", confidence="high")),
            _needs(resource_profile=profile),
        )
        assert not [f for f in findings if "cache tier could absorb" in f.message], profile


# ---------------------------------------------------------------------------
# Rule 7 — cost_optimization: estimated_cost is None
# ---------------------------------------------------------------------------


def test_rule_cost_not_estimated_fires():
    findings = build_well_architected_review(_sdr(estimated_cost=None), _needs())
    hit = [f for f in findings if "no monthly cost estimate" in f.message]
    assert len(hit) == 1
    assert hit[0].pillar == "cost_optimization"
    assert hit[0].severity == "info"


def test_rule_cost_not_estimated_does_not_fire_when_cost_present():
    findings = build_well_architected_review(
        _sdr(estimated_cost=EstimatedCost(total_monthly_low=42.0)), _needs()
    )
    assert not [f for f in findings if "no monthly cost estimate" in f.message]


# ---------------------------------------------------------------------------
# Rule 8 — operational_excellence: repo analysis did not contribute
# ---------------------------------------------------------------------------


def test_rule_repo_context_unavailable_fires():
    findings = build_well_architected_review(
        _sdr(repo_analysis_note="No GITHUB_MCP_TOKEN configured; repo analysis skipped."),
        _needs(),
    )
    hit = [f for f in findings if "Repository analysis did not contribute" in f.message]
    assert len(hit) == 1
    assert hit[0].pillar == "operational_excellence"
    assert hit[0].severity == "info"


def test_rule_repo_context_unavailable_does_not_fire_without_note():
    for value in (None, "", "   "):
        findings = build_well_architected_review(
            _sdr(repo_analysis_note=value), _needs()
        )
        assert not [
            f for f in findings if "Repository analysis did not contribute" in f.message
        ], value


# ---------------------------------------------------------------------------
# Function-level guarantees: no LLM call, deterministic, non-mutating
# ---------------------------------------------------------------------------


def test_no_llm_call_is_made():
    """The review must never touch the LLM path — assert the mock is unused."""
    with patch("app.llm.structured.invoke_structured") as mock_invoke:
        build_well_architected_review(_sdr(grounding_passed=False), _needs())
    mock_invoke.assert_not_called()


def test_review_is_deterministic_and_ordered():
    sdr, tn = _sdr(grounding_passed=False, estimated_cost=None), _needs(min_instances=1)
    first = build_well_architected_review(sdr, tn)
    second = build_well_architected_review(sdr, tn)
    assert [(f.pillar, f.severity, f.message) for f in first] == [
        (f.pillar, f.severity, f.message) for f in second
    ]
    # Fixed rule order for this input: min_instances==1 (no redundancy),
    # grounding failed, always-on security note, cost unavailable.
    assert _pillars(first) == [
        ("reliability", "warning"),
        ("operational_excellence", "warning"),
        ("security", "info"),
        ("cost_optimization", "info"),
    ]


def test_review_does_not_mutate_inputs():
    sdr, tn = _sdr(), _needs()
    before_sdr = sdr.model_dump()
    before_tn = tn.model_dump()
    build_well_architected_review(sdr, tn)
    assert sdr.model_dump() == before_sdr
    assert tn.model_dump() == before_tn


def test_empty_review_is_valid_when_no_rule_matches():
    """A fully redundant, costed, cache-backed recommendation still yields
    the always-on security note but nothing else."""
    findings = build_well_architected_review(
        _sdr(
            cache=CacheRecommendation(needed=False, why="no cache", confidence="high"),
            estimated_cost=EstimatedCost(total_monthly_low=10.0),
            grounding_passed=True,
        ),
        _needs(
            min_instances=2,
            max_instances=4,
            load_balancer_needed=True,
            needs_cache=False,
            resource_profile=ResourceProfile.BALANCED,
        ),
    )
    assert _pillars(findings) == [("security", "info")]


def test_field_serializes_with_recommendation():
    """well_architected_review round-trips through model_dump(mode='json')."""
    sdr = _sdr(grounding_passed=False)
    sdr = sdr.model_copy(
        update={"well_architected_review": build_well_architected_review(sdr, _needs())}
    )
    dumped = sdr.model_dump(mode="json")
    assert isinstance(dumped["well_architected_review"], list)
    assert dumped["well_architected_review"], "expected at least one finding"
    pillars = {f["pillar"] for f in dumped["well_architected_review"]}
    assert "operational_excellence" in pillars
    assert all(
        set(f) == {"pillar", "severity", "message"}
        for f in dumped["well_architected_review"]
    )
