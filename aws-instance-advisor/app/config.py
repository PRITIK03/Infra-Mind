"""
Centralized environment configuration for the AWS Instance Advisor agent.

Loads all required environment variables once via python-dotenv. Settings
are split into separate groups (LLM vs. live-data) so a module that only
needs one group isn't blocked by unrelated missing variables.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


class ConfigError(RuntimeError):
    """Raised when a required environment variable is missing."""


def _require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ConfigError(f"Missing required environment variable: {name}")
    return value


def _optional_int(name: str, default: int) -> int:
    """Read an integer env var, returning *default* if unset or non-numeric."""
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class LLMSettings:
    """Config for the OpenAI-compatible LLM endpoint."""

    api_key: str
    base_url: str
    model_name: str
    max_tokens: int = 8192
    # Caps the model's internal reasoning/"thinking" budget as a subset of
    # max_tokens (not in addition to it). Keep meaningfully smaller than
    # max_tokens so visible JSON output still has room.
    reasoning_max_tokens: int = 2048
    api_key_secondary: str | None = None
    # Optional server-side model fallback list for OpenRouter.  When set,
    # OpenRouter will automatically reroute to the next model in the list if
    # the primary is rate-limited or unavailable — distinct from the
    # dual-key failover which handles per-account 429s.  Read as a
    # comma-separated string from LLM_FALLBACK_MODELS; defaults to empty.
    fallback_models: tuple[str, ...] = ()
    # Optional second model used ONLY by opt-in consensus mode
    # (api request ``{"consensus": true}``).  The consensus node re-runs the
    # final holistic_recommend step against this model using the exact same
    # technical_needs/candidates, then compares the two recommendations
    # deterministically.  Read from CONSENSUS_MODEL.
    #
    # Deliberately None by default: consensus costs one extra full LLM call,
    # so it must never happen unless a caller explicitly asks for it AND a
    # distinct model is configured.  See effective_consensus_model().
    consensus_model: str | None = None

    def effective_consensus_model(self) -> str | None:
        """Resolve the model to use for consensus mode, or None to decline.

        Resolution order:
          1. ``CONSENSUS_MODEL`` when explicitly set.
          2. ``LLM_FALLBACK_MODELS[0]`` — already configured as a failover
             model, so it is a reasonable, zero-extra-config second opinion.
          3. None → consensus mode declines gracefully with a clear message
             rather than crashing or silently ignoring the request.
        """
        if self.consensus_model:
            return self.consensus_model
        if self.fallback_models:
            return self.fallback_models[0]
        return None


@dataclass(frozen=True)
class VantageSettings:
    """Config for the live EC2 instance-data source."""

    api_key: str


@dataclass(frozen=True)
class TavilySettings:
    """Config for Tavily-powered web search."""

    api_key: str


def get_llm_settings() -> LLMSettings:
    """Loads and validates LLM-related settings only."""
    raw_fallback = os.getenv("LLM_FALLBACK_MODELS", "")
    fallback_models: tuple[str, ...] = tuple(
        m.strip() for m in raw_fallback.split(",") if m.strip()
    )
    return LLMSettings(
        api_key=_require("API_KEY"),
        base_url=_require("BASE_URL"),
        model_name=_require("MODEL_NAME"),
        max_tokens=_optional_int("LLM_MAX_TOKENS", 8192),
        reasoning_max_tokens=_optional_int("LLM_REASONING_MAX_TOKENS", 2048),
        api_key_secondary=os.getenv("API_KEY_2") or None,
        fallback_models=fallback_models,
        consensus_model=(os.getenv("CONSENSUS_MODEL") or "").strip() or None,
    )


def get_vantage_settings() -> VantageSettings:
    """Loads and validates Vantage-related settings only."""
    return VantageSettings(
        api_key=_require("VANTAGE_API_KEY"),
    )


def get_tavily_settings() -> TavilySettings:
    """Loads and validates Tavily-related settings only."""
    return TavilySettings(
        api_key=_require("TAVILY_API_KEY"),
    )


@dataclass(frozen=True)
class GitHubMCPSettings:
    """
    Config for the GitHub MCP server used by optional repository analysis.

    token is None when GITHUB_MCP_TOKEN is unset.  Repository analysis is an
    enhancement, not a requirement — callers skip gracefully, exactly like
    the Tavily pattern above.
    """

    token: str | None = None
    base_url: str = "https://api.githubcopilot.com/mcp/"


def get_github_mcp_settings() -> GitHubMCPSettings:
    """Load GitHub MCP settings without failing when they're absent.

    When GITHUB_MCP_TOKEN is unset this returns an unconfigured instance so
    the pipeline runs without repository context rather than erroring —
    matching the Tavily/observability graceful-skip pattern.
    """
    token = (os.getenv("GITHUB_MCP_TOKEN") or "").strip() or None
    if token is None:
        logger.debug(
            "GITHUB_MCP_TOKEN is unset; repository analysis disabled. "
            "Runs will proceed without repo context."
        )
    base_url = (
        (os.getenv("GITHUB_MCP_BASE_URL") or "").strip()
        or "https://api.githubcopilot.com/mcp/"
    )
    return GitHubMCPSettings(token=token, base_url=base_url)


@dataclass(frozen=True)
class ObservabilitySettings:
    """
    Optional observability config.

    database_url: SQLAlchemy-compatible URL for run-history persistence
    (e.g. ``postgresql+psycopg2://user:pass@host/db`` for Neon/Supabase,
    or ``sqlite:///./runs.db`` for local development).
    When None, run summaries are logged to stdout only — no DB required.
    """

    database_url: str | None = None


def get_observability_settings() -> ObservabilitySettings:
    """Load observability settings.  Gracefully returns an unconfigured
    instance when DATABASE_URL is absent — matching the Tavily skip pattern."""
    raw = (os.getenv("DATABASE_URL") or "").strip() or None
    if raw is None:
        logger.debug(
            "DATABASE_URL is unset; observability DB persistence disabled. "
            "Run summaries will be logged to stdout only."
        )
    return ObservabilitySettings(database_url=raw)


@dataclass(frozen=True)
class RedisSettings:
    """
    Optional Redis config for the persistent job store.

    redis_url: Redis connection URL (e.g. ``redis://localhost:6379/0`` or a
    managed ``rediss://`` URL from Upstash/Render/Railway).  When None, the
    API falls back to the process-local in-memory job store — exactly the
    same graceful-skip pattern used for Tavily, GitHub MCP, and
    DATABASE_URL.  Redis is an upgrade (job survival across restarts,
    shared state across multiple backend instances), never a hard
    requirement.
    """

    redis_url: str | None = None


def get_redis_settings() -> RedisSettings:
    """Load Redis settings without failing when they're absent.

    When REDIS_URL is unset this returns an unconfigured instance so the
    app continues with the in-memory JobStore rather than erroring —
    matching the Tavily/GitHub-MCP/DATABASE_URL graceful-skip pattern.
    """
    raw = (os.getenv("REDIS_URL") or "").strip() or None
    if raw is None:
        logger.debug(
            "REDIS_URL is unset; using the in-memory job store. "
            "Jobs will not survive restarts or be shared across instances."
        )
    return RedisSettings(redis_url=raw)


@dataclass(frozen=True)
class SentrySettings:
    """
    Optional error-monitoring config.

    sentry_dsn: Sentry Data Source Name for error reporting (e.g.
    ``https://<key>@o0.ingest.sentry.io/0``).  When None, Sentry is never
    initialized and the app behaves exactly as it did before — the same
    graceful-optional pattern used for Tavily, GitHub MCP, DATABASE_URL,
    and REDIS_URL.  Error monitoring is an upgrade, never a requirement.

    traces_sample_rate: fraction of requests traced for performance
    monitoring.  Deliberately 0.0 by default — this project only needs
    error monitoring, and tracing on a free tier burns quota fast.
    """

    sentry_dsn: str | None = None
    traces_sample_rate: float = 0.0


def get_sentry_settings() -> SentrySettings:
    """Load Sentry settings without failing when they're absent.

    When SENTRY_DSN is unset this returns an unconfigured instance so the
    caller skips Sentry initialization entirely rather than erroring —
    matching the Tavily/GitHub-MCP/DATABASE_URL/REDIS_URL graceful-skip
    pattern.
    """
    raw = (os.getenv("SENTRY_DSN") or "").strip() or None
    if raw is None:
        logger.debug(
            "SENTRY_DSN is unset; error monitoring disabled. "
            "Unhandled API errors will only appear in server logs."
        )
    return SentrySettings(
        sentry_dsn=raw,
        traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.0") or 0.0),
    )


@dataclass(frozen=True)
class APISettings:
    """Config for the FastAPI HTTP layer exposing the agent."""

    cors_allowed_origin: str
    port: int = 8000


def get_api_settings() -> APISettings:
    """Load API settings without silently widening production CORS."""
    origin = (os.getenv("CORS_ALLOWED_ORIGIN") or "").strip()
    if not origin:
        logger.warning(
            "CORS_ALLOWED_ORIGIN is unset; cross-origin browser requests are disabled. "
            "Set it explicitly for each environment."
        )
    return APISettings(
        cors_allowed_origin=origin,
        port=_optional_int("PORT", 8000),
    )
