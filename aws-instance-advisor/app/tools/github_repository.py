"""Read a bounded, commit-pinned snapshot of a public GitHub repository."""

from __future__ import annotations

import hashlib
import io
import json
import re
import tarfile
import time
import zlib
from collections import Counter, deque
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

import httpx

from app.models.repository import RepositoryReason, RepositoryRef, parse_repository_url


_API = "https://api.github.com"
_SHA = re.compile(r"[a-f0-9]{40}", re.ASCII)
_MAX_TREE_ENTRIES = 20_000
_MAX_TREE_READS = 10
_MAX_ARCHIVE_BYTES = 16 * 1024 * 1024
_MAX_EXPANDED_BYTES = 32 * 1024 * 1024
_MAX_SOURCE_BYTES = 8 * 1024 * 1024
_MAX_FILE_BYTES = 1024 * 1024
_MAX_FILES = 1500
_MAX_BLOB_READS = 12
_EXCLUDED_DIRS = frozenset({
    ".git", ".next", ".venv", "venv", "node_modules", "vendor", "dist", "build",
    "__pycache__", ".cache", "coverage",
})
_BINARY_SUFFIXES = frozenset({
    "png", "jpg", "jpeg", "gif", "webp", "ico", "pdf", "woff", "woff2", "ttf",
    "jar", "zip", "gz", "bz2", "xz", "7z", "mp4", "mp3", "exe", "dll", "so",
})
MODEL_SUFFIXES = frozenset({"pt", "pth", "onnx", "safetensors", "gguf", "tflite", "ckpt", "h5", "pkl", "pickle"})


class RepositoryUnavailable(Exception):
    """Safe, typed upstream failure. HTTP bodies and URLs stay internal."""

    def __init__(self, reason: RepositoryReason, retry_after: int | None = None):
        super().__init__(reason)
        self.reason = reason
        self.retry_after = retry_after


class SnapshotLimit(Exception):
    pass


@dataclass(frozen=True)
class Commit:
    repository: RepositoryRef
    sha: str
    tree_sha: str

    @property
    def api_path(self) -> str:
        return f"/repos/{self.repository.full_name}"


@dataclass(frozen=True)
class TreeEntry:
    path: str
    mode: str
    sha: str
    size: int


@dataclass
class RepositorySnapshot:
    commit: Commit
    files_discovered: int
    files: dict[str, str] = field(default_factory=dict)
    skipped: Counter[str] = field(default_factory=Counter)
    limitations: list[str] = field(default_factory=list)
    model_artifacts: list[TreeEntry] = field(default_factory=list)
    retry_after_seconds: int | None = None


def _checked_status(response: httpx.Response) -> None:
    status = response.status_code
    if status == 200:
        return
    retry = response.headers.get("retry-after", "")
    remaining = response.headers.get("x-ratelimit-remaining")
    if status == 429 or (status == 403 and (remaining == "0" or retry)):
        seconds = int(retry) if retry.isascii() and retry.isdecimal() and len(retry) <= 8 else None
        reset = response.headers.get("x-ratelimit-reset", "")
        if seconds is None and remaining == "0" and reset.isascii() and reset.isdecimal() and len(reset) <= 12:
            seconds = max(1, int(int(reset) - time.time()))
        raise RepositoryUnavailable("rate_limited", seconds or 60)
    if status in (403, 404, 451):
        raise RepositoryUnavailable("not_accessible")
    if status == 409:
        raise RepositoryUnavailable("empty")
    raise RepositoryUnavailable("unavailable")


async def _read(response: httpx.Response, max_bytes: int) -> bytes:
    data = bytearray()
    async for chunk in response.aiter_bytes():
        if len(data) + len(chunk) > max_bytes:
            raise SnapshotLimit
        data.extend(chunk)
    return bytes(data)


