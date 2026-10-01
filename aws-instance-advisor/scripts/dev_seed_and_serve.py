"""Throwaway dev helper: start the API with a seeded completed job so the
share route's real-data OG metadata/image can be verified in a browser.
No LLM or live-data calls are made — the result dict below IS the fixture.

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

import threading
import time

import uvicorn

from app.api.job_store import Job
from app.api.main import app
from app.api.runtime import jobs

SEED_JOB_ID = "seed-visual-check-0001"

SEED_RESULT = {
    "system_design_recommendation": {
        "architecture_summary": "Two-tier web service behind an ALB: one auto-scaling "
        "compute tier, one relational database, one Redis cache for hot reads.",
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


def seed() -> None:
    jobs.put(
        Job(
            job_id=SEED_JOB_ID,
            status="done",
            current_stage="Complete",
            state={},
            result=SEED_RESULT,
        )
    )
    print(f"Seeded job {SEED_JOB_ID} -> /api/share/{SEED_JOB_ID}")


if __name__ == "__main__":
    seed()
    # Give the store a beat, then serve — same entrypoint as production.
    time.sleep(0.1)
    print("Serving on http://127.0.0.1:8000 (Ctrl+C to stop)")
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")
