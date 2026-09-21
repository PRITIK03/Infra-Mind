"""
Shared LangGraph state for the AWS Instance Advisor agent.
"""

from __future__ import annotations

from typing import TypedDict

from app.models.schemas import (
    CacheCandidate,
    DatabaseCandidate,
    InstanceCandidate,
    InstanceRecommendation,
    RepoAnalysis,
    SystemDesignRecommendation,
    TechnicalNeeds,
    UserRequirements,
)


class AgentState(TypedDict):
    requirements: UserRequirements
    latest_user_message: str | None
    next_question: str | None
    pending_field: str | None
    repo_analysis: RepoAnalysis | None
    repo_analysis_note: str | None
    technical_needs: TechnicalNeeds | None
    instance_candidates: list[InstanceCandidate] | None
    database_candidates: list[DatabaseCandidate] | None
    cache_candidates: list[CacheCandidate] | None
    recommendation: InstanceRecommendation | None
    system_design_recommendation: SystemDesignRecommendation | None
    terraform_files: dict[str, str] | None
    # Opt-in multi-model consensus flag.  Set from the API's `consensus: true`
    # request field (default False).  When False the consensus_check graph
    # node is never even invoked — consensus costs an extra full LLM call,
    # so it must never run by accident.
    consensus_requested: bool