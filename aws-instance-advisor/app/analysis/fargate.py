"""
Deterministic ECS Fargate alternative sizing.

Offers a serverless container alternative to the EC2 compute tier, mapped
deterministically from the already-recommended EC2 instance's vCPU/memory to
the nearest valid Fargate task size that MEETS OR EXCEEDS both.  Rounding is
always up — a container under-provisioned relative to the EC2 baseline would
be a regression, not a valid alternative.

Sizing table (Linux, task-level CPU/memory)
-------------------------------------------
Copied verbatim from the AWS ECS developer guide — "Troubleshoot Amazon ECS
task definition invalid CPU or memory errors"
(docs.aws.amazon.com/AmazonECS/latest/developerguide/task-cpu-memory-error.html)
which lists the valid combinations task definitions must use, plus the
"Task CPU and memory" table in fargate-tasks-services.md.  Do not edit by
hand without re-checking that page; 8/16/32 vCPU tiers require Fargate
platform version 1.4.0 or later.

No LLM call, no I/O, no network — same design rules as well_architected.py.
"""

from __future__ import annotations

import math

from app.models.schemas import (
    ContainerizedAlternative,
    InstanceCandidate,
    RepoAnalysis,
    SystemDesignRecommendation,
    TechnicalNeeds,
)

# ── Verified AWS table ──────────────────────────────────────────────────────
# (cpu_units, ascending tuple of valid memory values in MiB).  Ranges from
# the docs are expanded to explicit steps so selection is exact:
#   1024: 2–8 GB in 1 GB steps      2048: 4–16 GB in 1 GB steps
#   4096: 8–30 GB in 1 GB steps     8192: 16–60 GB in 4 GB steps
#   16384: 32–120 GB in 8 GB steps  32768: discrete 60/120/244 GB only
_MIB_PER_GIB = 1024


def _gib_range(low_gib: int, high_gib: int, step_gib: int) -> tuple[int, ...]:
    return tuple(
        gib * _MIB_PER_GIB for gib in range(low_gib, high_gib + 1, step_gib)
    )


FARGATE_TASK_SIZES: tuple[tuple[int, tuple[int, ...]], ...] = (
    (256, (512, 1024, 2048)),
    (512, (1024, 2048, 3072, 4096)),
    (1024, _gib_range(2, 8, 1)),
    (2048, _gib_range(4, 16, 1)),
    (4096, _gib_range(8, 30, 1)),
    (8192, _gib_range(16, 60, 4)),
    (16384, _gib_range(32, 120, 8)),
    (32768, (60 * 1024, 120 * 1024, 244 * 1024)),
)


def nearest_fargate_task_size(vcpu: int, memory_gib: float) -> tuple[int, int] | None:
    """
    Map an EC2 instance's (vcpu, memory_gib) to the nearest Fargate task size.

    Returns (cpu_units, memory_mib) of the smallest valid task whose CPU is
    at least *vcpu* and whose memory is at least *memory_gib*, rounding UP on
    both axes.  Returns None when no Fargate tier can fit the workload (the
    largest task tops out at 32 vCPU / 244 GB).
    """
    if vcpu <= 0 or memory_gib <= 0:
        return None
    required_units = vcpu * 1024
    required_mib = math.ceil(memory_gib * _MIB_PER_GIB)

    for cpu_units, memories in FARGATE_TASK_SIZES:
        if cpu_units < required_units:
            continue
        for mib in memories:
            if mib >= required_mib:
                return cpu_units, mib
        # CPU fits but this tier's largest memory doesn't — try the next tier.
    return None


# ── Templated copy ──────────────────────────────────────────────────────────
# Fixed templates with only measured values interpolated — not LLM-generated.


def _why(*, cpu_units: int | None, memory_mib: int | None, instance_type: str) -> str:
    if cpu_units is not None and memory_mib is not None:
        return (
            "A Dockerfile was detected in the repository; ECS Fargate offers "
            "an equivalent serverless container alternative to the EC2-based "
            f"compute tier above ({instance_type}), sized to at least match its "
            f"vCPU and memory ({cpu_units} CPU units / {memory_mib} MiB)."
        )
    return (
        "A Dockerfile was detected in the repository, but the recommended "
        f"EC2 instance ({instance_type}) exceeds the largest Fargate task "
        "size (32 vCPU / 244 GB), so no equivalent container task can be offered."
    )


_TRADE_OFF = (
    "Fargate removes instance management entirely and bills per-second while "
    "tasks run, and each task scales independently — but you give up control "
    "over the underlying host, and task startup (image pull plus container "
    "boot) can add latency compared with an always-running EC2 instance."
)

_WHY_GPU = (
    "A Dockerfile was detected in the repository, but Fargate does not "
    "support GPU containers, and this workload requires GPU — no container "
    "alternative is offered."
)


def build_containerized_alternative(
    sdr: SystemDesignRecommendation,
    tn: TechnicalNeeds,
    repo_analysis: RepoAnalysis | None,
    compute_candidates: list[InstanceCandidate],
) -> ContainerizedAlternative | None:
    """
    Offer an ECS Fargate alternative for the compute tier when the workload is
    actually containerizable.

    Trigger: repo_analysis exists AND repo_analysis.has_dockerfile is True.
    Anything else returns None — the section is simply absent (no placeholder,
    no "not applicable" text).

    Pure function: no LLM call, no I/O, no mutation.
    """
    if repo_analysis is None or not repo_analysis.has_dockerfile:
        return None

    if tn.requires_gpu:
        return ContainerizedAlternative(
            recommended=False,
            fargate_cpu_units=None,
            fargate_memory_mib=None,
            why=_WHY_GPU,
            trade_off=_TRADE_OFF,
        )

    instance_type = sdr.compute.recommended_instance
    candidate = next(
        (c for c in compute_candidates if c.instance_type == instance_type), None
    )

    size = (
        nearest_fargate_task_size(candidate.vcpu, candidate.memory_gib)
        if candidate is not None
        else None
    )
    if size is None:
        return ContainerizedAlternative(
            recommended=False,
            fargate_cpu_units=None,
            fargate_memory_mib=None,
            why=_why(cpu_units=None, memory_mib=None, instance_type=instance_type),
            trade_off=_TRADE_OFF,
        )

    cpu_units, memory_mib = size
    return ContainerizedAlternative(
        recommended=True,
        fargate_cpu_units=cpu_units,
        fargate_memory_mib=memory_mib,
        why=_why(cpu_units=cpu_units, memory_mib=memory_mib, instance_type=instance_type),
        trade_off=_TRADE_OFF,
    )
