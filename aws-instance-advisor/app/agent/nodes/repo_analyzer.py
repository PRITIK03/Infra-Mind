"""
Repository analyzer node — optional, additive capability.

Runs after collect_requirements and only when requirements.repo_url is set.
It inspects a user-supplied GitHub repository through the GitHub MCP server
and produces a shallow, deterministic RepoAnalysis: detected
language/framework, whether the repo is containerized, and notable
dependencies (in particular local ML/embedding libraries, which change the
resource profile of the workload).

Design rules, mirroring the rest of this project:

- Graceful skip everywhere.  No repo_url, no token, connection failure —
  the pipeline continues WITHOUT repo context (repo_analysis=None) rather
  than failing the run.  Repo analysis enhances a recommendation; it is
  never a hard dependency.
- Never fabricate.  A GitHubMCPUnavailableError is logged and propagated as
  a skip — it is never converted into "the repository is empty".
- Fetch only what exists.  The root listing is read first and manifest
  files are fetched only when they actually appear in it.
- Shallow by design.  This is not a dependency-graph or build analysis —
  just enough signal to inform resource_profile / scaling_recommendation.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
import re
from typing import Any

from app.agent.state import AgentState
from app.models.schemas import RepoAnalysis
from app.tools.github_mcp import (
    GitHubMCPUnavailableError,
    fetch_file_contents,
    fetch_repo_root_listing,
)

logger = logging.getLogger(__name__)

# Manifests worth reading, in priority order.  Only files present in the
# repository root listing are ever fetched.
_MANIFEST_ORDER: tuple[str, ...] = (
    "requirements.txt",
    "pyproject.toml",
    "package.json",
    "Dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
)

# Cap per-file reading so a pathological manifest can't bloat the prompt.
_MAX_FILE_CHARS = 20_000

# Languages implied by the presence of a manifest file.
_LANGUAGE_BY_MANIFEST: dict[str, str] = {
    "requirements.txt": "Python",
    "pyproject.toml": "Python",
    "package.json": "JavaScript/Node.js",
}

# Light framework hints — a dependency name is enough to say "FastAPI",
# no version resolution or graph walking required.  (Not local-model
# libraries: sentence-transformers and friends are dependencies, not
# frameworks — they surface via notable_dependencies instead.)
_FRAMEWORK_BY_DEPENDENCY: dict[str, str] = {
    "fastapi": "FastAPI",
    "django": "Django",
    "flask": "Flask",
    "streamlit": "Streamlit",
    "gradio": "Gradio",
    "next": "Next.js",
    "react": "React",
    "express": "Express",
    "nestjs": "NestJS",
}

# Local ML/embedding libraries — the motivating case from the original spec.
# These imply model weights loaded in-process, which materially affects
# memory (and sometimes CPU/GPU) requirements.
_LOCAL_MODEL_DEPENDENCIES: frozenset[str] = frozenset(
    {
        "sentence-transformers",
        "transformers",
        "torch",
        "torchvision",
        "torchaudio",
        "tensorflow",
        "keras",
        "onnxruntime",
        "onnx",
        "diffusers",
        "huggingface-hub",
        "sentencepiece",
        "spacy",
        "gensim",
        "fasttext",
        "faiss-cpu",
        "faiss-gpu",
        "chromadb",
        "sentence-transformers",
    }
)

# Hosted-inference clients: notable, but they do NOT imply local model
# weights — distinguishing these from the group above is the point.
_HOSTED_LLM_DEPENDENCIES: frozenset[str] = frozenset(
    {
        "openai",
        "anthropic",
        "cohere",
        "google-generativeai",
        "langchain",
        "langchain-core",
        "llama-index",
        "litellm",
        "groq",
        "mistralai",
    }
)


def _run_async(coro: Any) -> Any:
    """
    Run an async MCP call from this synchronous graph node.

    The graph is invoked synchronously (the API runs it in a worker thread),
    so there is normally no running event loop.  If one exists, run the
    coroutine in a dedicated thread instead of failing.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()
