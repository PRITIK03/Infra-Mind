"""Analyze a public repository as inert data and emit only bounded findings."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import threading
import time
import tomllib
from collections import Counter
from collections.abc import Callable

import httpx

from app.analysis.repository_advisories import check_advisories
from app.models.repository import (
    FindingCategory,
    RepositoryFinding,
    RepositoryProgress,
    RepositoryRef,
    RepositoryReport,
)
from app.models.schemas import RepoAnalysis, WorkloadType
from app.tools.github_repository import GitHubRepository, RepositorySnapshot, RepositoryUnavailable, SnapshotLimit


logger = logging.getLogger(__name__)
_SCAN_SECONDS = 35
_SCAN_SLOTS = threading.BoundedSemaphore(2)
_RATE_LIMIT_LOCK = threading.Lock()
_RATE_LIMIT_UNTIL = 0.0
_REPORT_CACHE_LOCK = threading.Lock()
_REPORT_CACHE: dict[tuple[str, str, str, str], tuple[float, RepositoryReport]] = {}
_ANALYZER_VERSION = "1"
_CACHE_SECONDS = 300
_CACHE_SIZE = 32
_MAX_FINDINGS_PER_CATEGORY = 12

_FRAMEWORKS = {
    "fastapi": "FastAPI", "django": "Django", "flask": "Flask",
    "next": "Next.js", "express": "Express", "@nestjs/core": "NestJS",
    "react": "React", "vue": "Vue", "svelte": "Svelte",
}
_APP_EVIDENCE = (
    (re.compile(r"\bFastAPI\s*\("), "FastAPI", WorkloadType.API_SERVICE),
    (re.compile(r"\bFlask\s*\("), "Flask", WorkloadType.API_SERVICE),
    (re.compile(r"\bexpress\s*\("), "Express", WorkloadType.API_SERVICE),
    (re.compile(r"\bget_(?:wsgi|asgi)_application\s*\("), "Django", WorkloadType.WEB_APP),
    (re.compile(r"\bNestFactory\.create\s*\("), "NestJS", WorkloadType.API_SERVICE),
    (re.compile(r"\bhttp\.ListenAndServe(?:TLS)?\s*\("), "Go HTTP", WorkloadType.API_SERVICE),
    (re.compile(r"\bcreateRoot\s*\("), "React", WorkloadType.WEB_APP),
)
_DB_PATTERNS = (
    (re.compile(r"\b(?:postgres(?:ql)?(?:\+\w+)?://|psycopg[23]?\b|asyncpg\b|postgres:[\w.-]+|django\.db\.backends\.postgresql|provider\s*=\s*[\"']postgresql|CREATE\s+EXTENSION\b)", re.I), "PostgreSQL"),
    (re.compile(r"\b(?:mysql(?:\+\w+)?://|pymysql\b|mysql:[\w.-]+|django\.db\.backends\.mysql|provider\s*=\s*[\"']mysql|ENGINE\s*=\s*InnoDB\b)", re.I), "MySQL"),
    (re.compile(r"\b(?:sqlite3\b|sqlite(?:\+\w+)?://|django\.db\.backends\.sqlite3\b|provider\s*=\s*[\"']sqlite\b)", re.I), "SQLite"),
    (re.compile(r"\b(?:mongodb(?:\+srv)?://|pymongo\b|mongoose\b|mongo:[\w.-]+|provider\s*=\s*[\"']mongodb)", re.I), "MongoDB"),
    (re.compile(r"\b(?:redis(?:s)?://|redis:[\w.-]+|ioredis\b|Redis\s*\()", re.I), "Redis"),
    (re.compile(r"\b(?:DynamoDBClient|boto3\.(?:resource|client)\s*\(\s*[\"']dynamodb|aws_dynamodb_table)\b", re.I), "DynamoDB"),
)
_SQL_LINE = re.compile(r"\b(?:CREATE\s+(?:TABLE|INDEX)|ALTER\s+TABLE|SELECT\s+.+?\s+FROM|INSERT\s+INTO)\b", re.I)
_DATABASE_CONFIGURATION = re.compile(
    r"://|\bprovider\s*=|django\.db\.backends\.|^image:\s|\baws_dynamodb_table\b",
    re.I,
)
_WORKFLOWS = (
    (re.compile(r"\b(?:Celery\s*\(|@\w+\.task\b)"), "Celery"),
    (re.compile(r"\b(?:from\s+rq\s+import|rq\.Queue\s*\()"), "RQ"),
    (re.compile(r"\b(?:from\s+[\"']bullmq|require\([\"']bullmq)"), "BullMQ"),
    (re.compile(r"\b(?:SQSClient|sqs\.(?:send_message|receive_message)\s*\()"), "Amazon SQS"),
    (re.compile(r"\b(?:CronJob|APScheduler|BackgroundScheduler\s*\()"), "Scheduled jobs"),
)
_LOCAL_MODEL = re.compile(r"\b(?:SentenceTransformer|(?:[A-Za-z0-9_]+\.)?from_pretrained|torch\.load|InferenceSession|llama_cpp\.Llama|load_model)\s*\(")
_HOSTED_MODEL = re.compile(r"\b(?:AsyncOpenAI|OpenAI|ChatOpenAI|Anthropic|ChatAnthropic|InferenceClient)\s*\(")
_MODEL_TUNING = (
    (re.compile(r"\b(?:load_in_4bit|load_in_8bit|BitsAndBytesConfig|quantization_config)\b"), "Quantization"),
    (re.compile(r"\b(?:batch_size|dynamic_batching|max_batch_size)\b"), "Batching"),
    (re.compile(r"\b(?:device_map|CUDAExecutionProvider|torch\.device|\.to\([\"']cuda)"), "Device selection"),
)
_SOURCE_SUFFIXES = frozenset({
    "py", "js", "ts", "jsx", "tsx", "mjs", "cjs", "go", "rs", "java", "kt", "rb",
    "cs", "php", "sql", "prisma", "toml", "json", "yml", "yaml", "tf", "ini",
    "cfg", "conf", "properties", "sh",
})
_ENV_EXAMPLE = re.compile(r"(?:^|\.)(?:example|sample|template|dist)(?:\.|$)", re.I)
_SECRET_SIGNATURE = re.compile(
    r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----"
    r"|\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"
    r"|\b(?:gh[pousr]_[A-Za-z0-9]{30,255}|github_pat_[A-Za-z0-9_]{30,255})\b"
    r"|\b(?:xox[baprs]-[A-Za-z0-9-]{12,255}|sk-(?:proj-|ant-api\d+-|live-)?[A-Za-z0-9_-]{24,255})\b"
)
_CREDENTIAL_URI = re.compile(r"\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|rediss?|amqps?)://[^\s:@/]{1,100}:([^\s@/'\"\x60]{1,200})@", re.I)
_SECRET_ASSIGNMENT = re.compile(
    r"""(?ix)\b(?:[A-Z0-9_]*?(?:api[_-]?key|(?:access|private|secret)[_-]?key|(?:access|auth)[_-]?token|password|client[_-]?secret))
        [\"']?\s*[:=]\s*[\"']([^\s\"']{10,180})[\"']"""
)
_ENV_ASSIGNMENT = re.compile(r"(?i)^\s*(?:export\s+)?[A-Z0-9_]*(?:KEY|TOKEN|PASSWORD|SECRET)\s*=\s*([^\s#]+)")
_PLACEHOLDER = re.compile(r"(?i)^(?:example|changeme|change.me|your[_ -]|dummy|placeholder|replace[_ -]|test[_-]|fake[_-]|<|\$|\*|x{4}|password$)")
_SAFE_PATH = re.compile(r"[a-z0-9_.@+/ -]{1,240}", re.IGNORECASE | re.ASCII)
_FINDING_PRIORITY = {"high": 0, "review": 1, "info": 2}


