"""
One real end-to-end pipeline run including a public GitHub repo URL.

Run from the advisor workspace root with the backend .env configured:

    $env:GITHUB_MCP_TOKEN = <PAT>; .venv\\Scripts\\python.exe scripts\\e2e_repo_run.py

Flows through collect_requirements (regex repo_url detection) →
analyze_repository (live GitHub MCP) → validate_requirements →
reason_system_design, then answers at most two follow-ups automatically so
the run completes unattended. Prints the repo analysis and the final
technical needs / recommendation reasoning as real output.
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

from app.agent.graph import build_graph  # noqa: E402
from app.models.schemas import UserRequirements  # noqa: E402

INITIAL_MESSAGE = (
    "Real-time ML inference endpoint for image classification running the "
    "code at https://github.com/huggingface/sentence-transformers. About "
    "200 requests per second, needs GPU acceleration, traffic is steady."
)

# Boring, deterministic answers if the validator still asks anything back.
AUTO_ANSWERS = {
    "traffic_pattern": "steady",
    "expected_scale": "200 requests per second",
    "workload_type": "ML inference",
}

MAX_FOLLOWUPS = 2


def _summarize_state(state, label: str) -> None:
    print(f"\n===== {label} =====")
    req = state["requirements"]
    print(f"repo_url: {req.repo_url}")
    print(f"workload_type: {req.workload_type}")
    analysis = state.get("repo_analysis")
    if analysis is None:
        print("repo_analysis: None")
    else:
        print("repo_analysis:")
        print(analysis.model_dump_json(indent=2))
    needs = state.get("technical_needs")
    if needs is not None:
        print("technical_needs:")
        print(needs.model_dump_json(indent=2))


def main() -> None:
    graph = build_graph()
    state = {
        "requirements": UserRequirements(),
        "latest_user_message": INITIAL_MESSAGE,
        "next_question": None,
        "pending_field": None,
        "repo_analysis": None,
    }

    followups = 0
    state = graph.invoke(state)
    while state.get("next_question"):
        if followups >= MAX_FOLLOWUPS:
            print("\nSTOPPED: still awaiting input after auto-answers.")
            break
        question = state["next_question"]
        pending = state.get("pending_field") or ""
        answer = AUTO_ANSWERS.get(pending, "steady, 200 requests per second")
        print(f"\n[follow-up] pending_field={pending} question={question!r}")
        print(f"[auto-answer] {answer!r}")
        state["latest_user_message"] = answer
        state["next_question"] = None
        state = graph.invoke(state)
        followups += 1

    _summarize_state(state, "FINAL STATE (repo_analysis + technical_needs)")

    recommendation = state.get("system_design_recommendation")
    if recommendation is None:
        print("\nNo system design recommendation produced.")
        return
    print("\n===== FINAL RECOMMENDATION (reasoning fields) =====")
    print(f"resource_profile: {recommendation.compute.confidence}")
    print("\n[technical_needs.reasoning]")
    print(recommendation and state["technical_needs"].reasoning)
    print("\n[compute.why]")
    print(recommendation.compute.why)
    print("\n[architecture_summary]")
    print(recommendation.architecture_summary)


if __name__ == "__main__":
    main()