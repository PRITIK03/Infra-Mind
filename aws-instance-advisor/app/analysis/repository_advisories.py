"""Check exact npm/Python versions against an operator-provided offline OSV database."""

from __future__ import annotations

import asyncio
import json
import os
import re
import tempfile
import tomllib
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import quote

_PACKAGE = re.compile(r"(?:@[a-z0-9_.-]+/)?[a-z0-9_.-]{1,150}", re.I | re.ASCII)
_VERSION = re.compile(r"[0-9][a-z0-9.+!_-]{0,49}", re.I | re.ASCII)
_PINNED_PYTHON = re.compile(r"^([a-z0-9_.-]+)(?:\[[a-z0-9_,.-]+\])?\s*==\s*([0-9][a-z0-9.+!_-]*)\s*(?:;|#|$)", re.I | re.ASCII)
_ADVISORY_ID = re.compile(r"(?:GHSA-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4}|CVE-\d{4}-\d{4,}|PYSEC-\d{4}-\d+|OSV-\d{4}-\d+|MAL-\d{4}-\d+)", re.ASCII)
_MAX_PACKAGES = 1500
_MAX_OUTPUT = 4 * 1024 * 1024


def _packages(path: str, content: str) -> Iterator[tuple[str, str, str]]:
    name = path.rsplit("/", 1)[-1].lower()
    if name in ("package-lock.json", "npm-shrinkwrap.json"):
        data = json.loads(content)
        packages = data.get("packages") if isinstance(data, dict) else None
        if isinstance(packages, dict):
            for location, item in packages.items():
                if "node_modules/" in location and isinstance(item, dict):
                    yield "npm", location.rsplit("node_modules/", 1)[1], item.get("version")
    elif name in ("uv.lock", "poetry.lock"):
        data = tomllib.loads(content).get("package")
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    yield "PyPI", item.get("name"), item.get("version")
    elif name.startswith("requirements") and name.endswith(".txt"):
        for line in content.splitlines():
            if match := _PINNED_PYTHON.match(line.strip()):
                yield "PyPI", match[1], match[2]


async def _run_offline(executable: Path, sbom: Path) -> dict:
    env = {key: value for key in ("SYSTEMROOT", "OSV_SCANNER_LOCAL_DB_CACHE_DIRECTORY")
           if (value := os.getenv(key))}
    env.update({"TMP": str(sbom.parent), "TEMP": str(sbom.parent), "TMPDIR": str(sbom.parent)})
    process = await asyncio.create_subprocess_exec(
        str(executable), "scan", "source", "--offline", "--format", "json", "--lockfile", str(sbom),
        cwd=sbom.parent, env=env, stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        output = bytearray()
        while chunk := await process.stdout.read(65536):
            output.extend(chunk)
            if len(output) > _MAX_OUTPUT:
                raise ValueError("Advisory output limit exceeded")
        code = await process.wait()
        if code not in (0, 1):
            raise ValueError("Advisory scan failed")
        data = json.loads(output)
        if isinstance(data, dict) and code == 0 and data.get("results") is None:
            return {"results": []}
        if not isinstance(data, dict) or not isinstance(data.get("results"), list):
            raise ValueError("Unexpected advisory output")
        return data
    finally:
        if process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            await process.wait()


async def check_advisories(files: dict[str, str]) -> tuple[str, list[tuple[str, str]]]:
    """Return safe advisory IDs and their source lockfile paths."""
    configured = os.getenv("REPOSITORY_OSV_SCANNER", "").strip()
    if not configured:
        return "not_configured", []
    executable = Path(configured)
    cache_directory = os.getenv("OSV_SCANNER_LOCAL_DB_CACHE_DIRECTORY", "").strip()
    if not executable.is_absolute() or not Path(cache_directory).is_absolute():
        return "unavailable", []

    coordinates: dict[tuple[str, str, str], str] = {}
    capped = False
    for path, content in files.items():
        try:
            for ecosystem, name, version in _packages(path, content):
                if (not isinstance(name, str) or not _PACKAGE.fullmatch(name)
                        or not isinstance(version, str) or not _VERSION.fullmatch(version)):
                    continue
                key = ecosystem, name.lower(), version
                if key not in coordinates and len(coordinates) >= _MAX_PACKAGES:
                    capped = True
                    break
                coordinates.setdefault(key, path)
        except (ValueError, RecursionError):
            capped = True
        if capped and len(coordinates) >= _MAX_PACKAGES:
            break
    if not coordinates:
        return ("partial" if capped else "no_supported_dependencies"), []

    components = [
        {
            "type": "library", "name": name, "version": version,
            "purl": f"pkg:{ecosystem.lower()}/{quote(name, safe='/')}@{quote(version, safe='')}",
        }
        for ecosystem, name, version in coordinates
    ]
    try:
        with tempfile.TemporaryDirectory(prefix="inframind-osv-") as directory:
            sbom = Path(directory) / "dependencies.cdx.json"
            sbom.write_text(json.dumps({
                "bomFormat": "CycloneDX", "specVersion": "1.4", "version": 1, "components": components,
            }), encoding="utf-8")
            async with asyncio.timeout(6):
                output = await _run_offline(executable, sbom)
    except (OSError, ValueError, TimeoutError, RecursionError):
        return "unavailable", []

    findings = {}
    for entry in output["results"]:
        packages = entry.get("packages") if isinstance(entry, dict) else None
        if not isinstance(packages, list):
            continue
        for item in packages:
            if not isinstance(item, dict) or not isinstance(package := item.get("package"), dict):
                continue
            parts = package.get("ecosystem"), package.get("name"), package.get("version")
            if not all(isinstance(part, str) for part in parts):
                continue
            ecosystem, name, version = parts
            path = coordinates.get((ecosystem, name.lower(), version))
            if path is None:
                continue
            vulnerabilities = item.get("vulnerabilities")
            if not isinstance(vulnerabilities, list):
                continue
            for vulnerability in vulnerabilities:
                identifier = vulnerability.get("id") if isinstance(vulnerability, dict) else None
                if isinstance(identifier, str) and _ADVISORY_ID.fullmatch(identifier):
                    findings.setdefault((identifier, path), None)
                    if len(findings) > 12:
                        return ("partial" if capped else "checked_capped"), list(findings)[:12]
    return ("partial" if capped else "checked"), list(findings)