class GitHubRepository:
    def __init__(self, client: httpx.AsyncClient, token: str | None = None):
        self.client = client
        self.headers = {
            "Accept": "application/vnd.github+json",
            "Accept-Encoding": "identity",
            "User-Agent": "InfraMind-Repository-Analysis",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if token:
            self.headers["Authorization"] = f"Bearer {token}"

    async def _json(self, path: str, *, allow_repository_move: bool = False) -> dict[str, Any]:
        redirect = None
        async with self.client.stream("GET", _API + path, headers=self.headers) as response:
            if allow_repository_move and response.status_code == 301:
                location = response.headers.get("location", "")
                if re.fullmatch(r"https://api\.github\.com/repositories/[0-9]+", location):
                    redirect = location.removeprefix(_API)
            if redirect is None:
                _checked_status(response)
                try:
                    payload = json.loads(await _read(response, 8 * 1024 * 1024))
                except (ValueError, RecursionError):
                    raise RepositoryUnavailable("unavailable") from None
                if isinstance(payload, dict):
                    return payload
                raise RepositoryUnavailable("unavailable")
        return await self._json(redirect)

    async def public_metadata(self, ref: RepositoryRef) -> dict[str, Any]:
        metadata = await self._json(f"/repos/{ref.full_name}", allow_repository_move=True)
        if metadata.get("private") is True or metadata.get("visibility") in ("private", "internal"):
            # A mis-scoped service credential must not reveal whether a
            # specific private repository exists to an anonymous caller.
            reason = "not_accessible" if "Authorization" in self.headers else "not_public"
            raise RepositoryUnavailable(reason)
        if metadata.get("private") is not False:
            raise RepositoryUnavailable("unavailable")
        return metadata

    async def resolve(self, ref: RepositoryRef) -> Commit:
        metadata = await self.public_metadata(ref)
        name, branch = metadata.get("full_name"), metadata.get("default_branch")
        if not isinstance(name, str) or not isinstance(branch, str) or not branch or len(branch) > 256:
            raise RepositoryUnavailable("empty" if branch == "" else "unavailable")
        try:
            canonical_ref = parse_repository_url(f"https://github.com/{name}")
        except ValueError:
            raise RepositoryUnavailable("unavailable") from None
        commit = await self._json(f"/repos/{canonical_ref.full_name}/commits/{quote(branch, safe='')}")
        sha = commit.get("sha")
        commit_data = commit.get("commit")
        tree = commit_data.get("tree") if isinstance(commit_data, dict) else None
        tree_sha = tree.get("sha") if isinstance(tree, dict) else None
        if not _valid_sha(sha) or not _valid_sha(tree_sha):
            raise RepositoryUnavailable("unavailable")
        return Commit(canonical_ref, sha, tree_sha)

    async def _tree(self, commit: Commit) -> tuple[list[TreeEntry], bool]:
        endpoint = f"{commit.api_path}/git/trees/"
        payload = await self._json(f"{endpoint}{commit.tree_sha}?recursive=1")
        if payload.get("truncated") is False:
            return _tree_entries(payload), len(payload["tree"]) > _MAX_TREE_ENTRIES
        entries = []
        pending = deque([("", commit.tree_sha)])
        incomplete = False
        for _ in range(_MAX_TREE_READS):
            if not pending or len(entries) >= _MAX_TREE_ENTRIES:
                break
            prefix, sha = pending.popleft()
            try:
                tree = await self._json(endpoint + sha)
            except RepositoryUnavailable as exc:
                if not entries or exc.reason == "rate_limited":
                    raise
                incomplete = True
                break
            except SnapshotLimit:
                if not entries:
                    raise
                incomplete = True
                break
            incomplete |= tree.get("truncated") is not False or len(tree.get("tree", [])) > _MAX_TREE_ENTRIES
            for entry in _tree_entries(tree, prefix):
                if entry.mode == "040000":
                    pending.append((f"{entry.path}/", entry.sha))
                else:
                    entries.append(entry)
                if len(entries) >= _MAX_TREE_ENTRIES:
                    incomplete = True
                    break
        return entries, incomplete or bool(pending)

    async def _archive(self, commit: Commit) -> bytes:
        async with self.client.stream(
            "GET", f"{_API}{commit.api_path}/tarball/{commit.sha}", headers=self.headers,
        ) as response:
            if response.status_code != 302:
                _checked_status(response)
                raise RepositoryUnavailable("unavailable")
            target = httpx.URL(response.headers.get("location", ""))
        if (target.scheme != "https" or target.host != "codeload.github.com"
                or target.port not in (None, 443) or target.userinfo or target.fragment):
            raise RepositoryUnavailable("unavailable")
        # Only GitHub's archive host receives the request, with no token.
        async with self.client.stream("GET", target, headers={"Accept-Encoding": "identity"}) as response:
            _checked_status(response)
            compressed = 0
            archive = bytearray()
            decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)
            async for chunk in response.aiter_raw():
                compressed += len(chunk)
                if compressed > _MAX_ARCHIVE_BYTES:
                    raise SnapshotLimit
                remaining = _MAX_EXPANDED_BYTES - len(archive)
                archive.extend(decompressor.decompress(chunk, remaining + 1))
                if len(archive) > _MAX_EXPANDED_BYTES:
                    raise SnapshotLimit
            if not decompressor.eof or decompressor.unused_data:
                raise tarfile.ReadError("Incomplete or unexpected archive")
        return bytes(archive)

    async def snapshot(self, commit: Commit) -> RepositorySnapshot:
        entries, incomplete = await self._tree(commit)
        files = {entry.path: entry for entry in entries if entry.mode != "040000"}
        snapshot = RepositorySnapshot(commit=commit, files_discovered=len(files))
        if incomplete:
            snapshot.limitations.append("GitHub's file inventory exceeded the scan budget.")
        selected = {}
        selected_bytes = 0
        for path, entry in sorted(files.items(), key=lambda item: (_priority(item[0]), item[0])):
            suffix = path.rpartition(".")[2].lower()
            if entry.mode not in ("100644", "100755"):
                snapshot.skipped["link_or_submodule"] += 1
            elif _EXCLUDED_DIRS.intersection(part.lower() for part in path.split("/")[:-1]):
                snapshot.skipped["generated_or_vendored"] += 1
            elif suffix in MODEL_SUFFIXES:
                snapshot.skipped["binary"] += 1
                snapshot.model_artifacts.append(entry)
            elif suffix in _BINARY_SUFFIXES:
                snapshot.skipped["binary"] += 1
            elif entry.size > _MAX_FILE_BYTES:
                snapshot.skipped["file_size_limit"] += 1
            elif len(selected) >= _MAX_FILES or selected_bytes + entry.size > _MAX_SOURCE_BYTES:
                snapshot.skipped["scan_budget"] += 1
            else:
                selected[path] = entry
                selected_bytes += entry.size
        if not selected:
            return snapshot

        raw = {}
        try:
            archive = await self._archive(commit)
            with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as tar:
                for member in tar:
                    path = member.name.partition("/")[2]
                    entry = selected.get(path)
                    if entry and member.isfile() and member.size == entry.size and not member.issparse():
                        file = tar.extractfile(member)
                        if file is not None:
                            with file:
                                content = file.read(entry.size)
                            if _matches_blob(entry, content):
                                raw[path] = content
        except RepositoryUnavailable as exc:
            if exc.reason == "rate_limited":
                raise
        except (SnapshotLimit, httpx.HTTPError, tarfile.TarError, OSError, zlib.error, ValueError):
            # The inventory still identifies the important blobs to try next.
            pass
        missing = [entry for path, entry in selected.items() if path not in raw]
        for entry in missing[:_MAX_BLOB_READS]:
            try:
                async with self.client.stream(
                    "GET", f"{_API}{commit.api_path}/git/blobs/{entry.sha}",
                    headers={**self.headers, "Accept": "application/vnd.github.raw+json"},
                ) as response:
                    _checked_status(response)
                    content = await _read(response, entry.size)
                if _matches_blob(entry, content):
                    raw[entry.path] = content
            except RepositoryUnavailable as exc:
                if exc.reason in ("rate_limited", "not_public", "unavailable"):
                    if not raw:
                        raise
                    if exc.reason == "rate_limited":
                        snapshot.retry_after_seconds = exc.retry_after
                        snapshot.limitations.append("GitHub limited the remaining file requests.")
                    break
            except (SnapshotLimit, httpx.HTTPError):
                continue
        for path in selected:
            content = raw.get(path)
            if content is None:
                snapshot.skipped["unreadable"] += 1
            elif b"\x00" in content or content.startswith(b"version https://git-lfs.github.com/spec/"):
                snapshot.skipped["binary"] += 1
            else:
                try:
                    snapshot.files[path] = content.decode("utf-8-sig")
                except UnicodeDecodeError:
                    snapshot.skipped["unsupported_encoding"] += 1
        return snapshot


