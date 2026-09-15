"""
Tests for the optional GitHub MCP repository-analysis capability.

All MCP traffic is mocked — no network access and no GitHub token needed.
Covers: deterministic repo_url extraction, graceful skip when no repo is
supplied, GitHubMCPUnavailableError never failing the pipeline, and the
sentence-transformers / local-embedding-model signal from the original spec.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app.agent.nodes.repo_analyzer import (
    analyze_repository,
    build_repo_analysis,
)
from app.agent.nodes.requirement_collector import (
    collect_requirements,
    detect_repo_url,
)
from app.models.schemas import TechnicalNeeds, UserRequirements
from app.tools.github_mcp import (
    GitHubMCPUnavailableError,
    fetch_file_contents,
    fetch_repo_root_listing,
    parse_repo_url,
)

REPO_URL = "https://github.com/example/embedding-service"

# Real shape confirmed against the live server: type/size/name/path/sha.
ROOT_LISTING = [
    {"type": "file", "size": 512, "name": "requirements.txt",
     "path": "requirements.txt", "sha": "abc123"},
    {"type": "file", "size": 128, "name": "Dockerfile",
     "path": "Dockerfile", "sha": "def456"},
    {"type": "dir", "size": 0, "name": "app", "path": "app", "sha": "ghi789"},
]

REQUIREMENTS_TXT = (
    "fastapi==0.115.0\n"
    "sentence-transformers>=2.2.2\n"
    "# a comment line\n"
    "-r other-requirements.txt\n"
    "uvicorn[standard]>=0.30\n"
)


def _state(**requirement_kwargs) -> dict:
    return {
        "requirements": UserRequirements(**requirement_kwargs),
        "latest_user_message": None,
        "next_question": None,
        "pending_field": None,
        "repo_analysis": None,
    }


# ── 1. Deterministic repo_url extraction ────────────────────────────────────


def test_detect_repo_url_extracts_github_url_from_message():
    message = (
        "Our API service backend is at https://github.com/example/embedding-service "
        "and we expect 50 req/s steady traffic."
    )
    assert detect_repo_url(message) == REPO_URL


def test_detect_repo_url_strips_git_suffix_and_trailing_slash():
    assert detect_repo_url("see https://github.com/example/repo.git") == (
        "https://github.com/example/repo"
    )
    assert detect_repo_url("see https://github.com/example/repo/") == (
        "https://github.com/example/repo"
    )


def test_detect_repo_url_strips_trailing_sentence_punctuation():
    """Real failure case: '...at https://github.com/a/b.' must not keep the dot."""
    message = (
        "running the code at https://github.com/huggingface/sentence-transformers. "
        "About 200 requests per second."
    )
    assert detect_repo_url(message) == (
        "https://github.com/huggingface/sentence-transformers"
    )


def test_detect_repo_url_returns_none_without_github_url():
    assert detect_repo_url("A steady B2B SaaS API with 80 req/s.") is None
    assert detect_repo_url("") is None
    assert detect_repo_url("https://gitlab.com/example/repo") is None


@patch("app.agent.nodes.requirement_collector.invoke_structured")
def test_collect_requirements_populates_repo_url_from_message(mock_invoke):
    """The URL is detected by regex, not left to the LLM to echo back."""
    mock_invoke.return_value = UserRequirements()  # model returned nothing
    state = _state()
    state["latest_user_message"] = (
        "Web app for embeddings: https://github.com/example/embedding-service"
    )

    result = collect_requirements(state)

    assert result["requirements"].repo_url == REPO_URL


@patch("app.agent.nodes.requirement_collector.invoke_structured")
def test_detect_repo_url_overrides_llm_guess(mock_invoke):
    mock_invoke.return_value = UserRequirements(
        repo_url="https://github.com/wrong/guessed-repo"
    )
    state = _state()
    state["latest_user_message"] = f"repo: {REPO_URL}"

    result = collect_requirements(state)

    assert result["requirements"].repo_url == REPO_URL


def test_repo_url_is_never_a_critical_requirement_field():
    """repo_url stays fully optional — it must never trigger a follow-up."""
    requirements = UserRequirements()
    assert "repo_url" not in requirements.missing_critical_fields()

    requirements_with_repo = UserRequirements(repo_url=REPO_URL)
    assert "repo_url" not in requirements_with_repo.missing_critical_fields()


# ── 2. repo_analyzer: graceful skip when no repo is supplied ────────────────


@patch("app.agent.nodes.repo_analyzer.fetch_repo_root_listing", new_callable=AsyncMock)
def test_repo_analyzer_skips_entirely_when_repo_url_unset(mock_listing):
    """No repo_url → no MCP call at all, and repo_analysis stays None."""
    state = _state()

    result = analyze_repository(state)

    assert result["repo_analysis"] is None
    assert result["repo_analysis_note"] is None
    mock_listing.assert_not_called()


@pytest.mark.parametrize("blank", [None, "", "   "])
@patch("app.agent.nodes.repo_analyzer.fetch_repo_root_listing", new_callable=AsyncMock)
def test_repo_analyzer_skips_for_blank_repo_url(mock_listing, blank):
    state = _state(repo_url=blank)

    result = analyze_repository(state)

    assert result["repo_analysis"] is None
    assert result["repo_analysis_note"] is None
    mock_listing.assert_not_called()


# ── 3. GitHubMCPUnavailableError never crashes the pipeline ─────────────────


@patch(
    "app.agent.nodes.repo_analyzer.fetch_repo_root_listing",
    new_callable=AsyncMock,
    side_effect=GitHubMCPUnavailableError("GITHUB_MCP_TOKEN is unset"),
)
def test_repo_analyzer_soft_skips_on_mcp_unavailable(mock_listing):
    """An MCP failure must degrade to 'no repo context', never an exception."""
    state = _state(repo_url=REPO_URL)

    result = analyze_repository(state)  # must not raise

    assert result["repo_analysis"] is None
    assert "Repository URL was provided but could not be analyzed" in result["repo_analysis_note"]
    assert "GITHUB_MCP_TOKEN is unset" in result["repo_analysis_note"]
    mock_listing.assert_called_once()


@patch("app.agent.nodes.repo_analyzer.fetch_file_contents", new_callable=AsyncMock)
@patch(
    "app.agent.nodes.repo_analyzer.fetch_repo_root_listing",
    new_callable=AsyncMock,
    return_value=ROOT_LISTING,
)
def test_manifest_read_failure_does_not_discard_listing_signals(
    mock_listing, mock_file
):
    """One unreadable manifest still leaves Dockerfile/language signals intact."""
    mock_file.side_effect = GitHubMCPUnavailableError("file read failed")
    state = _state(repo_url=REPO_URL)

    result = analyze_repository(state)

    analysis = result["repo_analysis"]
    assert analysis is not None
    assert result["repo_analysis_note"] is None
    assert analysis.has_dockerfile is True
    assert analysis.detected_language == "Python"


@patch(
    "app.agent.nodes.repo_analyzer.fetch_repo_root_listing",
    new_callable=AsyncMock,
    side_effect=RuntimeError("unexpected transport explosion"),
)
def test_repo_analyzer_never_raises_on_unexpected_error(mock_listing):
    state = _state(repo_url=REPO_URL)

    result = analyze_repository(state)  # must not raise

    assert result["repo_analysis"] is None
    assert "Repository URL was provided but could not be analyzed" in result["repo_analysis_note"]
    assert "unexpected transport explosion" in result["repo_analysis_note"]


@patch("app.agent.nodes.repo_analyzer.fetch_file_contents", new_callable=AsyncMock)
@patch(
    "app.agent.nodes.repo_analyzer.fetch_repo_root_listing",
    new_callable=AsyncMock,
    return_value=ROOT_LISTING,
)
def test_only_existing_manifests_are_fetched(mock_listing, mock_file):
    """Never guess-fetch: package.json is absent, so it must not be requested."""
    mock_file.return_value = REQUIREMENTS_TXT
    state = _state(repo_url=REPO_URL)

    analyze_repository(state)

    requested = [call.args[1] for call in mock_file.call_args_list]
    assert "requirements.txt" in requested
    assert "package.json" not in requested
    assert "docker-compose.yml" not in requested


# ── 4. sentence-transformers / local embedding model detection ─────────────


@patch("app.agent.nodes.repo_analyzer.fetch_file_contents", new_callable=AsyncMock)
@patch(
    "app.agent.nodes.repo_analyzer.fetch_repo_root_listing",
    new_callable=AsyncMock,
    return_value=ROOT_LISTING,
)
def test_mocked_repo_flags_sentence_transformers(mock_listing, mock_file):
    """The exact scenario from the original mentor spec."""
    mock_file.return_value = REQUIREMENTS_TXT
    state = _state(repo_url=REPO_URL)

    result = analyze_repository(state)
    analysis = result["repo_analysis"]

    assert analysis is not None
    assert "sentence-transformers" in analysis.notable_dependencies
    assert analysis.detected_language == "Python (FastAPI)"
    assert analysis.has_dockerfile is True
    assert "local ML/embedding dependency" in analysis.analysis_note
    assert "sentence-transformers" in analysis.analysis_note


def test_build_repo_analysis_ignores_comments_and_pip_options():
    analysis = build_repo_analysis(
        ROOT_LISTING, {"requirements.txt": REQUIREMENTS_TXT}
    )
    assert "a comment line" not in analysis.notable_dependencies
    assert "other-requirements.txt" not in analysis.notable_dependencies
    assert "uvicorn" not in analysis.notable_dependencies  # parsed but not notable


def test_build_repo_analysis_distinguishes_hosted_llm_clients():
    """Hosted API clients are notable but must NOT imply local model weights."""
    analysis = build_repo_analysis(
        [{"type": "file", "name": "requirements.txt"}],
        {"requirements.txt": "openai>=1.0\nfastapi\n"},
    )
    assert analysis.notable_dependencies == ["openai"]
    assert "off-instance" in analysis.analysis_note
    assert "local ML/embedding" not in analysis.analysis_note


def test_build_repo_analysis_without_manifests_still_returns_a_note():
    analysis = build_repo_analysis([{"type": "dir", "name": "src"}], {})
    assert analysis.detected_language is None
    assert analysis.has_dockerfile is False
    assert analysis.notable_dependencies == []
    assert analysis.analysis_note


# ── 5. Reasoner consumes repo context without overriding the user ──────────


def _needs(**kwargs) -> TechnicalNeeds:
    from app.models.schemas import ResourceProfile, TrafficPattern

    base = dict(
        estimated_concurrency=10,
        resource_profile=ResourceProfile.BALANCED,
        traffic_pattern=TrafficPattern.STEADY,
        requires_gpu=False,
        scaling_recommendation="single instance",
        reasoning="test",
    )
    base.update(kwargs)
    return TechnicalNeeds(**base)


@patch("app.agent.nodes.system_design_reasoner._maybe_collect_research", return_value=None)
@patch("app.agent.nodes.system_design_reasoner.invoke_structured")
def test_reasoner_prompt_includes_repo_context_when_present(mock_invoke, _research):
    from app.agent.nodes.system_design_reasoner import reason_system_design

    mock_invoke.return_value = _needs()
    state = _state(repo_url=REPO_URL, workload_type="api_service")
    state["repo_analysis"] = build_repo_analysis(
        ROOT_LISTING, {"requirements.txt": REQUIREMENTS_TXT}
    )

    reason_system_design(state)

    prompt = mock_invoke.call_args.args[1]
    assert "<repository_analysis>" in prompt
    assert "sentence-transformers" in prompt
    assert "Python (FastAPI)" in prompt


@patch("app.agent.nodes.system_design_reasoner._maybe_collect_research", return_value=None)
@patch("app.agent.nodes.system_design_reasoner.invoke_structured")
def test_reasoner_prompt_has_no_repo_block_without_analysis(mock_invoke, _research):
    from app.agent.nodes.system_design_reasoner import reason_system_design

    mock_invoke.return_value = _needs()
    state = _state(workload_type="api_service")  # no repo, no analysis

    reason_system_design(state)

    assert "<repository_analysis>" not in mock_invoke.call_args.args[1]


def test_repo_prompt_instructs_user_stated_requirements_take_precedence():
    """Repo context must be explicitly subordinate to user-stated facts."""
    from app.agent.nodes.system_design_reasoner import _PROMPT_TEMPLATE

    lowered = _PROMPT_TEMPLATE.lower()
    assert "repository analysis block" in lowered
    assert "must never override" in lowered
    assert "user-stated traffic pattern" in lowered
    assert "gpu requirement" in lowered


@patch("app.agent.nodes.system_design_reasoner._maybe_collect_research", return_value=None)
@patch("app.agent.nodes.system_design_reasoner.invoke_structured")
def test_repo_context_does_not_override_user_stated_gpu_and_traffic(
    mock_invoke, _research
):
    """
    Repo analysis must not flip an explicit user GPU/traffic fact — the
    existing deterministic bridges still win.
    """
    from app.agent.nodes.system_design_reasoner import reason_system_design
    from app.models.schemas import ResourceProfile, TrafficPattern

    # Model returns contradictory values (as if repo context swayed it).
    mock_invoke.return_value = _needs(
        resource_profile=ResourceProfile.MEMORY_BOUND,
        traffic_pattern=TrafficPattern.STEADY,
    )
    state = _state(
        repo_url=REPO_URL,
        gpu_required=True,
        traffic_pattern=TrafficPattern.BURSTY,
        workload_type="ml_inference",
    )
    state["repo_analysis"] = build_repo_analysis(
        ROOT_LISTING, {"requirements.txt": REQUIREMENTS_TXT}
    )

    needs = reason_system_design(state)["technical_needs"]

    assert needs.requires_gpu is True
    assert needs.resource_profile == ResourceProfile.GPU_BOUND
    assert needs.traffic_pattern == TrafficPattern.BURSTY


# ── 6. Config, graph wiring, and the sync/async bridge ─────────────────────


def test_github_mcp_settings_graceful_when_token_unset(monkeypatch):
    from app.config import get_github_mcp_settings

    monkeypatch.delenv("GITHUB_MCP_TOKEN", raising=False)
    settings = get_github_mcp_settings()

    assert settings.token is None
    assert settings.base_url == "https://api.githubcopilot.com/mcp/"


def test_github_mcp_settings_reads_token_when_set(monkeypatch):
    from app.config import get_github_mcp_settings

    monkeypatch.setenv("GITHUB_MCP_TOKEN", "  ghp_example  ")

    assert get_github_mcp_settings().token == "ghp_example"


def test_graph_runs_repo_analysis_before_validation():
    from app.agent.graph import build_graph

    graph = build_graph()
    assert "analyze_repository" in set(graph.get_graph().nodes.keys())

    edges = {(edge.source, edge.target) for edge in graph.get_graph().edges}
    assert ("collect_requirements", "analyze_repository") in edges
    assert ("analyze_repository", "validate_requirements") in edges
    # The pre-existing V2 chain is untouched.
    assert ("validate_requirements", "reason_system_design") in edges


def test_parse_repo_url_variants():
    assert parse_repo_url(REPO_URL) == ("example", "embedding-service")
    assert parse_repo_url("https://www.github.com/owner/repo.git") == ("owner", "repo")
    with pytest.raises(GitHubMCPUnavailableError):
        parse_repo_url("https://gitlab.com/owner/repo")


def test_mcp_wrappers_raise_clear_error_without_token(monkeypatch):
    """No token → GitHubMCPUnavailableError, never a silently empty listing."""
    monkeypatch.delenv("GITHUB_MCP_TOKEN", raising=False)

    with pytest.raises(GitHubMCPUnavailableError):
        asyncio.run(fetch_repo_root_listing(REPO_URL))

    with pytest.raises(GitHubMCPUnavailableError):
        asyncio.run(fetch_file_contents(REPO_URL, "requirements.txt"))


def test_run_async_bridge_executes_coroutine():
    from app.agent.nodes.repo_analyzer import _run_async

    async def _value():
        return 42

    assert _run_async(_value()) == 42


# ── 7. pyproject.toml (quoted TOML strings, not requirements lines) ─────────


PYPROJECT_TOML = (
    "[project]\n"
    'name = "embedding-service"\n'
    "dependencies = [\n"
    '    "fastapi>=0.110",\n'
    '    "sentence-transformers>=2.2.2",\n'
    '    "torch>=2.0",\n'
    "]\n"
    'requires-python = ">=3.9"\n'
)

PYPROJECT_LISTING = [
    {"type": "file", "size": 600, "name": "pyproject.toml",
     "path": "pyproject.toml", "sha": "xyz"},
]


def test_pyproject_toml_finds_quoted_dependencies():
    from app.agent.nodes.repo_analyzer import _parse_pyproject_toml

    deps = _parse_pyproject_toml(PYPROJECT_TOML)

    assert "sentence-transformers" in deps
    assert "torch" in deps
    assert "fastapi" in deps
    # Non-dependency quoted strings are harmless: either filtered out or
    # simply never match a notable set.  (The project's own "name" key
    # legitimately normalizes to a name token — harmless, never notable.)
    assert ">=3.9" not in deps


def test_pyproject_toml_repo_builds_correct_analysis():
    analysis = build_repo_analysis(PYPROJECT_LISTING, {"pyproject.toml": PYPROJECT_TOML})

    assert analysis.detected_language == "Python (FastAPI)"
    assert "sentence-transformers" in analysis.notable_dependencies
    assert "torch" in analysis.notable_dependencies
    assert "local ML/embedding dependency" in analysis.analysis_note
