"""
Opt-in multi-model consensus node.

Runs AFTER grounding_check and BEFORE generate_terraform — but ONLY when the
caller explicitly requested it (``consensus_requested`` in graph state, set
from the API's ``consensus: true`` request flag).  Consensus costs exactly
one additional holistic-recommend LLM call, so it must never run by default.

Design constraint (cost-conscious scoping)
------------------------------------------
Requirement collection, system-design reasoning, and live-data research are
NOT re-run: they produce the same technical_needs and candidate data
regardless of which model reasons about them.  Only the final
holistic_recommend step runs twice — once against the primary model
(already done earlier in the graph) and once here against the consensus
model — using the identical technical_needs/candidates as input to both.
Total extra cost: exactly one LLM call, never a doubled pipeline.

The PRIMARY model's recommendation remains the deliverable: consensus is
supplementary insight attached to it, and Terraform generation, grounding
results, and cost estimates are untouched.

Agreement is computed DETERMINISTICALLY by comparing instance_type / engine /
load_balancer_type strings across the two SystemDesignRecommendation
objects (0 = full, 1-2 = partial, 3+ = significant_disagreement).  No third
LLM call is used to judge similarity — that would defeat both the cost
budget and the deterministic-comparison principle.

Failure policy: this node NEVER raises.  Consensus is advisory; if the
second call fails, or no consensus model is configured, the run proceeds
with a consensus_result that explains what happened (enabled=False + note).
"""

from __future__ import annotations

import logging

from app.agent.nodes.holistic_recommender import (
    HolisticRecommendationError,
    build_system_design_recommendation,
)
from app.agent.state import AgentState
from app.config import get_llm_settings
from app.models.schemas import (
    ConsensusDisagreement,
    ConsensusResult,
    SystemDesignRecommendation,
)

logger = logging.getLogger(__name__)

# Agreement thresholds over the four compared tiers
# (compute, database, cache, load_balancer).
_SIGNIFICANT_DISAGREEMENT_MIN = 3


def _choice_compute(rec: SystemDesignRecommendation) -> str:
    return rec.compute.recommended_instance


def _choice_database(rec: SystemDesignRecommendation) -> str:
    db = rec.database
    if not db.needed:
        return "not needed"
    engine = (db.engine_suggestion or "").strip() or "unknown engine"
    instance = (db.recommended_instance or "").strip() or "unknown instance"
    return f"{instance}/{engine}"


def _choice_cache(rec: SystemDesignRecommendation) -> str:
    cache = rec.cache
    if not cache.needed:
        return "not needed"
    engine = str(cache.engine) if cache.engine is not None else "unknown engine"
    instance = (cache.recommended_instance or "").strip() or "unknown instance"
    return f"{instance}/{engine}"


def _choice_load_balancer(rec: SystemDesignRecommendation) -> str:
    lb = rec.load_balancer
    if not lb.needed:
        return "not needed"
    return (lb.load_balancer_type or "").strip() or "unknown type"


_TIER_CHOOSERS = (
    ("compute", _choice_compute),
    ("database", _choice_database),
    ("cache", _choice_cache),
    ("load_balancer", _choice_load_balancer),
)


def compare_recommendations(
    primary: SystemDesignRecommendation,
    secondary: SystemDesignRecommendation,
    *,
    primary_model: str,
    secondary_model: str,
) -> ConsensusResult:
    """Deterministically compare two recommendations tier-by-tier.

    Pure function (no LLM, no I/O) — safe to unit test exhaustively.
    """
    agreements: list[str] = []
    disagreements: list[ConsensusDisagreement] = []

    for tier, chooser in _TIER_CHOOSERS:
        primary_choice = chooser(primary)
        secondary_choice = chooser(secondary)
        if primary_choice == secondary_choice:
            agreements.append(tier)
        else:
            disagreements.append(
                ConsensusDisagreement(
                    tier=tier,
                    primary_choice=primary_choice,
                    secondary_choice=secondary_choice,
                )
            )

    n = len(disagreements)
    if n == 0:
        level = "full"
    elif n >= _SIGNIFICANT_DISAGREEMENT_MIN:
        level = "significant_disagreement"
    else:
        level = "partial"

    return ConsensusResult(
        enabled=True,
        primary_model=primary_model,
        secondary_model=secondary_model,
        agreement_level=level,  # type: ignore[arg-type]
        agreements=agreements,
        disagreements=disagreements,
    )


def _declined_result(primary_model: str, note: str) -> ConsensusResult:
    """ConsensusResult for the graceful-decline path (enabled=False)."""
    return ConsensusResult(
        enabled=False,
        primary_model=primary_model,
        secondary_model="",
        note=note,
    )


def consensus_check(state: AgentState) -> AgentState:
    """LangGraph node: run the second opinion and attach the comparison.

    Never raises — consensus is advisory.  Any failure (or missing config)
    produces an enabled=False result with a human-readable note, and the
    primary recommendation passes through untouched.
    """
    primary: SystemDesignRecommendation | None = state.get(
        "system_design_recommendation"
    )
    if primary is None:
        logger.debug("consensus_check: no primary recommendation; skipping.")
        return state

    if not state.get("consensus_requested"):
        return state

    settings = get_llm_settings()
    secondary_model = settings.effective_consensus_model()

    if secondary_model is None:
        note = (
            "Consensus mode was requested, but no consensus model is configured. "
            "Set CONSENSUS_MODEL, or configure LLM_FALLBACK_MODELS (its first "
            "entry is used as the consensus model). No extra LLM call was made."
        )
        logger.info("consensus_check declined: %s", note)
        state["system_design_recommendation"] = primary.model_copy(
            update={"consensus_result": _declined_result(settings.model_name, note)}
        )
        return state

    try:
        secondary = build_system_design_recommendation(
            state, model_override=secondary_model
        )
    except HolisticRecommendationError as exc:
        note = (
            f"Consensus second-opinion call failed ({exc}); "
            "the primary recommendation is unchanged."
        )
        logger.warning("consensus_check second call failed: %s", exc)
        state["system_design_recommendation"] = primary.model_copy(
            update={"consensus_result": _declined_result(settings.model_name, note)}
        )
        return state
    except Exception:  # pragma: no cover - defensive, never blocks the run
        note = (
            "Consensus second-opinion call failed unexpectedly; "
            "the primary recommendation is unchanged."
        )
        logger.exception("consensus_check unexpected failure")
        state["system_design_recommendation"] = primary.model_copy(
            update={"consensus_result": _declined_result(settings.model_name, note)}
        )
        return state

    result = compare_recommendations(
        primary,
        secondary,
        primary_model=settings.model_name,
        secondary_model=secondary_model,
    )
    state["system_design_recommendation"] = primary.model_copy(
        update={"consensus_result": result}
    )
    return state
