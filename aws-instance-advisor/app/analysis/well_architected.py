"""
Deterministic Well-Architected-style review.

Produces a list of WellArchitectedFinding objects from data the pipeline has
ALREADY produced — fields on SystemDesignRecommendation plus TechnicalNeeds.
There is deliberately no LLM call here: every finding is a direct consequence
of a specific field value, so the output is reproducible and each rule can be
unit-tested in isolation with plain Python objects.

Design rules
------------
- One small predicate function per finding.  If the predicate is false the
  rule contributes nothing.  Predicates never raise on partial data — they
  are written against Optional/defaulted fields and simply decline.
- No rule may require interpretation, domain judgement, or a "look at the
  prose and decide" step.  If a check would need that, it does not belong
  here (it would belong in the grounding check, which does use an LLM).
- Findings are emitted in a fixed rule order so output is stable.

Rules deliberately NOT implemented
----------------------------------
- Multi-AZ / cross-AZ redundancy for the database tier: the pipeline does not
  track any multi-AZ field on DatabaseRecommendation or TechnicalNeeds, so
  there is no data to test.  Fabricating a multi-AZ status would be exactly
  the kind of guess this module exists to avoid, so the rule is omitted
  rather than inferred.
"""

from __future__ import annotations

from app.models.schemas import (
    ResourceProfile,
    SystemDesignRecommendation,
    TechnicalNeeds,
    WellArchitectedFinding,
)


# ── Individual rules ────────────────────────────────────────────────────────
# Each returns a finding, or None when the underlying condition is absent.


def _rule_no_compute_redundancy(
    sdr: SystemDesignRecommendation, tn: TechnicalNeeds
) -> WellArchitectedFinding | None:
    """min_instances == 1 → a single compute instance, no redundancy."""
    if tn.min_instances != 1:
        return None
    return WellArchitectedFinding(
        pillar="reliability",
        severity="warning",
        message=(
            f"min_instances is {tn.min_instances}: the compute tier runs a "
            "single instance, so an instance failure takes the workload "
            "offline until it is replaced."
        ),
    )


def _rule_max_instances_without_load_balancer(
    sdr: SystemDesignRecommendation, tn: TechnicalNeeds
) -> WellArchitectedFinding | None:
    """max_instances > 1 but no load balancer → nothing distributes traffic."""
    if tn.max_instances <= 1 or sdr.load_balancer.needed:
        return None
    return WellArchitectedFinding(
        pillar="performance_efficiency",
        severity="warning",
        message=(
            f"max_instances is {tn.max_instances} but load_balancer.needed is "
            "False: scaling beyond one instance would not distribute incoming "
            "traffic across them."
        ),
    )


def _rule_single_instance_no_load_balancer(
    sdr: SystemDesignRecommendation, tn: TechnicalNeeds
) -> WellArchitectedFinding | None:
    """min_instances == 1 and no load balancer → single contention point."""
    if sdr.load_balancer.needed or tn.min_instances != 1:
        return None
    return WellArchitectedFinding(
        pillar="performance_efficiency",
        severity="info",
        message=(
            "load_balancer.needed is False with min_instances == 1: all traffic "
            "reaches a single instance, which is the first point of contention "
            "under a load spike."
        ),
    )


def _rule_grounding_failed(
    sdr: SystemDesignRecommendation, tn: TechnicalNeeds
) -> WellArchitectedFinding | None:
    """grounding_passed is explicitly False → unresolved contradictions."""
    if sdr.grounding_passed is not False:
        return None
    notes = [n for n in (sdr.grounding_notes or []) if n.strip()]
    detail = "; ".join(notes) if notes else "no issue detail was recorded"
    return WellArchitectedFinding(
        pillar="operational_excellence",
        severity="warning",
        message=(
            "The consistency check did not pass after its bounded retry. "
            f"Unresolved issues: {detail}"
        ),
    )


def _rule_security_groups_are_baseline(
    sdr: SystemDesignRecommendation, tn: TechnicalNeeds
) -> WellArchitectedFinding | None:
    """
    Mirror the Terraform header's security warning.

    Always emitted: the generated Terraform always contains the same baseline
    security groups and placeholder DB credentials, so this is a property of
    the deliverable rather than of any particular workload.  Surfacing it here
    means it is visible without opening the Terraform tab.
    """
    return WellArchitectedFinding(
        pillar="security",
        severity="info",
        message=(
            "The generated Terraform includes baseline security groups and a "
            "placeholder database password — tighten the rules and move the "
            "credential to a secret manager before applying."
        ),
    )


def _rule_cache_absent_for_read_heavy_profile(
    sdr: SystemDesignRecommendation, tn: TechnicalNeeds
) -> WellArchitectedFinding | None:
    """
    Memory-bound profile but no cache tier.

    MEMORY_BOUND is the only read-heavy signal actually tracked: the pipeline
    records no read/write ratio or query pattern, so the rule keys off that
    single field rather than guessing from prose.
    """
    if sdr.cache.needed or tn.resource_profile != ResourceProfile.MEMORY_BOUND:
        return None
    return WellArchitectedFinding(
        pillar="cost_optimization",
        severity="info",
        message=(
            "resource_profile is memory_bound but cache.needed is False: a "
            "cache tier could absorb repeated reads and reduce the instance "
            "size the workload needs."
        ),
    )


def _rule_cost_not_estimated(
    sdr: SystemDesignRecommendation, tn: TechnicalNeeds
) -> WellArchitectedFinding | None:
    """estimated_cost is None → no monthly cost could be computed."""
    if sdr.estimated_cost is not None:
        return None
    return WellArchitectedFinding(
        pillar="cost_optimization",
        severity="info",
        message=(
            "estimated_cost is None: live pricing was unavailable for at least "
            "one needed tier, so no monthly cost estimate accompanies this "
            "recommendation."
        ),
    )


def _rule_repo_context_unavailable(
    sdr: SystemDesignRecommendation, tn: TechnicalNeeds
) -> WellArchitectedFinding | None:
    """repo_analysis_note present → repo analysis was requested but skipped."""
    note = (sdr.repo_analysis_note or "").strip()
    if not note:
        return None
    return WellArchitectedFinding(
        pillar="operational_excellence",
        severity="info",
        message=(
            "Repository analysis did not contribute to this recommendation: "
            f"{note}"
        ),
    )


# Fixed evaluation order — keeps output stable across runs and makes the
# findings list diff-friendly.
_RULES = (
    _rule_no_compute_redundancy,
    _rule_max_instances_without_load_balancer,
    _rule_single_instance_no_load_balancer,
    _rule_grounding_failed,
    _rule_security_groups_are_baseline,
    _rule_cache_absent_for_read_heavy_profile,
    _rule_cost_not_estimated,
    _rule_repo_context_unavailable,
)


def build_well_architected_review(
    sdr: SystemDesignRecommendation,
    technical_needs: TechnicalNeeds,
) -> list[WellArchitectedFinding]:
    """
    Run the deterministic rule set and return the findings that fired.

    Pure function: no LLM call, no I/O, no mutation of its inputs.  An empty
    list is a legitimate result meaning no rule matched — never an error.
    """
    findings: list[WellArchitectedFinding] = []
    for rule in _RULES:
        finding = rule(sdr, technical_needs)
        if finding is not None:
            findings.append(finding)
    return findings
