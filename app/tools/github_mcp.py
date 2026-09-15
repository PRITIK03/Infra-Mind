"""
GitHub MCP tool wrapper — optional repository analysis.

Connects to GitHub's remote MCP server over streamable HTTP using the
official ``mcp`` Python SDK (>= 2.2.0).  The API below is the one proven
against the live server by ``mcp_github_test.py``:

    http_client = create_mcp_http_client(headers={...})
    async with streamable_http_client(url, http_client=http_client) as streams:
        async with ClientSession(*streams) as session:
            await session.initialize()
            result = await session.call_tool("get_file_contents", {...})

Note the SDK's real names: ``streamable_http_client`` (not
``streamablehttp_client``), and custom headers are passed through an httpx
client — ``streamable_http_client`` itself takes no ``headers`` argument.

Optional by design: callers treat GitHubMCPUnavailableError as a soft skip.
Repository analysis enhances a recommendation; it never blocks one.
"""

from __future__ import annotations

import base64
import json
import logging
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from app.config import ConfigError, get_github_mcp_settings

logger = logging.getLogger(__name__)

# Tool name confirmed against the live remote server (repos toolset).
GET_FILE_CONTENTS_TOOL = "get_file_contents"

# Matches https://github.com/<owner>/<repo> with optional .git / trailing path.
_REPO_URL_RE = re.compile(
    r"https?://(?:www\.)?github\.com/"
    r"(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+)",
    re.IGNORECASE,
)


class GitHubMCPUnavailableError(RuntimeError):
    """
    Raised when GitHub MCP cannot be configured, reached, authenticated, or
    when a tool call itself fails.

    Callers MUST treat this as a soft skip.  Returning empty data instead
    would silently imply "this repository has no manifests", which is a
    different — and misleading — claim.
    """


def parse_repo_url(repo_url: str) -> tuple[str, str]:
    """Extract (owner, repo) from a GitHub URL, or raise if malformed."""
    match = _REPO_URL_RE.search(repo_url or "")
    if not match:
        raise GitHubMCPUnavailableError(
            f"Not a recognizable GitHub repository URL: {repo_url!r}"
        )
    owner = match.group("owner")
    repo = match.group("repo")
    if repo.lower().endswith(".git"):
        repo = repo[: -len(".git")]
    return owner, repo


@asynccontextmanager
async def get_mcp_session() -> AsyncIterator[Any]:
    """
    Async context manager yielding an initialized MCP ClientSession.

    Raises GitHubMCPUnavailableError when the token is unset, the SDK is
    missing, or the connection/initialize handshake fails.
    """
    try:
        settings = get_github_mcp_settings()
    except ConfigError as exc:
        raise GitHubMCPUnavailableError(
            "Missing GitHub MCP configuration: set GITHUB_MCP_TOKEN in the environment."
        ) from exc

    if not settings.token:
        raise GitHubMCPUnavailableError(
            "GITHUB_MCP_TOKEN is unset; repository analysis is disabled. "
            "Set it to a GitHub PAT with repo read scope to enable repo context."
        )

    try:
        from mcp import ClientSession
        from mcp.client.streamable_http import (
            create_mcp_http_client,
            streamable_http_client,
        )
    except ImportError as exc:
        raise GitHubMCPUnavailableError(
            "GitHub MCP dependency is missing. Install requirements to enable repo analysis."
        ) from exc

    headers = {
        "Authorization": f"Bearer {settings.token}",
        # Pin the toolset so the exposed tool list stays small and stable.
        "X-MCP-Toolsets": "repos",
    }
    http_client = create_mcp_http_client(headers=headers)

    try:
        async with streamable_http_client(
            settings.base_url, http_client=http_client
        ) as streams:
            async with ClientSession(*streams) as session:
                await session.initialize()
                yield session
    except GitHubMCPUnavailableError:
        raise
    except BaseException as exc:  # noqa: BLE001 — normalize anyio/TaskGroup errors
        raise GitHubMCPUnavailableError(
            f"GitHub MCP connection failed: {exc}"
        ) from exc


def _text_blocks(result: Any) -> list[str]:
    """
    Collect text from an MCP CallToolResult.

    Confirmed against the live server: responses may carry payload text as
    plain ``type=text`` blocks, as ``type=resource`` blocks whose
    ``resource`` has a ``text`` attribute (TextResourceContents), or both —
    e.g. a file read returns a "successfully downloaded text file" note
    plus a resource block holding the actual content.
    """
    texts: list[str] = []
    for block in getattr(result, "content", None) or []:
        text = getattr(block, "text", None)
        if isinstance(text, str) and text:
            texts.append(text)
        resource = getattr(block, "resource", None)
        resource_text = getattr(resource, "text", None)
        if isinstance(resource_text, str) and resource_text:
            texts.append(resource_text)
    return texts


