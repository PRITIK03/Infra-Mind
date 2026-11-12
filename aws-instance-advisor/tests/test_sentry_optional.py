"""
Test that Sentry error monitoring is fully optional.

This covers the only behavior worth asserting: when SENTRY_DSN is unset,
initialization is skipped cleanly and the app is unaffected. We deliberately
do NOT test that Sentry receives an event — that would require mocking the
SDK's transport internals and isn't meaningful coverage.

No network calls anywhere: skipping init means nothing is ever sent.
"""

from __future__ import annotations

import os

os.environ.setdefault("CORS_ALLOWED_ORIGIN", "http://localhost:3000")
os.environ.setdefault("PORT", "8000")


def test_init_sentry_skipped_cleanly_when_dsn_unset(monkeypatch):
    """With SENTRY_DSN unset, init_sentry() reports 'not initialized' and
    the capture helpers remain no-ops (they must never raise)."""
    from app.api.main import _capture_exception, _capture_message, init_sentry
    from app.config import get_sentry_settings

    monkeypatch.delenv("SENTRY_DSN", raising=False)

    # Settings surface the unconfigured state rather than raising.
    settings = get_sentry_settings()
    assert settings.sentry_dsn is None

    # Initialization is skipped, not attempted-and-failed.
    assert init_sentry() is False

    # The capture helpers must be safe no-ops when Sentry is disabled.
    _capture_exception(RuntimeError("boom"))
    _capture_message("job timed out")
