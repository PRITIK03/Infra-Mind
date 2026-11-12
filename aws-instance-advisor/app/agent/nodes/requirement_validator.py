"""
Requirement validator node.

Checks whether critical requirement fields are still missing and, if
so, prepares a follow-up question. If nothing critical is missing,
clears next_question so the graph can proceed to reasoning.
"""

from __future__ import annotations

from app.agent.state import AgentState
from app.models.schemas import TrafficPattern, WorkloadType

_FIELD_PROMPTS = {
    "workload_type": "What kind of application is this — a web app, an API service, batch processing, or ML inference?",
    "traffic_pattern": "Is traffic fairly steady throughout the day, or bursty with specific peak periods?",
}

_EXPECTED_SCALE_COMMON = (
    "For this workload, what is the expected scale? "
    "Provide one of: registered users, concurrent users, or peak RPS (requests per second)."
)

_EXPECTED_SCALE_BATCH = (
    "For this batch/backend workload, what is the expected scale? "
    "Provide one of: concurrent job/worker slots, or jobs processed per unit time."
)


def validate_requirements(state: AgentState) -> AgentState:
    requirements = state["requirements"]
    assumptions = []
    report = state.get("repository_report")
    if report is not None:
        updates = {}
        if requirements.workload_type is None and report.workload_type is not None:
            updates["workload_type"] = report.workload_type
            assumptions.append("Workload type was inferred from repository evidence.")
        workload = updates.get("workload_type", requirements.workload_type)
        if workload in (WorkloadType.WEB_APP, WorkloadType.API_SERVICE, WorkloadType.BATCH_PROCESSING) and not report.local_inference:
            if "expected_scale" in requirements.missing_critical_fields():
                if workload == WorkloadType.BATCH_PROCESSING:
                    updates["estimated_concurrent_users"] = 1
                    assumptions.append("Provisional sizing assumes one concurrent worker. Benchmark the workload before deployment.")
                else:
                    updates["requests_per_second"] = 10
                    assumptions.append("Provisional sizing assumes 10 peak requests per second. Benchmark the workload before deployment.")
            if requirements.traffic_pattern == TrafficPattern.UNKNOWN:
                updates["traffic_pattern"] = TrafficPattern.STEADY
                assumptions.append("Provisional sizing assumes steady traffic until peak and burst patterns are measured.")
        if updates:
            requirements = requirements.model_copy(update=updates)
    missing = requirements.missing_critical_fields()

    if not missing:
        if report is not None:
            state["repository_stated_requirements"] = state["requirements"].model_copy(
                update={"workload_type": requirements.workload_type},
            )
            state["requirements"] = requirements
            state["repository_assumptions"] = assumptions
        state["next_question"] = None
        state["pending_field"] = None
        return state

    field = missing[0]
    if field == "expected_scale":
        workload_type = requirements.workload_type
        if workload_type == WorkloadType.BATCH_PROCESSING:
            question = _EXPECTED_SCALE_BATCH
        else:
            question = _EXPECTED_SCALE_COMMON
    else:
        question = _FIELD_PROMPTS.get(
            field, f"Could you tell me more about {field.replace('_', ' ')}?"
        )

    state["pending_field"] = field
    state["next_question"] = question
    return state