_CONFIRMATION_RE = re.compile(
    r"^(successfully\s+(downloaded|retrieved|fetched)"
    r"|file\s+(saved|downloaded|written)"
    r"|content\s+saved)",
    re.IGNORECASE,
)


def _is_confirmation(text: str) -> bool:
    """Server acknowledgement lines carry no repository data — skip them."""
    first_line = text.strip().splitlines()[0] if text.strip() else ""
    return bool(_CONFIRMATION_RE.match(first_line))


def _content_texts(result: Any) -> list[str]:
    """Payload texts with server confirmation/noise lines removed."""
    return [text for text in _text_blocks(result) if not _is_confirmation(text)]


def _parse_listing_entries(raw_text: str) -> list[dict[str, Any]]:
    """
    Parse a get_file_contents directory response.

    Confirmed real shape (root listing of a public repo): a JSON array of
    objects with ``type`` ("dir"/"file"), ``size``, ``name``, ``path``,
    ``sha``, ``url``, ``git_url``, ``html_url``.
    """
    try:
        parsed = json.loads(raw_text)
    except ValueError as exc:
        raise GitHubMCPUnavailableError(
            "GitHub MCP returned a directory listing that was not valid JSON."
        ) from exc

    if isinstance(parsed, list):
        return [entry for entry in parsed if isinstance(entry, dict)]
    if isinstance(parsed, dict) and isinstance(parsed.get("name"), str):
        return [parsed]
    raise GitHubMCPUnavailableError(
        "Unexpected GitHub MCP directory listing shape."
    )


def _file_text_from_response(raw_text: str) -> str:
    """
    Decode a get_file_contents file response.

    The server may return the file text directly or wrap it as JSON with a
    ``content`` field (base64 when ``encoding == "base64"``).  Both shapes
    are handled so the exact server version doesn't matter.
    """
    stripped = raw_text.strip()
    if not stripped.startswith("{"):
        return raw_text
    try:
        payload = json.loads(stripped)
    except ValueError:
        return raw_text
    if not isinstance(payload, dict) or not isinstance(payload.get("content"), str):
        return raw_text

    content = payload["content"]
    if str(payload.get("encoding", "")).lower() == "base64":
        try:
            return base64.b64decode(content).decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001 — fall back to the raw payload
            return raw_text
    return content


async def _call_get_file_contents(
    owner: str, repo: str, path: str
) -> str:
    """Invoke the confirmed get_file_contents tool and return raw text."""
    async with get_mcp_session() as session:
        try:
            result = await session.call_tool(
                GET_FILE_CONTENTS_TOOL,
                {"owner": owner, "repo": repo, "path": path},
            )
        except GitHubMCPUnavailableError:
            raise
        except Exception as exc:  # noqa: BLE001 — normalize transport errors
            target = "repository root" if path in (".", "") else f"path {path}"
            raise GitHubMCPUnavailableError(
                f"GitHub MCP call to {GET_FILE_CONTENTS_TOOL} failed for "
                f"{owner}/{repo} ({target}): {exc}"
            ) from exc

    if getattr(result, "is_error", False):
        target = "repository root" if path in (".", "") else f"path {path}"
        detail = " ".join(_content_texts(result)) or "no detail returned"
        raise GitHubMCPUnavailableError(
            f"GitHub MCP reported an error reading {owner}/{repo} ({target}) — {detail}"
        )

    texts = _content_texts(result)
    if not texts:
        raise GitHubMCPUnavailableError(
            f"GitHub MCP returned no content for {owner}/{repo}:{path}."
        )
    return "\n".join(texts)


async def fetch_repo_root_listing(repo_url: str) -> list[dict[str, Any]]:
    """Return the repository root directory listing as structured entries."""
    owner, repo = parse_repo_url(repo_url)
    raw = await _call_get_file_contents(owner, repo, ".")
    return _parse_listing_entries(raw)


async def fetch_file_contents(repo_url: str, path: str) -> str:
    """Return the decoded text content of a single file in the repository."""
    owner, repo = parse_repo_url(repo_url)
    raw = await _call_get_file_contents(owner, repo, path)
    return _file_text_from_response(raw)