def _manifest_names(root_entries: list[dict[str, Any]]) -> set[str]:
    """File names present in the repository root listing (dirs excluded)."""
    names: set[str] = set()
    for entry in root_entries:
        name = entry.get("name")
        if not isinstance(name, str) or not name:
            continue
        if str(entry.get("type", "")).lower() == "dir":
            continue
        names.add(name)
    return names


def _normalize_dependency(raw: str) -> str | None:
    """Reduce a requirement line to a bare, comparable package name."""
    line = raw.strip().strip("\"'").strip().rstrip(",").strip()
    if not line or line.startswith("#"):
        return None
    # Skip pip options and includes: -r, -e, --hash, -c, etc.
    if line.startswith("-"):
        return None
    # Drop environment markers and inline comments.
    line = line.split(";")[0].split("#")[0].strip()
    if not line:
        return None
    # Keep only the leading name (strip extras and version specifiers).
    name = re.split(r"[<>=!~\[\s(]", line, maxsplit=1)[0].strip()
    return name.lower() or None


# Quoted strings are how pyproject.toml declares dependencies, e.g.
#     dependencies = ["torch>=2.0", "sentence-transformers>=2.2"]
_QUOTED_STRING_RE = re.compile(r'"([^"]+)"' + r"|'([^']+)'")


def _parse_pyproject_toml(text: str) -> list[str]:
    """
    Extract dependency-ish names from a pyproject.toml without a TOML parser.

    Deliberately shallow: every quoted string is normalized to a bare name.
    Non-dependency strings (descriptions, versions, extras) simply don't
    match any notable-dependency set, so they're harmless — and shipping no
    TOML parser keeps this a lightweight signal rather than a build analysis.
    """
    found: list[str] = []
    for match in _QUOTED_STRING_RE.finditer(text):
        raw = match.group(1) or match.group(2) or ""
        name = _normalize_dependency(raw)
        # A bare dotted path or a version constraint is not a dependency name.
        if not name or not re.match(r"^[a-z0-9][a-z0-9._-]*$", name):
            continue
        if name not in found:
            found.append(name)
    return found


def _parse_requirements_txt(text: str) -> list[str]:
    found: list[str] = []
    for raw_line in text.splitlines():
        name = _normalize_dependency(raw_line)
        if name and name not in found:
            found.append(name)
    return found


def _parse_package_json(text: str) -> list[str]:
    try:
        payload = json.loads(text)
    except ValueError:
        return []
    if not isinstance(payload, dict):
        return []
    found: list[str] = []
    for section in ("dependencies", "devDependencies"):
        deps = payload.get(section)
        if isinstance(deps, dict):
            for name in deps:
                lowered = str(name).lower()
                if lowered not in found:
                    found.append(lowered)
    return found


def _dependencies_for(manifest: str, text: str) -> list[str]:
    """Extract dependency names from whichever manifest was fetched."""
    if manifest == "package.json":
        return _parse_package_json(text)
    if manifest == "pyproject.toml":
        return _parse_pyproject_toml(text)
    if manifest == "requirements.txt":
        return _parse_requirements_txt(text)
    return []