def safe_evidence_path(path: str) -> str | None:
    # Keep attacker-controlled markup, controls, and likely token values out
    # of reports, links and exported Markdown.
    if (_SAFE_PATH.fullmatch(path) and not _SECRET_SIGNATURE.search(path)
            and all(0 < len(part) <= 64 and part not in (".", "..") for part in path.split("/"))):
        return path
    return None


def _dependencies(name: str, content: str) -> set[str]:
    try:
        if name == "package.json":
            manifest = json.loads(content)
            deps = manifest.get("dependencies") if isinstance(manifest, dict) else None
            return {key.lower() for key in deps} if isinstance(deps, dict) else set()
        if name == "pyproject.toml":
            manifest = tomllib.loads(content)
            project = manifest.get("project")
            deps = project.get("dependencies") if isinstance(project, dict) else None
            tool = manifest.get("tool")
            poetry = tool.get("poetry") if isinstance(tool, dict) else None
            poetry_deps = poetry.get("dependencies") if isinstance(poetry, dict) else None
            names = set(poetry_deps or {}) if isinstance(poetry_deps, dict) else set()
            lines = deps if isinstance(deps, list) else []
        elif name.startswith("requirements") and name.endswith(".txt"):
            names, lines = set(), content.splitlines()
        else:
            return set()
    except (ValueError, RecursionError):
        return set()
    for line in lines:
        if isinstance(line, str) and (match := re.match(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*", line.strip())):
            names.add(match.group().lower())
    return names


def _credential_kind(line: str, *, dotenv: bool) -> str | None:
    if _SECRET_SIGNATURE.search(line):
        return "Token or private-key pattern"
    match = _CREDENTIAL_URI.search(line) or _SECRET_ASSIGNMENT.search(line)
    if match is None and dotenv:
        match = _ENV_ASSIGNMENT.match(line)
    if match and not _PLACEHOLDER.match(match[1].strip("\"'")):
        return "Possible hardcoded credential"
    return None


def analyze_snapshot(snapshot: RepositorySnapshot, deadline: float) -> RepositoryReport:
    stack: set[str] = set()
    databases: set[str] = set()
    configured_databases: set[str] = set()
    workflows: set[str] = set()
    observed_workloads: set[WorkloadType] = set()
    findings: list[RepositoryFinding] = []
    finding_counts: Counter[str] = Counter()
    skipped = snapshot.skipped.copy()
    limitations = list(snapshot.limitations)
    finding_keys = set()
    has_dockerfile = local_inference = hosted_inference = False
    scanned = 0

    def record(
        category: FindingCategory, title: str, action: str, path: str, line: int | None = None,
        *, severity: str = "info", confidence: str = "observed", per_file: bool = False,
    ) -> None:
        key = category, title, path if per_file else None
        if key in finding_keys:
            return
        finding_keys.add(key)
        retain = finding_counts[category] < _MAX_FINDINGS_PER_CATEGORY
        if not retain and severity != "info":
            for index in range(len(findings) - 1, -1, -1):
                old = findings[index]
                if old.category == category and _FINDING_PRIORITY[old.severity] > _FINDING_PRIORITY[severity]:
                    findings.pop(index)
                    retain = True
                    break
        if retain:
            findings.append(RepositoryFinding(
                category=category, title=title, action=action, path=safe_evidence_path(path),
                line=line, severity=severity, confidence=confidence,
            ))
        finding_counts[category] += 1

    for path, content in snapshot.files.items():
        if time.monotonic() >= deadline:
            skipped["scan_budget"] += len(snapshot.files) - scanned
            limitations.append("Analysis reached its time limit.")
            break
        scanned += 1
        lower_path = path.lower()
        name = lower_path.rsplit("/", 1)[-1]
        suffix = name.rpartition(".")[2]
        sample = bool(_ENV_EXAMPLE.search(name))
        dotenv = name == ".env" or name.startswith(".env.")
        tests_or_docs = (
            any(part in ("test", "tests", "spec", "__tests__", "examples", "docs") for part in lower_path.split("/")[:-1])
            or name.startswith("test_") or ".test." in name or ".spec." in name or sample
        )
        if dotenv and not sample:
            record(
                "security", "Environment file tracked in Git",
                "Move deployment secrets to a secret manager. Review the file and rotate any exposed credentials.",
                path, severity="review", per_file=True,
            )
        lines = content.splitlines()
        for number, line in enumerate(lines, 1):
            if time.monotonic() >= deadline:
                break
            if kind := _credential_kind(line, dotenv=dotenv):
                record(
                    "security", kind,
                    "Verify privately. Rotate the credential if real and remove the exposed value from the repository and its history.",
                    path, number, severity="high", confidence="inferred", per_file=True,
                )
        if time.monotonic() >= deadline:
            scanned -= 1
            skipped["scan_budget"] += len(snapshot.files) - scanned
            limitations.append("Analysis reached its time limit.")
            break
        if tests_or_docs:
            continue

        dependencies = _dependencies(name, content)
        for package in sorted(dependencies & _FRAMEWORKS.keys()):
            framework = _FRAMEWORKS[package]
            stack.add(framework)
            record("application", f"{framework} declared", "Confirm which service uses this runtime in production.", path)
        if name.startswith("next.config.") or (
            "Next.js" in stack and re.search(r"(?:^|/)app/(?:[^/]+/)*page\.[jt]sx?$", lower_path)
        ):
            observed_workloads.add(WorkloadType.WEB_APP)
            stack.add("Next.js")
            record("application", "Next.js application", "Include the web application in the deployment plan.", path)
        if name.startswith("dockerfile") or name.endswith(".dockerfile"):
            has_dockerfile = True
            record("deployment", "Dockerfile found", "Verify build context, runtime settings, and container privileges before deploying.", path, per_file=True)
            if not re.search(r"^\s*HEALTHCHECK\b", content, re.M | re.I):
                record("deployment", "Container health check to verify", "Configure an application health check in the image or on the deployment platform.", path, severity="review", per_file=True)
        if lower_path.startswith(".github/workflows/") and suffix in ("yml", "yaml"):
            workflows.add("GitHub Actions")
            record("workflow", "GitHub Actions workflow", "Confirm the deployment job, required secrets, and approval gates.", path, per_file=True)
            if re.search(r"\bpull_request_target\s*:", content) and re.search(r"pull_request\.head\.(?:sha|ref)", content):
                record("security", "Privileged pull-request workflow to review", "Verify that this workflow cannot execute contributor code with privileged secrets or tokens.", path, severity="review", confidence="inferred", per_file=True)
        if name in ("compose.yaml", "compose.yml", "docker-compose.yml", "docker-compose.yaml"):
            record("deployment", "Compose configuration", "Map each service and volume to its production equivalent.", path)
        if suffix == "tf":
            record("deployment", "Terraform configuration", "Check existing state and infrastructure before applying generated Terraform.", path)
        if name in ("render.yaml", "vercel.json", "fly.toml", "railway.json", "helmfile.yaml", "chart.yaml"):
            record("deployment", "Platform deployment configuration", "Reconcile the existing deployment settings with the AWS plan.", path, per_file=True)
        if re.search(r"(?:^|/)(?:migrations?|alembic|prisma)(?:/|\.)", lower_path):
            record("database", "Migration files detected", "Include a migration step, backups, and a tested rollback in the deployment plan.", path)
        if suffix not in _SOURCE_SUFFIXES and not dotenv and not name.startswith("dockerfile"):
            continue
        if name in ("package-lock.json", "npm-shrinkwrap.json", "pnpm-lock.yaml", "yarn.lock", "uv.lock"):
            continue
        for number, line in enumerate(lines, 1):
            if time.monotonic() >= deadline:
                break
            # Bound matching work on minified or generated single lines.
            line = line[:4096].strip()
            if not line or line.startswith(("#", "//", "--", "/*", "*")):
                continue
            for pattern, framework, workload in _APP_EVIDENCE:
                if pattern.search(line):
                    stack.add(framework)
                    observed_workloads.add(workload)
                    record("application", f"{framework} entry point", "Confirm the production entry point and startup command.", path, number)
            for pattern, engine in _DB_PATTERNS:
                if pattern.search(line):
                    databases.add(engine)
                    if _DATABASE_CONFIGURATION.search(line):
                        configured_databases.add(engine)
                    record("database", f"{engine} referenced", "Verify where this data store runs in production and whether it needs migration.", path, number)
            if _SQL_LINE.search(line):
                record("database", "SQL usage detected", "Check query plans, indexes, and connection limits under representative load.", path, number)
            for pattern, workflow in _WORKFLOWS:
                if pattern.search(line):
                    workflows.add(workflow)
                    record("workflow", f"{workflow} usage", "Size and monitor workers independently of request-serving capacity.", path, number)
            if _LOCAL_MODEL.search(line):
                local_inference = True
                record("inference", "Local model loading detected", "Measure model memory, startup time, and throughput. Benchmark smaller or quantized weights before sizing GPUs.", path, number)
            if _HOSTED_MODEL.search(line):
                hosted_inference = True
                record("inference", "Hosted inference client detected", "Budget for provider latency and quotas, and size the application separately from the model.", path, number)
            for pattern, tuning in _MODEL_TUNING:
                if pattern.search(line):
                    record("inference", f"{tuning} setting detected", "Benchmark this setting against production latency and throughput goals.", path, number, confidence="inferred")
            if re.search(r"^kind:\s*(?:Deployment|StatefulSet|CronJob|Service)\s*$", line):
                record("deployment", "Kubernetes resource detected", "Review resource requests, probes, and rollout settings.", path, number)
        if time.monotonic() >= deadline:
            scanned -= 1
            skipped["scan_budget"] += len(snapshot.files) - scanned
            limitations.append("Analysis reached its time limit.")
            break

    for artifact in snapshot.model_artifacts[:3]:
        size_mib = artifact.size / (1024 * 1024)
        size_note = f"The Git blob is {size_mib:.1f} MiB." if size_mib >= 0.1 else "The Git blob is small and may be a pointer."
        record("inference", "Tracked model artifact", f"{size_note} Verify the stored artifact size and measure runtime memory before sizing.", artifact.path, per_file=True)
    if any(count > _MAX_FINDINGS_PER_CATEGORY for count in finding_counts.values()):
        limitations.append("The report shows a capped number of findings per category.")
    if local_inference and WorkloadType.API_SERVICE in observed_workloads:
        workload = WorkloadType.ML_INFERENCE
    elif WorkloadType.WEB_APP in observed_workloads:
        workload = WorkloadType.WEB_APP
    elif len(observed_workloads) == 1:
        workload = next(iter(observed_workloads))
    elif not observed_workloads and workflows.intersection({"Celery", "RQ", "BullMQ", "Scheduled jobs"}):
        workload = WorkloadType.BATCH_PROCESSING
    else:
        workload = None
    coverage = "partial" if snapshot.limitations or any(
        skipped[key] for key in ("scan_budget", "file_size_limit", "unreadable", "unsupported_encoding")
    ) else "complete"
    return RepositoryReport(
        repository=snapshot.commit.repository, commit_sha=snapshot.commit.sha,
        coverage=coverage, files_discovered=snapshot.files_discovered, files_analyzed=scanned,
        skipped=dict(skipped), limitations=limitations, stack=sorted(stack),
        databases=sorted(databases), configured_databases=sorted(configured_databases),
        workflows=sorted(workflows), workload_type=workload,
        has_dockerfile=has_dockerfile, local_inference=local_inference,
        hosted_inference=hosted_inference, model_artifacts=len(snapshot.model_artifacts),
        findings=sorted(findings, key=lambda finding: _FINDING_PRIORITY[finding.severity]),
    )


def reasoner_context(report: RepositoryReport) -> RepoAnalysis:
    """Translate allowlisted facts into the existing reasoner's contract."""
    facts = []
    if report.databases:
        facts.append("Data stores referenced: " + ", ".join(report.databases))
    if report.configured_databases:
        facts.append("Data stores found in configuration: " + ", ".join(report.configured_databases))
    if report.workflows:
        facts.append("Workflows detected: " + ", ".join(report.workflows))
    if report.local_inference:
        facts.append("Local model loading observed; measure memory and benchmark CPU or GPU before sizing")
    if report.hosted_inference:
        facts.append("Hosted inference client observed; provider inference is external to this service")
    if report.model_artifacts:
        facts.append("Tracked model artifacts found; the runtime memory requirement is unknown")
    if report.coverage == "partial":
        facts.append("Coverage is partial; missing evidence is not evidence of absence")
    return RepoAnalysis(
        detected_language=", ".join(report.stack) or None,
        has_dockerfile=report.has_dockerfile,
        notable_dependencies=[],
        analysis_note="; ".join(facts) or "No supported workload signals were confirmed in the scanned files.",
    )


def repository_scan_enabled() -> bool:
    return os.getenv("REPOSITORY_ANALYSIS_ENABLED", "true").strip().lower() in ("true", "1", "yes")


def scan_repository(
    ref: RepositoryRef, on_scanning: Callable[[], None] = lambda: None,
) -> tuple[RepositoryProgress, RepositoryReport | None]:
    if not repository_scan_enabled():
        return RepositoryProgress(status="unavailable", reason="disabled"), None
    with _RATE_LIMIT_LOCK:
        cooldown = _RATE_LIMIT_UNTIL - time.monotonic()
    if cooldown > 0:
        return RepositoryProgress(status="unavailable", reason="rate_limited", retry_after_seconds=int(cooldown) + 1), None
    if not _SCAN_SLOTS.acquire(blocking=False):
        return RepositoryProgress(status="unavailable", reason="busy", retry_after_seconds=5), None

    started = time.monotonic()
    report = None
    try:
        report = asyncio.run(_scan(ref, on_scanning, started + _SCAN_SECONDS))
        progress = RepositoryProgress(status=report.coverage)
    except RepositoryUnavailable as exc:
        if exc.reason == "rate_limited":
            _pause_github_reads(exc.retry_after or 60)
        progress = RepositoryProgress(status="unavailable", reason=exc.reason, retry_after_seconds=exc.retry_after)
    except (TimeoutError, httpx.TimeoutException):
        progress = RepositoryProgress(status="unavailable", reason="timeout")
    except SnapshotLimit:
        progress = RepositoryProgress(status="unavailable", reason="no_source")
    except httpx.HTTPError:
        progress = RepositoryProgress(status="unavailable", reason="unavailable")
    finally:
        _SCAN_SLOTS.release()
    logger.info(
        "repository_scan status=%s reason=%s duration_ms=%d files_analyzed=%d",
        progress.status, progress.reason, int((time.monotonic() - started) * 1000),
        report.files_analyzed if report else 0,
    )
    return progress, report


def _pause_github_reads(seconds: int) -> None:
    global _RATE_LIMIT_UNTIL
    with _RATE_LIMIT_LOCK:
        _RATE_LIMIT_UNTIL = max(_RATE_LIMIT_UNTIL, time.monotonic() + seconds)


async def _scan(ref: RepositoryRef, on_scanning: Callable[[], None], deadline: float) -> RepositoryReport:
    token = os.getenv("REPOSITORY_GITHUB_TOKEN", "").strip() or None
    async with (
        asyncio.timeout(max(0.0, deadline - time.monotonic())),
        httpx.AsyncClient(timeout=httpx.Timeout(8.0, connect=4.0), follow_redirects=False, trust_env=False) as client,
    ):
        github = GitHubRepository(client, token)
        commit = await github.resolve(ref)
        on_scanning()
        cache_key = (
            commit.repository.full_name.lower(), commit.sha, _ANALYZER_VERSION,
            os.getenv("REPOSITORY_OSV_SCANNER", ""),
        )
        with _REPORT_CACHE_LOCK:
            cached = _REPORT_CACHE.get(cache_key)
            if cached and cached[0] > time.monotonic():
                return cached[1].model_copy(deep=True)
        snapshot = await github.snapshot(commit)
        if snapshot.retry_after_seconds:
            _pause_github_reads(snapshot.retry_after_seconds)
        if not snapshot.files:
            raise RepositoryUnavailable("no_source" if snapshot.files_discovered else "empty")
        if token:
            # Recheck before publishing evidence when authenticated file
            # reads might succeed after a public repository became private.
            await github.public_metadata(commit.repository)
        report = analyze_snapshot(snapshot, deadline)
        if not report.files_analyzed:
            raise RepositoryUnavailable("timeout")
        # This optional pass uses only package coordinates, a fixed local
        # scanner, and an operator-managed offline advisory database.
        try:
            async with asyncio.timeout(max(0.0, min(6.0, deadline - time.monotonic() - 0.25))):
                advisory_status, advisories = await check_advisories(snapshot.files)
        except TimeoutError:
            advisory_status, advisories = "unavailable", []
        report.advisory_status = advisory_status
        report.findings.extend(
            RepositoryFinding(
                category="security", title=f"Dependency advisory {identifier}", severity="review",
                action="Review the advisory and upgrade the affected dependency to a supported fixed version.",
                path=safe_evidence_path(path),
            )
            for identifier, path in advisories
        )
        if report.coverage == "complete" and report.advisory_status != "unavailable":
            with _REPORT_CACHE_LOCK:
                _REPORT_CACHE.pop(cache_key, None)
                if len(_REPORT_CACHE) >= _CACHE_SIZE:
                    _REPORT_CACHE.pop(next(iter(_REPORT_CACHE)))
                _REPORT_CACHE[cache_key] = time.monotonic() + _CACHE_SECONDS, report.model_copy(deep=True)
        return report
