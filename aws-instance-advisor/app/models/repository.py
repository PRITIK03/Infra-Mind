"""Repository intake and the sanitized contract shared with the job API."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.schemas import WorkloadType


_GITHUB_URL = re.compile(
    r"https://(?:www\.)?github\.com/(?P<owner>[a-z0-9][a-z0-9-]{0,38})/"
    r"(?P<name>[a-z0-9_.-]{1,104})/?", re.IGNORECASE | re.ASCII
)
_PASTED_URL = re.compile(r"https?://[^\s<>\"'`]+", re.IGNORECASE | re.ASCII)


class RepositoryRef(BaseModel):
    model_config = ConfigDict(frozen=True)

    owner: str
    name: str

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.name}"

    @property
    def url(self) -> str:
        return f"https://github.com/{self.full_name}"


def parse_repository_url(value: str) -> RepositoryRef:
    match = _GITHUB_URL.fullmatch(value.strip())
    if match:
        owner, name = match.group("owner", "name")
        if name.lower().endswith(".git"):
            name = name[:-4]
        if name not in ("", ".", "..") and len(name) <= 100:
            return RepositoryRef(owner=owner, name=name)
    raise ValueError("Enter a GitHub repository URL like https://github.com/owner/repo.")


def repository_input(message: str, github_url: str | None) -> tuple[str, RepositoryRef | None]:
    explicit = parse_repository_url(github_url) if github_url else None
    pasted: dict[str, RepositoryRef] = {}

    def remove_repo_link(match: re.Match[str]) -> str:
        url = match.group().rstrip(".,;:!?)]}*")
        url = url.partition("?")[0].partition("#")[0]
        # Keep accepting old http links in prose, but always use HTTPS.
        if url.lower().startswith("http://"):
            url = f"https://{url[7:]}"
        try:
            ref = parse_repository_url(url)
        except ValueError:
            return match.group()
        pasted.setdefault(ref.full_name.lower(), ref)
        return ""

    workload = _PASTED_URL.sub(remove_repo_link, message).strip()
    if not explicit and len(pasted) > 1:
        raise ValueError("Choose one repository in the GitHub repository field.")
    ref = explicit or next(iter(pasted.values()), None)
    if ref and not any(character.isalnum() for character in workload):
        workload = ""
    return workload, ref


RepositoryReason = Literal[
    "disabled", "not_accessible", "not_public", "empty", "rate_limited",
    "unavailable", "busy", "timeout", "no_source",
]
FindingCategory = Literal["application", "database", "workflow", "deployment", "security", "inference"]


class RepositoryProgress(BaseModel):
    status: Literal["checking", "scanning", "complete", "partial", "unavailable"]
    reason: RepositoryReason | None = None
    retry_after_seconds: int | None = None


class RepositoryFinding(BaseModel):
    category: FindingCategory
    title: str
    action: str
    path: str | None = None
    line: int | None = None
    severity: Literal["info", "review", "high"] = "info"
    confidence: Literal["observed", "inferred"] = "observed"


class RepositoryReport(BaseModel):
    repository: RepositoryRef
    commit_sha: str
    coverage: Literal["complete", "partial"]
    files_discovered: int
    files_analyzed: int
    skipped: dict[str, int] = Field(default_factory=dict)
    limitations: list[str] = Field(default_factory=list)
    stack: list[str] = Field(default_factory=list)
    databases: list[str] = Field(default_factory=list)
    configured_databases: list[str] = Field(default_factory=list)
    workflows: list[str] = Field(default_factory=list)
    workload_type: WorkloadType | None = None
    has_dockerfile: bool = False
    local_inference: bool = False
    hosted_inference: bool = False
    model_artifacts: int = 0
    advisory_status: Literal[
        "not_configured", "no_supported_dependencies", "checked", "checked_capped", "partial", "unavailable",
    ] = "not_configured"
    findings: list[RepositoryFinding] = Field(default_factory=list)
