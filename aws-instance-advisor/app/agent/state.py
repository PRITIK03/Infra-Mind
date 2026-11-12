"""
Shared LangGraph state for the AWS Instance Advisor agent.
"""

from __future__ import annotations

from typing import NotRequired, TypedDict

from app.models.repository import RepositoryProgress, RepositoryRef, RepositoryReport

from app.models.schemas import (
    CacheCandidate,
    DatabaseCandidate,
    InstanceCandidate,
    InstanceRecommendation,
    RepoAnalysis,
    RdsEngine,
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
    # The HTTP worker supplies validated repository input and keeps the
    # immutable scan across graph passes. Older CLI states use the MCP path.
    repository_managed: NotRequired[bool]
    repository_ref: NotRequired[RepositoryRef | None]
    repository_progress: NotRequired[RepositoryProgress | None]
    repository_report: NotRequired[RepositoryReport | None]
    repository_assumptions: NotRequired[list[str]]
    repository_stated_requirements: NotRequired[UserRequirements]
    target_rds_engine: NotRequired[RdsEngine | None]
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