def build_repo_analysis(
    root_entries: list[dict[str, Any]],
    files: dict[str, str],
) -> RepoAnalysis:
    """
    Pure, deterministic extraction from a root listing + manifest contents.

    Kept side-effect free so it can be tested without any MCP connection.
    """
    names = _manifest_names(root_entries)

    language: str | None = None
    for manifest, label in _LANGUAGE_BY_MANIFEST.items():
        if manifest in files or manifest in names:
            language = label
            break

    has_dockerfile = "Dockerfile" in names or "Dockerfile" in files

    dependencies: list[str] = []
    for manifest in _MANIFEST_ORDER:
        text = files.get(manifest)
        if not text:
            continue
        for dep in _dependencies_for(manifest, text):
            if dep not in dependencies:
                dependencies.append(dep)

    local_models = [d for d in dependencies if d in _LOCAL_MODEL_DEPENDENCIES]
    hosted_llm = [d for d in dependencies if d in _HOSTED_LLM_DEPENDENCIES]
    frameworks = [
        label
        for dep, label in _FRAMEWORK_BY_DEPENDENCY.items()
        if dep in dependencies
    ]

    # Framework detection is limited to the primary language's ecosystem so a
    # stray devDependency cannot relabel a Python service.
    if language and frameworks:
        framework = frameworks[0]
        js_frameworks = ("React", "Next.js", "Express", "NestJS")
        if framework in js_frameworks:
            if language.startswith("JavaScript"):
                language = f"{language} ({framework})"
        else:
            language = f"{language} ({framework})"

    notable = list(local_models)
    for dep in hosted_llm:
        if dep not in notable:
            notable.append(dep)

    note_parts: list[str] = []
    if language:
        note_parts.append(f"Repository is primarily {language}")
    if has_dockerfile:
        note_parts.append("containerized deployment (Dockerfile present)")
    if local_models:
        note_parts.append(
            "local ML/embedding dependency detected ("
            + ", ".join(local_models)
            + ") — model weights load in-process, so expect higher memory and "
            "CPU demands"
        )
    if hosted_llm and not local_models:
        note_parts.append(
            "LLM usage appears to be via hosted API clients ("
            + ", ".join(hosted_llm)
            + "), so inference compute is off-instance"
        )
    if not note_parts:
        note_parts.append(
            "No recognized manifest files in the repository root; "
            "no language-specific signals available"
        )

    return RepoAnalysis(
        detected_language=language,
        has_dockerfile=has_dockerfile,
        notable_dependencies=notable,
        analysis_note="; ".join(note_parts) + ".",
    )


def _fetch_manifests(
    repo_url: str, root_entries: list[dict[str, Any]]
) -> dict[str, str]:
    """Fetch only the manifests that actually exist in the root listing."""
    names = _manifest_names(root_entries)
    files: dict[str, str] = {}
    for manifest in _MANIFEST_ORDER:
        if manifest not in names:
            continue
        try:
            content = _run_async(fetch_file_contents(repo_url, manifest))
        except GitHubMCPUnavailableError as exc:
            # One unreadable manifest must not discard the signals we can
            # still derive from the listing itself.
            logger.debug("Skipping manifest %s: %s", manifest, exc)
            continue
        if content:
            files[manifest] = content[:_MAX_FILE_CHARS]
    return files


def _repo_analysis_failure_note(exc: Exception) -> str:
    reason = str(exc).strip().rstrip(".")
    if not reason:
        reason = "GitHub access was unavailable"
    return (
        "Repository URL was provided but could not be analyzed: "
        f"{reason}."
    )


def analyze_repository(state: AgentState) -> AgentState:
    """
    Analyze the user-supplied GitHub repository, if any.

    Always sets repo_analysis (possibly None) and never raises for
    GitHub-side problems — the pipeline continues without repo context.
    """
    requirements = state["requirements"]
    repo_url = (requirements.repo_url or "").strip()

    if not repo_url:
        # Graceful skip: same pattern as optional Tavily research.
        state["repo_analysis"] = None
        state["repo_analysis_note"] = None
        return state

    try:
        root_entries = _run_async(fetch_repo_root_listing(repo_url))
        files = _fetch_manifests(repo_url, root_entries)
    except GitHubMCPUnavailableError as exc:
        logger.warning(
            "Repository analysis skipped for %s: %s", repo_url, exc
        )
        state["repo_analysis"] = None
        state["repo_analysis_note"] = _repo_analysis_failure_note(exc)
        return state
    except Exception as exc:  # noqa: BLE001 — never fail the pipeline here
        logger.warning(
            "Repository analysis failed unexpectedly for %s: %s", repo_url, exc
        )
        state["repo_analysis"] = None
        state["repo_analysis_note"] = _repo_analysis_failure_note(exc)
        return state

    analysis = build_repo_analysis(root_entries, files)
    state["repo_analysis"] = analysis
    state["repo_analysis_note"] = None
    logger.info(
        "Repository analysis for %s: language=%s dockerfile=%s notable=%s",
        repo_url,
        analysis.detected_language,
        analysis.has_dockerfile,
        analysis.notable_dependencies,
    )
    return state
