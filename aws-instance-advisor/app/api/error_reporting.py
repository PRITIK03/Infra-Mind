"""
Optional error monitoring (Sentry) — never required, never blocking.

Extracted from ``app/api/main.py`` so the API module stays focused on app
construction and routes.  ``main.py`` re-exports these names unchanged, so
imports elsewhere (and the test suite) keep working.

Initialization must happen BEFORE the FastAPI app is constructed: Sentry's
FastAPI/Starlette integration patches the framework at init time, so
initializing after ``FastAPI(...)`` exists can miss the instrumentation.
When SENTRY_DSN is unset (or sentry-sdk isn't installed) every function here
is a no-op and the app runs exactly as it did before.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_sentry_enabled: bool = False


def init_sentry(dsn: str | None = None, *, traces_sample_rate: float | None = None) -> bool:
    """Initialize Sentry error monitoring if a DSN is configured.

    Returns True when Sentry was initialized, False when it was skipped.
    Skipping is the normal case (no SENTRY_DSN configured) and is never an
    error — matching the Tavily / GitHub-MCP / DATABASE_URL / REDIS_URL
    graceful-optional pattern.

    The import is deferred so a deployment without sentry-sdk installed
    still starts up cleanly.
    """
    global _sentry_enabled

    from app.config import get_sentry_settings

    settings = get_sentry_settings()
    if dsn is None:
        dsn = settings.sentry_dsn
    if not dsn:
        # No DSN configured — leave Sentry disabled.
        _sentry_enabled = False
        return False

    if traces_sample_rate is None:
        traces_sample_rate = settings.traces_sample_rate

    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration

        sentry_sdk.init(
            dsn=dsn,
            integrations=[FastApiIntegration()],
            # Error monitoring only by default; tracing is opt-in via
            # SENTRY_TRACES_SAMPLE_RATE to avoid burning free-tier quota.
            traces_sample_rate=traces_sample_rate,
            send_default_pii=False,
        )
        _sentry_enabled = True
        logger.info("Error monitoring: Sentry initialized")
        return True
    except Exception as exc:  # pragma: no cover - depends on local env
        _sentry_enabled = False
        logger.warning(
            "SENTRY_DSN is configured but Sentry could not be initialized (%s); "
            "continuing without error monitoring.",
            exc,
        )
        return False


def capture_exception(exc: BaseException) -> None:
    """Report an already-handled exception to Sentry, if it's enabled.

    Used for errors the API catches deliberately (graph failures, job
    timeouts) — those never propagate to FastAPI, so the automatic
    integration cannot see them. No-ops when Sentry is unconfigured.
    """
    if not _sentry_enabled:
        return
    try:
        import sentry_sdk

        sentry_sdk.capture_exception(exc)
    except Exception:  # pragma: no cover - observability must never crash
        pass


def capture_message(message: str) -> None:
    """Report a non-exception job failure (e.g. wall-clock timeout) to Sentry.

    No-ops when Sentry is unconfigured, same as capture_exception.
    """
    if not _sentry_enabled:
        return
    try:
        import sentry_sdk

        sentry_sdk.capture_message(message, level="error")
    except Exception:  # pragma: no cover - observability must never crash
        pass
