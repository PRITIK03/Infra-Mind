"""
Request bodies accepted by the HTTP API.

Extracted from ``app/api/main.py`` so the route module holds only app
construction, middleware, and route definitions.  ``main.py`` re-exports
these names unchanged.

The validators are deliberately strict about whitespace-only input: an
agent run costs real LLM/live-data quota, so an empty-after-stripping
message must be rejected by FastAPI (422) rather than started.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class RecommendRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=10_000)
    consensus: bool = Field(
        default=False,
        description=(
            "Opt-in multi-model consensus.  When true, the final holistic "
            "recommendation is generated once more against a second model "
            "(CONSENSUS_MODEL, else the first LLM_FALLBACK_MODELS entry) and "
            "compared deterministically — at the cost of one extra full LLM "
            "call.  Defaults to False: consensus never runs unless explicitly "
            "requested."
        ),
    )

    @field_validator("message")
    @classmethod
    def validate_message(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("message must contain non-whitespace text")
        return value


class AnswerRequest(BaseModel):
    answer: str = Field(..., min_length=1, max_length=2_000)

    @field_validator("answer")
    @classmethod
    def validate_answer(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("answer must contain non-whitespace text")
        return value


class FollowupRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2_000)

    @field_validator("question")
    @classmethod
    def validate_question(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("question must contain non-whitespace text")
        return value
