"""
Standalone GitHub MCP connectivity test — NOT wired into the LangGraph graph.

Verifies the real technical shape before designing any schema/node:
  1. Official `mcp` Python SDK (v2.2.0) streamable-HTTP client API
  2. Whether GitHub's remote MCP server (api.githubcopilot.com/mcp/) accepts
     a PAT via `Authorization: Bearer <token>` from outside VS Code
  3. Raw response shape of list_tools + one read-only repo metadata call

Usage:
    .venv\\Scripts\\python.exe mcp_github_test.py [owner/repo]

Token: set GITHUB_MCP_TOKEN in the environment (PAT with repo read scope).
VS Code's Copilot OAuth session CANNOT be reused by an external client —
that token lives in VS Code's secret storage and is only injected into
VS Code's own MCP client.
"""

import asyncio
import json
import os
import sys

# Windows consoles default to cp1252 — force UTF-8 for box-drawing chars
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

from mcp import ClientSession
from mcp.client.streamable_http import (
    create_mcp_http_client,
    streamable_http_client,
)

GITHUB_REMOTE_MCP_URL = "https://api.githubcopilot.com/mcp/"
DEFAULT_REPO = "langchain-ai/langchain-mcp-adapters"


def load_token() -> str | None:
    """Read GITHUB_MCP_TOKEN from env or the backend .env file (no echo)."""
    token = os.getenv("GITHUB_MCP_TOKEN")
    if token:
        return token.strip()
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_path):
        with open(env_path, encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("GITHUB_MCP_TOKEN="):
                    value = line.split("=", 1)[1].strip()
                    return value or None
    return None


async def probe_without_auth() -> None:
    """Capture what the server does without a token — documents auth shape."""
    print("── Probe 1: unauthenticated request ──")
    try:
        async with streamable_http_client(GITHUB_REMOTE_MCP_URL) as streams:
            async with ClientSession(*streams) as session:
                await session.initialize()
        print("  unexpectedly succeeded (server allows anonymous?)")
    except BaseException as exc:  # noqa: BLE001 — diagnostics, print raw shape
        print(f"  result: {type(exc).__name__}: {str(exc)[:200]}")
        # Unwrap ExceptionGroup (anyio TaskGroup) to the real HTTP error
        subs = getattr(exc, "exceptions", None) or []
        for sub in subs:
            print(f"    → {type(sub).__name__}: {str(sub)[:250]}")
            status = getattr(sub, "status_code", None) or getattr(sub, "code", None)
            if status is not None:
                print(f"      HTTP/status: {status}")


async def probe_with_auth(token: str, repo: str) -> None:
    print("── Probe 2: authenticated request (Bearer token) ──")
    headers = {
        "Authorization": f"Bearer {token}",
        # Pin the tool set for read-only repo inspection
        "X-MCP-Toolsets": "repos",
    }
    http_client = create_mcp_http_client(headers=headers)
    async with streamable_http_client(
        GITHUB_REMOTE_MCP_URL, http_client=http_client
    ) as streams:
        async with ClientSession(*streams) as session:
            init = await session.initialize()
            print("  initialize OK")
            print(f"  serverInfo: name={init.server_info.name!r} "
                  f"version={init.server_info.version!r}")
            if init.instructions:
                print(f"  instructions: {init.instructions[:150]!r}")

            tools = await session.list_tools()
            print(f"  list_tools: {len(tools.tools)} tools exposed")
            for tool in tools.tools[:12]:
                print(f"    - {tool.name}: {(tool.description or '')[:70]}")
            if len(tools.tools) > 12:
                print(f"    ... and {len(tools.tools) - 12} more")

            # One real read-only call: fetch the repo root file listing
            owner, _, name = repo.partition("/")
            print(f"\n── Probe 3: call get_file_contents on {repo} (root listing) ──")
            result = await session.call_tool(
                "get_file_contents",
                {"owner": owner, "repo": name, "path": "."},
            )
            print(f"  isError: {result.is_error}")
            for block in result.content:
                kind = getattr(block, "type", "?")
                if kind == "text":
                    text = block.text
                    print(f"  content block: type=text, {len(text)} chars")
                    # Show the raw shape — first file entries
                    print("  raw response (first 800 chars):")
                    print("  " + text[:800].replace("\n", "\n  "))
                else:
                    print(f"  content block: type={kind}")


async def main() -> None:
    repo = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_REPO
    print(f"GitHub MCP connectivity test — target: {GITHUB_REMOTE_MCP_URL}")
    print(f"Test repo: {repo}\n")

    await probe_without_auth()

    token = load_token()
    if not token:
        print("\n── Probe 2/3 skipped: no GITHUB_MCP_TOKEN found ──")
        print("The remote GitHub MCP server requires its own auth token;")
        print("VS Code's Copilot session token cannot be reused externally.")
        print("Set GITHUB_MCP_TOKEN (PAT with repo read scope) and re-run.")
        return
    await probe_with_auth(token, repo)


if __name__ == "__main__":
    asyncio.run(main())

