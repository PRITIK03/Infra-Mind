"""
Backwards-compatibility shim — job models and store now live in
``app.api.job_store``.

Historical note: this module originally contained the in-memory JobStore
implementation directly.  That implementation moved to
``app.api.job_store.InMemoryJobStore`` alongside the Redis-backed
``RedisJobStore``; this module re-exports the public names so existing
imports (``from app.api.jobs import Job, JobStore, ...``) keep working
unchanged across the codebase and test suite.
"""

from __future__ import annotations

from app.api.job_store import (
    InMemoryJobStore,
    Job,
    JobRecord,
    JobStatus,
    JobStoreBackend,
    RedisJobStore,
    build_job_store,
)

# ``JobStore`` is the historical name for the in-memory store; keep it as
# an alias so older imports continue to resolve.
JobStore = InMemoryJobStore

__all__ = [
    "InMemoryJobStore",
    "Job",
    "JobRecord",
    "JobStatus",
    "JobStore",
    "JobStoreBackend",
    "RedisJobStore",
    "STAGE_LABELS",
    "build_job_store",
    "label_for_node",
]


STAGE_LABELS: dict[str, str] = {
    "collect_requirements": "Collecting requirements",
    "analyze_repository": "Analyzing repository",
    "validate_requirements": "Validating requirements",
    "reason_system_design": "Reasoning about system design",
    "research_instances": "Researching compute options",
    "research_database": "Researching database options",
    "research_cache": "Researching cache options",
    "holistic_recommend": "Building final recommendation",
    "grounding_check": "Checking recommendation consistency",
    "consensus_check": "Cross-checking with a second model",
    "generate_terraform": "Generating Terraform",
}


def label_for_node(node_name: str) -> str:
    """Return a human-readable stage label for a LangGraph node name."""
    return STAGE_LABELS.get(node_name, node_name.replace("_", " ").title())
