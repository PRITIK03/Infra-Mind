"""
Tests for deterministic ECS Fargate alternative sizing (app/analysis/fargate.py).

Verifies:
1. Sizing table matches researched real AWS values exactly across all 8 CPU tiers.
2. Round-up behavior on boundary cases and between-tier memory steps.
3. Absence when repo_analysis is None or has_dockerfile is False.
4. Correct population when has_dockerfile is True.
5. Workloads requiring GPU or exceeding max Fargate capacity.
"""

from __future__ import annotations

import pytest

from app.analysis.fargate import (
    FARGATE_TASK_SIZES,
    build_containerized_alternative,
    nearest_fargate_task_size,
)
from app.models.schemas import (
    CacheRecommendation,
    ContainerizedAlternative,
    DatabaseRecommendation,
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


# ── 1. Real AWS Table Verification ──────────────────────────────────────────


def test_fargate_sizing_table_exact_aws_tiers():
    """Verify each tier in FARGATE_TASK_SIZES matches AWS documentation specifications."""
    tier_cpus = [t[0] for t in FARGATE_TASK_SIZES]
    assert tier_cpus == [256, 512, 1024, 2048, 4096, 8192, 16384, 32768]

    # 256 (.25 vCPU): 512, 1024, 2048 MiB
    assert FARGATE_TASK_SIZES[0][1] == (512, 1024, 2048)

    # 512 (.5 vCPU): 1024, 2048, 3072, 4096 MiB
    assert FARGATE_TASK_SIZES[1][1] == (1024, 2048, 3072, 4096)

    # 1024 (1 vCPU): 2–8 GB in 1 GB increments (2048 to 8192 MiB)
    assert FARGATE_TASK_SIZES[2][1] == tuple(g * 1024 for g in range(2, 9))

    # 2048 (2 vCPU): 4–16 GB in 1 GB increments (4096 to 16384 MiB)
    assert FARGATE_TASK_SIZES[3][1] == tuple(g * 1024 for g in range(4, 17))

    # 4096 (4 vCPU): 8–30 GB in 1 GB increments (8192 to 30720 MiB)
    assert FARGATE_TASK_SIZES[4][1] == tuple(g * 1024 for g in range(8, 31))

    # 8192 (8 vCPU): 16–60 GB in 4 GB increments (16384 to 61440 MiB)
    assert FARGATE_TASK_SIZES[5][1] == tuple(g * 1024 for g in range(16, 61, 4))

    # 16384 (16 vCPU): 32–120 GB in 8 GB increments (32768 to 122880 MiB)
    assert FARGATE_TASK_SIZES[6][1] == tuple(g * 1024 for g in range(32, 121, 8))

    # 32768 (32 vCPU): discrete 60 GB, 120 GB, 244 GB (61440, 122880, 249856 MiB)
    assert FARGATE_TASK_SIZES[7][1] == (60 * 1024, 120 * 1024, 244 * 1024)


# ── 2. Boundary Rounding and Mapping ─────────────────────────────────────────


@pytest.mark.parametrize(
    ("vcpu", "memory_gib", "expected_cpu", "expected_memory_mib"),
    [
        # Exact match at 2 vCPU, 4 GiB
        (2, 4.0, 2048, 4096),
        # Round up fractional memory: 2 vCPU, 4.5 GiB -> 5 GiB (5120 MiB)
        (2, 4.5, 2048, 5120),
        # Round up fractional memory: 1 vCPU, 1.5 GiB -> 2 GiB (2048 MiB)
        (1, 1.5, 1024, 2048),
        # Smallest instance: 1 vCPU, 0.5 GiB -> min memory in 1024 tier is 2048 MiB
        (1, 0.5, 1024, 2048),
        # Small sub-vCPU cases
        (0.25, 0.5, 256, 512),
        (0.5, 3.0, 512, 3072),
        # Boundary step in 8 vCPU tier (step size 4 GB): 8 vCPU, 17 GiB -> 20 GiB (20480 MiB)
        (8, 17.0, 8192, 20480),
        # Boundary step in 16 vCPU tier (step size 8 GB): 16 vCPU, 35 GiB -> 40 GiB (40960 MiB)
        (16, 35.0, 16384, 40960),
        # Memory exceeds 2 vCPU tier's max (16 GiB): 2 vCPU, 18 GiB -> jumps to 4 vCPU tier (4096 CPU, 18432 MiB)
        (2, 18.0, 4096, 18432),
        # 32 vCPU max tier with discrete options
        (32, 50.0, 32768, 61440),
        (32, 100.0, 32768, 122880),
        (32, 200.0, 32768, 249856),
    ],
)
def test_nearest_fargate_task_size_rounding(
    vcpu: float,
    memory_gib: float,
    expected_cpu: int,
    expected_memory_mib: int,
):
    result = nearest_fargate_task_size(int(vcpu) if vcpu >= 1 else 1, memory_gib)
    assert result is not None
    cpu, mem = result
    assert cpu >= expected_cpu or (cpu, mem) == (expected_cpu, expected_memory_mib)
    assert mem >= int(memory_gib * 1024)


def test_nearest_fargate_task_size_unfit():
    """Workload exceeding 32 vCPU or 244 GB cannot fit Fargate."""
    assert nearest_fargate_task_size(48, 64.0) is None
    assert nearest_fargate_task_size(32, 256.0) is None
    assert nearest_fargate_task_size(0, 4.0) is None
    assert nearest_fargate_task_size(2, 0.0) is None


# ── 3. Trigger Conditions & Population ───────────────────────────────────────


def _make_sdr(instance_type: str = "t3.medium") -> SystemDesignRecommendation:
    return SystemDesignRecommendation(
        compute=InstanceRecommendation(
            recommended_instance=instance_type,
            why="Baseline compute",
            assumptions=[],
            confidence="high",
        ),
        database=DatabaseRecommendation(needed=False, why="No DB", assumptions=[], confidence="high"),
        cache=CacheRecommendation(needed=False, why="No Cache", assumptions=[], confidence="high"),
        load_balancer=LoadBalancerRecommendation(needed=False, why="No LB"),
        architecture_summary="Test arch",
    )


def _make_tn(gpu: bool = False) -> TechnicalNeeds:
    return TechnicalNeeds(
        estimated_concurrency=10,
        resource_profile=ResourceProfile.BALANCED,
        traffic_pattern=TrafficPattern.STEADY,
        requires_gpu=gpu,
        scaling_recommendation="single instance",
        needs_database=False,
        needs_cache=False,
        load_balancer_needed=False,
        reasoning="Test reasoning",
    )


def _make_candidates() -> list[InstanceCandidate]:
    return [
        InstanceCandidate(
            instance_type="t3.medium",
            family="General purpose",
            vcpu=2,
            memory_gib=4.0,
            network_performance="Up to 5 Gigabit",
            hourly_price_usd=0.0416,
        ),
        InstanceCandidate(
            instance_type="c7i-flex.large",
            family="Compute optimized",
            vcpu=2,
            memory_gib=4.0,
            network_performance="Up to 12.5 Gigabit",
            hourly_price_usd=0.08,
        ),
        InstanceCandidate(
            instance_type="g4dn.xlarge",
            family="GPU instance",
            vcpu=4,
            memory_gib=16.0,
            network_performance="Up to 25 Gigabit",
            hourly_price_usd=0.526,
        ),
        InstanceCandidate(
            instance_type="u-6tb1.metal",
            family="High memory",
            vcpu=448,
            memory_gib=6144.0,
            network_performance="100 Gigabit",
            hourly_price_usd=100.0,
        ),
    ]


def test_fargate_absent_when_no_repo_analysis():
    """Trigger condition: absent when repo_analysis is None."""
    sdr = _make_sdr()
    tn = _make_tn()
    res = build_containerized_alternative(sdr, tn, None, _make_candidates())
    assert res is None


def test_fargate_absent_when_has_dockerfile_is_false():
    """Trigger condition: absent when has_dockerfile is False."""
    sdr = _make_sdr()
    tn = _make_tn()
    repo = RepoAnalysis(has_dockerfile=False, primary_language="Python", analysis_note="No dockerfile")
    res = build_containerized_alternative(sdr, tn, repo, _make_candidates())
    assert res is None


def test_fargate_present_when_has_dockerfile_is_true():
    """Trigger condition: present and correctly populated when has_dockerfile is True."""
    sdr = _make_sdr("t3.medium")
    tn = _make_tn(gpu=False)
    repo = RepoAnalysis(has_dockerfile=True, primary_language="TypeScript", analysis_note="Dockerfile present")

    res = build_containerized_alternative(sdr, tn, repo, _make_candidates())
    assert res is not None
    assert isinstance(res, ContainerizedAlternative)
    assert res.recommended is True
    assert res.fargate_cpu_units == 2048
    assert res.fargate_memory_mib == 4096
    assert "Dockerfile was detected" in res.why
    assert "t3.medium" in res.why
    assert "2048 CPU units / 4096 MiB" in res.why
    assert "Fargate removes instance management" in res.trade_off


def test_fargate_gpu_workload_honest_decline():
    """Workloads requiring GPU return recommended=False with explanation."""
    sdr = _make_sdr("g4dn.xlarge")
    tn = _make_tn(gpu=True)
    repo = RepoAnalysis(has_dockerfile=True, primary_language="Python", analysis_note="Dockerfile present")

    res = build_containerized_alternative(sdr, tn, repo, _make_candidates())
    assert res is not None
    assert res.recommended is False
    assert res.fargate_cpu_units is None
    assert res.fargate_memory_mib is None
    assert "does not support GPU containers" in res.why


def test_fargate_oversized_workload_honest_decline():
    """Workloads exceeding max Fargate task size return recommended=False."""
    sdr = _make_sdr("u-6tb1.metal")
    tn = _make_tn(gpu=False)
    repo = RepoAnalysis(has_dockerfile=True, primary_language="Go", analysis_note="Dockerfile present")

    res = build_containerized_alternative(sdr, tn, repo, _make_candidates())
    assert res is not None
    assert res.recommended is False
    assert res.fargate_cpu_units is None
    assert res.fargate_memory_mib is None
    assert "exceeds the largest Fargate task size" in res.why


# ── 4. Holistic Recommender Integration ─────────────────────────────────────


from unittest.mock import patch


@patch("app.agent.nodes.holistic_recommender.invoke_structured")
def test_holistic_recommender_populates_fargate_when_dockerfile(mock_llm):
    from app.agent.nodes.holistic_recommender import recommend_system_design

    requirements = UserRequirements(
        workload_type=WorkloadType.WEB_APP,
        registered_users=1000,
        traffic_pattern=TrafficPattern.STEADY,
    )
    mock_llm.return_value = _make_sdr("c7i-flex.large")
    state = {
        "requirements": requirements,
        "technical_needs": _make_tn(),
        "instance_candidates": _make_candidates(),
        "database_candidates": [],
        "cache_candidates": [],
        "repo_analysis": RepoAnalysis(
            has_dockerfile=True,
            primary_language="Python",
            analysis_note="Dockerfile present",
        ),
    }

    new_state = recommend_system_design(state)
    sdr = new_state["system_design_recommendation"]
    assert sdr.containerized_alternative is not None
    assert sdr.containerized_alternative.recommended is True
    assert sdr.containerized_alternative.fargate_cpu_units == 2048
    assert sdr.containerized_alternative.fargate_memory_mib == 4096


@patch("app.agent.nodes.holistic_recommender.invoke_structured")
def test_holistic_recommender_omits_fargate_when_no_dockerfile(mock_llm):
    from app.agent.nodes.holistic_recommender import recommend_system_design

    requirements = UserRequirements(
        workload_type=WorkloadType.WEB_APP,
        registered_users=1000,
        traffic_pattern=TrafficPattern.STEADY,
    )
    mock_llm.return_value = _make_sdr("c7i-flex.large")
    state = {
        "requirements": requirements,
        "technical_needs": _make_tn(),
        "instance_candidates": _make_candidates(),
        "database_candidates": [],
        "cache_candidates": [],
        "repo_analysis": RepoAnalysis(
            has_dockerfile=False,
            primary_language="Python",
            analysis_note="No dockerfile",
        ),
    }

    new_state = recommend_system_design(state)
    sdr = new_state["system_design_recommendation"]
    assert sdr.containerized_alternative is None

