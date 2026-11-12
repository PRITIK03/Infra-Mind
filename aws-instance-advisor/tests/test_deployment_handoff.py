"""Exercise the deployment handoff through the completed export, without AWS/model calls."""

import pytest

from app.agent.nodes.terraform_generator import generate_terraform
from app.api.repository_share import repository_share_result
from app.models.repository import RepositoryFinding, RepositoryRef, RepositoryReport
from app.models.schemas import SystemDesignRecommendation, TechnicalNeeds, UserRequirements


def _state(workload="api_service", database="PostgreSQL"):
    rds = database == "PostgreSQL"
    return {
        "requirements": UserRequirements(workload_type=workload, database_engine=database),
        "technical_needs": TechnicalNeeds(
            estimated_concurrency=100, resource_profile="balanced", traffic_pattern="bursty",
            requires_gpu=False, scaling_recommendation="horizontal", min_instances=2, max_instances=4,
            needs_database=rds, needs_cache=False, load_balancer_needed=workload != "batch_processing",
            reasoning="Scenario fixture",
        ),
        "system_design_recommendation": SystemDesignRecommendation(
            compute={"recommended_instance": "m5.large", "why": "Capacity estimate", "confidence": "medium"},
            database={"needed": rds, "recommended_instance": "db.t3.medium" if rds else None,
                      "engine_suggestion": "PostgreSQL" if rds else None, "why": "Selected persistence", "confidence": "medium"},
            cache={"needed": False, "why": "No cache", "confidence": "high"},
            load_balancer={"needed": workload != "batch_processing", "load_balancer_type": "Application Load Balancer", "why": "Ingress"},
            architecture_summary="Scenario fixture", grounding_passed=True,
        ),
    }


def test_api_handoff_matches_resources_and_names_missing_deployment_work():
    state = generate_terraform(_state())
    handoff = state["system_design_recommendation"].deployment_handoff
    actions = {action.id: action for action in handoff.actions}
    assert any("RDS PostgreSQL" in resource for resource in handoff.generated_resources)
    assert 'engine = "postgres"' in state["terraform_files"]["main.tf"]
    assert {"network", "identity", "application", "database", "scaling", "ingress", "operations", "cost"} <= actions.keys()
    assert "no scaling policy" in actions["scaling"].detail
    assert "without your application" in actions["application"].detail
    assert "CloudFormation export is not available" in actions["export-scope"].detail
    assert "single-AZ" in actions["database"].detail
    assert len(actions) == len(handoff.actions)
    assert state["system_design_recommendation"].model_dump(mode="json")["deployment_handoff"]["actions"]


@pytest.mark.parametrize(("workload", "database", "expected", "excluded"), [
    ("api_service", "external", "external-database", "database"),
    ("batch_processing", "none", "batch", "ingress"),
    ("ml_inference", "none", "inference", "database"),
    ("web_app", "MongoDB", "separate-database", "database"),
])
def test_handoff_respects_workload_and_persistence(workload, database, expected, excluded):
    state = generate_terraform(_state(workload, database))
    handoff = state["system_design_recommendation"].deployment_handoff
    ids = {action.id for action in handoff.actions}
    assert expected in ids
    assert excluded not in ids
    assert not any("RDS " in resource for resource in handoff.generated_resources)
    assert 'resource "aws_db_instance"' not in state["terraform_files"]["main.tf"]
    if workload == "batch_processing":
        assert not any("Load Balancer" in resource for resource in handoff.generated_resources)
        assert "scaling" in ids


@pytest.mark.parametrize("store", ["SQLite", "MongoDB", "DynamoDB"])
@pytest.mark.parametrize("explicit", [None, "external", "none"])
def test_repository_persistence_is_carried_into_handoff_with_user_precedence(store, explicit):
    state = _state(database=explicit)
    state["repository_report"] = RepositoryReport(
        repository=RepositoryRef(owner="example", name="workload"),
        commit_sha="a" * 40, coverage="complete", files_discovered=2, files_analyzed=2,
        configured_databases=[store],
    )
    handoff = generate_terraform(state)["system_design_recommendation"].deployment_handoff
    actions = {action.id: action for action in handoff.actions}
    if explicit is None:
        assert store in actions["separate-database"].title
    else:
        assert "separate-database" not in actions
        assert ("external-database" in actions) == (explicit == "external")


def test_missing_required_database_and_unverified_output_are_explicit():
    state = _state(database="external")
    state["technical_needs"].needs_database = True
    state["system_design_recommendation"].grounding_passed = None
    result = generate_terraform(state)["system_design_recommendation"]
    ids = {action.id for action in result.deployment_handoff.actions}
    assert {"unsized-database", "consistency"} <= ids


def test_repository_findings_drive_actions_without_leaking_through_public_share():
    state = _state()
    state["repository_report"] = RepositoryReport(
        repository=RepositoryRef(owner="example", name="internal"),
        commit_sha="a" * 40, coverage="partial", files_discovered=3, files_analyzed=2,
        skipped={"unreadable": 1}, local_inference=True,
        findings=[RepositoryFinding(category="security", title="Exposed credential",
                                    action="Rotate it", severity="high", path="private-name.py")],
    )
    result = generate_terraform(state)["system_design_recommendation"]
    ids = {action.id for action in result.deployment_handoff.actions}
    assert {"repository-security", "repository-coverage", "inference"} <= ids
    serialized = {"system_design_recommendation": result.model_dump(mode="json")}
    shared = repository_share_result(serialized)
    assert "deployment_handoff" not in shared["system_design_recommendation"]
    assert "private-name" not in str(shared)
