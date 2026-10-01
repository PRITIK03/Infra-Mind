"""
Liveness vs. readiness checks (Part B production readiness).

* Liveness (``GET /api/health``) answers whether the process itself can
  respond — it performs nothing beyond formatting ``{"status": "ok"}``.
* Readiness (``GET /api/health/ready``, built here) answers whether the
  process is *configured to serve* — purely local, zero-outbound checks,
  because a load balancer or monitor hitting this endpoint every few
  seconds must never burn LLM/live-data quota or wait on a provider:

  - required config vars present (API_KEY, BASE_URL, MODEL_NAME,
    VANTAGE_API_KEY, CORS_ALLOWED_ORIGIN) — read straight from the
    environment, never ``_require()``, so the endpoint reports rather
    than raising;
  - Redis reachable **only if** REDIS_URL is configured — one lightweight
    ``PING`` against the *job store's* client when it is Redis-backed (no
    new connection, no round-trip benchmark);
  - which optional integrations are actually configured
    (Redis / Sentry / GitHub MCP / Consensus / Tavily) as a status object,
    so an operator can see at a glance what this deployment offers.

Only an *unrecoverable* gap (missing required config) makes the endpoint
503; degraded-but-servable states (Redis down → in-memory fallbacks,
optional integrations missing) stay 200 with the degradation stated
explicitly in ``checks``.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


def _env_present(name: str) -> bool:
    return bool((os.getenv(name) or "").strip())


def build_readiness_report(jobs_store: Any = None) -> tuple[dict[str, Any], bool]:
    """Compute the readiness payload and whether this instance is servable.

    ``jobs_store`` is the process's job store (injectable for tests);
    ``None`` resolves to the concrete store from runtime.
    """
    from app.config import get_redis_settings

    required = ("API_KEY", "BASE_URL", "MODEL_NAME", "VANTAGE_API_KEY")
    missing_required = [name for name in required if not _env_present(name)]

    integrations = {
        "redis": _env_present("REDIS_URL"),
        "sentry": _env_present("SENTRY_DSN"),
        "github_mcp": _env_present("GITHUB_MCP_TOKEN"),
        "consensus": _env_present("CONSENSUS_MODEL"),
        "tavily": _env_present("TAVILY_API_KEY"),
    }

    checks: dict[str, Any] = {
        "required_env": {
            name: _env_present(name) for name in (*required, "CORS_ALLOWED_ORIGIN")
        },
    }

    redis_ok: bool | None = None
    if get_redis_settings().redis_url is not None:
        try:
            store = jobs_store
            if store is None:
                from app.api.runtime import jobs as runtime_jobs

                store = runtime_jobs
            client = getattr(store, "_redis", None)
            if client is None:
                # REDIS_URL is set but this process fell back to the
                # in-memory store (Redis was unreachable at startup).
                redis_ok = False
            else:
                client.ping()
                redis_ok = True
        except Exception as exc:
            redis_ok = False
            logger.warning("Readiness: Redis ping failed (%s)", exc)
        checks["redis"] = "reachable" if redis_ok else "unreachable"
    else:
        checks["redis"] = "not configured (in-memory job store)"

    report: dict[str, Any] = {
        "status": "ready" if not missing_required else "not_ready",
        "ready": not missing_required,
        "checks": checks,
        "integrations": integrations,
    }
    if missing_required:
        report["missing_required_env"] = missing_required
    return report, not missing_required
