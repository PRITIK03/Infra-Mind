"""
Conversational follow-up assistant for completed recommendations.

Executes a single LLM call using already-computed recommendation data and prior
Q&A history. Does not re-run research, does not re-generate Terraform, and does
not fetch new live AWS data.
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from pydantic import BaseModel

from app.api.job_store import FollowupExchange
from app.llm.retry import _call_with_failover
from app.models.schemas import SystemDesignRecommendation, TechnicalNeeds

_SYSTEM_PROMPT = """\
You are an expert AWS Solutions Architect assistant answering questions about an already-computed system design recommendation.

You are provided with:
1. The finalized architecture recommendation (Compute, Database, Cache, Load Balancer, Cost breakdown, and Architecture Summary).
2. The workload's technical needs and characteristics.
3. Prior Q&A history from this session (if any).

CRITICAL INSTRUCTIONS:
- You must answer ONLY using the provided architecture recommendation and technical needs data.
- If the question asks for or requires data not present in the recommendation (for example: spot instance pricing, reserved instance pricing, GPU instances when none were analyzed, alternate cloud providers, or fundamental architectural changes like adding microservices/GPU clusters), you MUST state honestly that this information was not part of the current analysis and suggest starting a new analysis.
- NEVER fabricate numbers, pricing, specifications, or assumptions.
- NEVER silently reinterpret the question into something you can answer with the existing data.
- Keep your answers clear, concise, direct, and factual.
"""


def _serialize_for_prompt(obj: Any) -> str:
    """Format a recommendation or technical needs object for the prompt."""
    if obj is None:
        return "Not available"
    if isinstance(obj, BaseModel):
        return json.dumps(obj.model_dump(mode="json"), indent=2)
    if isinstance(obj, dict):
        return json.dumps(obj, indent=2)
    return str(obj)


def answer_followup(
    system_design_recommendation: SystemDesignRecommendation | dict[str, Any],
    technical_needs: TechnicalNeeds | dict[str, Any] | None,
    question: str,
    prior_history: list[FollowupExchange] | None = None,
) -> str:
    """
    Generate an answer to a follow-up question based solely on the completed
    recommendation and technical needs. Single LLM call with bounded retries.
    """
    rec_str = _serialize_for_prompt(system_design_recommendation)
    tn_str = _serialize_for_prompt(technical_needs)

    context_prompt = (
        f"### ARCHITECTURE RECOMMENDATION DATA:\n{rec_str}\n\n"
        f"### WORKLOAD TECHNICAL NEEDS:\n{tn_str}"
    )

    messages: list[BaseMessage] = [
        SystemMessage(content=_SYSTEM_PROMPT),
        SystemMessage(content=context_prompt),
    ]

    if prior_history:
        for ex in prior_history:
            q = ex.question if isinstance(ex, FollowupExchange) else ex.get("question", "")
            a = ex.answer if isinstance(ex, FollowupExchange) else ex.get("answer", "")
            if q:
                messages.append(HumanMessage(content=q))
            if a:
                messages.append(AIMessage(content=a))

    messages.append(HumanMessage(content=question.strip()))

    def _call(model: Any) -> str:
        res = model.invoke(messages)
        if isinstance(res, AIMessage):
            return str(res.content).strip()
        return str(getattr(res, "content", res)).strip()

    return _call_with_failover(_call)
