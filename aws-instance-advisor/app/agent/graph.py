"""
LangGraph definition wiring the full V2 flow: requirement collection
with a loop for missing info, system design reasoning, live compute,
database, and cache research, and holistic recommendation.
"""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from app.agent.nodes.cache_researcher import research_cache
from app.agent.nodes.consensus_check import consensus_check
from app.agent.nodes.database_researcher import research_database
from app.agent.nodes.grounding_check import grounding_check
from app.agent.nodes.holistic_recommender import holistic_recommend
from app.agent.nodes.instance_researcher import research_instances
from app.agent.nodes.recommender import recommend_instance
from app.agent.nodes.repo_analyzer import analyze_repository
from app.agent.nodes.requirement_collector import collect_requirements
from app.agent.nodes.requirement_validator import validate_requirements
from app.agent.nodes.system_design_reasoner import reason_system_design
from app.agent.nodes.terraform_generator import generate_terraform
from app.agent.state import AgentState


def _needs_more_info(state: AgentState) -> str:
    return "ask_user" if state.get("next_question") else "proceed"


def _should_run_consensus(state: AgentState) -> str:
    """Conditional router after grounding_check.

    Returns "consensus" only when the caller explicitly opted in via the
    API's ``consensus: true`` flag (stored as ``consensus_requested`` in
    graph state).  Otherwise the consensus node is never invoked — no
    extra LLM call, no extra latency.
    """
    return "consensus" if state.get("consensus_requested") else "skip"


def build_graph():
    graph = StateGraph(AgentState)

    graph.add_node("collect_requirements", collect_requirements)
    graph.add_node("analyze_repository", analyze_repository)
    graph.add_node("validate_requirements", validate_requirements)
    graph.add_node("reason_system_design", reason_system_design)
    graph.add_node("research_instances", research_instances)
    graph.add_node("research_database", research_database)
    graph.add_node("research_cache", research_cache)
    graph.add_node("holistic_recommend", holistic_recommend)
    graph.add_node("grounding_check", grounding_check)
    graph.add_node("consensus_check", consensus_check)
    graph.add_node("generate_terraform", generate_terraform)

    graph.set_entry_point("collect_requirements")
    graph.add_edge("collect_requirements", "analyze_repository")
    graph.add_edge("analyze_repository", "validate_requirements")

    graph.add_conditional_edges(
        "validate_requirements",
        _needs_more_info,
        {"ask_user": END, "proceed": "reason_system_design"},
    )

    graph.add_edge("reason_system_design", "research_instances")
    graph.add_edge("research_instances", "research_database")
    graph.add_edge("research_database", "research_cache")
    graph.add_edge("research_cache", "holistic_recommend")
    graph.add_edge("holistic_recommend", "grounding_check")

    # Consensus is strictly opt-in: when the flag is absent the
    # consensus_check node is never invoked.
    graph.add_conditional_edges(
        "grounding_check",
        _should_run_consensus,
        {"consensus": "consensus_check", "skip": "generate_terraform"},
    )
    graph.add_edge("consensus_check", "generate_terraform")
    graph.add_edge("generate_terraform", END)

    return graph.compile()


def build_v1_graph():
    """Preserved V1 graph definition for backward compatibility and V1 e2e tests."""
    graph = StateGraph(AgentState)

    graph.add_node("collect_requirements", collect_requirements)
    graph.add_node("validate_requirements", validate_requirements)
    graph.add_node("reason_system_design", reason_system_design)
    graph.add_node("research_instances", research_instances)
    graph.add_node("recommend_instance", recommend_instance)

    graph.set_entry_point("collect_requirements")
    graph.add_edge("collect_requirements", "validate_requirements")

    graph.add_conditional_edges(
        "validate_requirements",
        _needs_more_info,
        {"ask_user": END, "proceed": "reason_system_design"},
    )

    graph.add_edge("reason_system_design", "research_instances")
    graph.add_edge("research_instances", "recommend_instance")
    graph.add_edge("recommend_instance", END)

    return graph.compile()