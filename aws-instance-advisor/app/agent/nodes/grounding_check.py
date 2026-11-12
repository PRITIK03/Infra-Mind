"""Check consistency, with one repair through the shared recommendation module.

A failed or unavailable check is visible in the result. A repair that violates
the catalog is discarded; the original catalog-validated recommendation survives.
Neither an unavailable auditor nor an invalid repair adds synthesis retries.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from app.agent.nodes.holistic_recommender import (
    HolisticRecommendationError,
    build_system_design_recommendation,
)
from app.agent.state import AgentState
from app.analysis.well_architected import build_well_architected_review
from app.llm.structured import StructuredOutputError, invoke_structured
from app.models.schemas import SystemDesignRecommendation, TechnicalNeeds

logger = logging.getLogger(__name__)


class GroundingResult(BaseModel):
    passed: bool = Field(description="True only when no concrete contradictions were found.")
    issues: list[str] = Field(
        default_factory=list,
        description="Specific contradictions, each under 120 characters. Empty on success.",
    )


_GROUNDING_PROMPT = """\
You are a consistency auditor for AWS architecture recommendations.
Identify CONCRETE contradictions between the recommendation and technical needs.

Check whether the summary and tier explanations agree with the enabled tiers,
resource profile, GPU requirement, and scaling range. A fixed min/max range does
not implement dynamic scaling. Load balancer need must agree with
technical_needs.load_balancer_needed, not be inferred from instance count:
multiple batch workers can consume a queue without a load balancer, and a single
web server can use one for managed ingress.

Do NOT flag reasonable sizing trade-offs, terse explanations, or anything that
requires facts absent from the inputs.

Technical needs:
{technical_needs}

System design recommendation:
{recommendation}

Return a GroundingResult JSON object. If no contradictions are found, return
{{"passed": true, "issues": []}}. Keep each issue description under 120 chars.
"""


def _run_grounding_check(
    sdr: SystemDesignRecommendation,
    tn: TechnicalNeeds,
) -> GroundingResult | None:
    prompt = _GROUNDING_PROMPT.format(
        technical_needs=tn.model_dump_json(indent=2),
        recommendation=sdr.model_dump_json(
            indent=2,
            exclude={"grounding_passed", "grounding_notes", "well_architected_review"},
        ),
    )
    try:
        result = invoke_structured(GroundingResult, prompt)
    except StructuredOutputError:
        logger.warning("Consistency check unavailable; leaving the result unverified.")
        return None
    if result.issues:
        result.passed = False
    return result


def grounding_check(state: AgentState) -> AgentState:
    sdr = state.get("system_design_recommendation")
    needs = state.get("technical_needs")
    if sdr is None or needs is None:
        return state

    result = _run_grounding_check(sdr, needs)
    if result is not None and not result.passed:
        issues = result.issues or ["The consistency check did not pass; review the recommendation."]
        try:
            repaired = build_system_design_recommendation(state, corrections=issues)
        except HolisticRecommendationError:
            logger.warning("Grounding repair failed validation; retaining the original recommendation.")
            result = GroundingResult(passed=False, issues=[
                *issues,
                "Repair could not be validated. The original recommendation was retained.",
            ])
        else:
            sdr = repaired.model_copy(update={"repo_analysis_note": sdr.repo_analysis_note})
            second_result = _run_grounding_check(sdr, needs)
            if second_result is None:
                result = None
                # Preserve unresolved issues until a check succeeds.
                sdr = sdr.model_copy(update={"grounding_notes": issues})
            else:
                result = second_result

    sdr = sdr.model_copy(update={
        "grounding_passed": result.passed if result is not None else None,
        "grounding_notes": (
            (result.issues if not result.passed else []) if result is not None
            else [*sdr.grounding_notes, "Consistency check unavailable. Review this recommendation before deployment."]
        ),
    })
    state["system_design_recommendation"] = sdr.model_copy(update={
        "well_architected_review": build_well_architected_review(sdr, needs),
    })
    return state