def _valid_sha(value: Any) -> bool:
    return isinstance(value, str) and bool(_SHA.fullmatch(value))


def _tree_entries(payload: dict[str, Any], prefix: str = "") -> list[TreeEntry]:
    items = payload.get("tree")
    if not isinstance(items, list):
        raise RepositoryUnavailable("unavailable")
    entries = []
    for item in items[:_MAX_TREE_ENTRIES]:
        if not isinstance(item, dict):
            raise RepositoryUnavailable("unavailable")
        path, mode, sha, size = (item.get(key) for key in ("path", "mode", "sha", "size"))
        if (not isinstance(path, str) or not path or not _valid_sha(sha)
                or mode not in ("040000", "160000", "120000", "100644", "100755")
                or len(prefix) + len(path) > 4096 or "\\" in path or "\x00" in path
                or any(part in ("", ".", "..") for part in path.split("/"))):
            raise RepositoryUnavailable("unavailable")
        if mode in ("100644", "100755") and (type(size) is not int or size < 0):
            raise RepositoryUnavailable("unavailable")
        entries.append(TreeEntry(f"{prefix}{path}", mode, sha, size or 0))
    return entries


def _matches_blob(entry: TreeEntry, content: bytes) -> bool:
    # Verify that archive bytes are exactly the tracked Git blob. Archives
    # can substitute or omit files based on .gitattributes.
    digest = hashlib.sha1(usedforsecurity=False)
    digest.update(f"blob {len(content)}\0".encode("ascii"))
    digest.update(content)
    return len(content) == entry.size and digest.hexdigest() == entry.sha


def _priority(path: str) -> int:
    name = path.rsplit("/", 1)[-1].lower()
    if (name.startswith((".env", "dockerfile", "requirements", "compose", "docker-compose"))
            or name in ("package.json", "pyproject.toml", "go.mod", "cargo.toml", "gemfile", "pom.xml")
            or path.startswith(".github/workflows/")):
        return 0
    if name.endswith((".py", ".ts", ".js", ".sql", ".tf", ".yaml", ".yml", ".go", ".rs", ".java")):
        return 1
    return 2
