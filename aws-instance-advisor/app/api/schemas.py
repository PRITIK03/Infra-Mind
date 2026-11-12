"""
Request bodies accepted by the HTTP API.

Extracted from ``app/api/main.py`` so the route module holds only app
construction, middleware, and route definitions.  ``main.py`` re-exports
these names unchanged.

Recommendation requests need workload text, a repository, or both.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, PrivateAttr, field_validator, model_validator
from pydantic_core import PydanticCustomError

from app.models.repository import RepositoryRef, repository_input


class RecommendRequest(BaseModel):
    message: str = Field(default="", max_length=10_000)
    github_url: str | None = Field(default=None, max_length=256)
    _repository: RepositoryRef | None = PrivateAttr(default=None)
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

    @model_validator(mode="after")
    def normalize_input(self) -> "RecommendRequest":
        try:
            self.message, self._repository = repository_input(self.message, (self.github_url or "").strip())
        except ValueError as exc:
            raise PydanticCustomError("github_url", str(exc)) from None
        if not self.message and self._repository is None:
            raise ValueError("Enter workload details or a GitHub repository URL.")
        return self

    @property
    def repository(self) -> RepositoryRef | None:
        return self._repository


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
