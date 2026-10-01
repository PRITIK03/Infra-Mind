"""Dev/E2E helper: serve the API with seeded completed jobs.

No LLM or live-data calls are made — the result dicts below ARE the fixtures.
Doubles as the fixture factory for the Playwright E2E suite (see
aws-advisor-ui/e2e): the seed shapes here cover the result variants the UI
renders (full stack / no database / compute only).

Usage: python scripts/dev_seed_and_serve.py  (Ctrl+C to stop)
"""

from __future__ import annotations

import os

# Config validation runs at import time; satisfy it with dummies.
os.environ.setdefault("API_KEY", "dummy-key")
os.environ.setdefault("BASE_URL", "https://example.com/v1")
os.environ.setdefault("MODEL_NAME", "dummy-model")
os.environ.setdefault("VANTAGE_API_KEY", "dummy-vantage-key")
os.environ.setdefault("CORS_ALLOWED_ORIGIN", "http://localhost:3000")
os.environ.setdefault("PORT", "8000")
os.environ.setdefault("LOG_FORMAT", "text")

import time

import uvicorn

from app.api.job_store import Job
from app.api.main import app
from app.api.runtime import jobs

# Stable ids the E2E suite asserts against (aws-advisor-ui/e2e/smoke.spec.ts).
FULL_STACK_ID = "seed-e2e-full-stack"
NO_DB_ID = "seed-e2e-no-db"
COMPUTE_ONLY_ID = "seed-e2e-compute-only"
OG_CHECK_ID = "seed-visual-check-0001"


def _base_sdr() -> dict:
    return {
        "architecture_summary": (
            "Two-tier web service behind an ALB: one auto-scaling compute "
            "tier, one relational database, one Redis cache for hot reads."
        ),
        "compute": {
            "recommended_instance": "m5.large",
            "why": "Balanced general-purpose compute for a steady API workload.",
            "assumptions": ["Traffic is mostly read-heavy API calls."],
            "confidence": "high",
        },
        "database": {
            "needed": True,
            "recommended_instance": "db.t3.medium",
            "engine_suggestion": "PostgreSQL",
            "why": "Standard relational storage with mature tooling.",
            "assumptions": [],
            "confidence": "medium",
        },
        "cache": {
            "needed": True,
            "recommended_instance": "cache.t3.micro",
            "engine": "Redis",
            "why": "Session cache and hot reads.",
            "assumptions": [],
            "confidence": "high",
        },
        "load_balancer": {"needed": False, "why": "Single instance is sufficient."},
        "well_architected_review": [
            {
                "pillar": "operational_excellence",
                "severity": "info",
                "message": "Infrastructure is expressed as reviewed Terraform.",
            },
            {
                "pillar": "cost_optimization",
                "severity": "warning",
                "message": "Rightsize after two weeks of real traffic data.",
            },
        ],
        "estimated_cost": {"total_monthly_low": 120.0, "total_monthly_high": 150.0},
    }


def _full_stack_result() -> dict:
    # terraform_files and technical_needs are top-level JobResult fields
    # (the same shape the real pipeline produces), not SDR fields.
    return {
        "system_design_recommendation": _base_sdr(),
        "terraform_files": {
            "main.tf": (
                'provider "aws" {\n  region = "us-east-1"\n}\n\n'
                'resource "aws_instance" "app" {\n  instance_type = "m5.large"\n'
                '  ami           = "ami-placeholder"\n}\n'
            ),
            "outputs.tf": 'output "instance_id" {\n  value = aws_instance.app.id\n}\n',
        },
        "technical_needs": {
            "scaling_recommendation": "Start at 2 instances, scale on CPU > 60%.",
            "concurrency_expectation": "About 2,000 concurrent users at peak.",
        },
    }


def _no_db_result() -> dict:
    sdr = _base_sdr()
    sdr["database"] = {
        "needed": False,
        "why": "Stateless API — session data lives in the cache tier.",
        "assumptions": [],
        "confidence": "high",
    }
    sdr["cache"] = {
        "needed": False,
        "why": "Working set fits in instance memory.",
        "assumptions": [],
        "confidence": "medium",
    }
    sdr["estimated_cost"] = {"total_monthly_low": 70.0, "total_monthly_high": 85.0}
    return {"system_design_recommendation": sdr}


def _compute_only_result() -> dict:
    sdr = _base_sdr()
    sdr["database"] = {
        "needed": False,
        "why": "No persistence required.",
        "assumptions": [],
        "confidence": "high",
    }
    sdr["cache"] = {
        "needed": False,
        "why": "No cache required.",
        "assumptions": [],
        "confidence": "high",
    }
    sdr["load_balancer"] = {
        "needed": True,
        "why": "Two instances for availability.",
    }
    del sdr["estimated_cost"]
    return {"system_design_recommendation": sdr}


def _og_check_result() -> dict:
    """The original single-purpose OG verification fixture, kept stable."""
    return {
        "system_design_recommendation": {
            "architecture_summary": "Two-tier web service behind an ALB.",
            "compute": {
                "recommended_instance": "m5.large",
                "why": "Balanced general-purpose compute for a steady API workload.",
                "assumptions": ["Traffic is mostly read-heavy API calls."],
                "confidence": "high",
            },
            "database": {
                "needed": True,
                "recommended_instance": "db.t3.medium",
                "engine_suggestion": "PostgreSQL",
                "why": "Standard relational storage with mature tooling.",
                "assumptions": [],
                "confidence": "medium",
            },
            "cache": {
                "needed": True,
                "recommended_instance": "cache.t3.micro",
                "engine": "Redis",
                "why": "Session cache and hot reads.",
                "assumptions": [],
                "confidence": "high",
            },
            "load_balancer": {"needed": False, "why": "Single instance is sufficient."},
            "estimated_cost": {"total_monthly_low": 120.0, "total_monthly_high": 150.0},
        }
    }


def seed_jobs() -> list[str]:
    """Factory: seed every fixture job into the process store; returns ids."""
    fixtures = {
        FULL_STACK_ID: _full_stack_result(),
        NO_DB_ID: _no_db_result(),
        COMPUTE_ONLY_ID: _compute_only_result(),
        OG_CHECK_ID: _og_check_result(),
    }
    for job_id, result in fixtures.items():
        jobs.put(
            Job(
                job_id=job_id,
                status="done",
                current_stage="Complete",
                state={},
                result=result,
            )
        )
    return list(fixtures)


if __name__ == "__main__":
    seeded = seed_jobs()
    for job_id in seeded:
        print(f"Seeded job {job_id} -> /api/share/{job_id}")
    # Give the store a beat, then serve — same entrypoint as production.
    time.sleep(0.1)
    print("Serving on http://127.0.0.1:8000 (Ctrl+C to stop)")
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")
