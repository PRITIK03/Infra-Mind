"""
Central logging configuration: JSON-structured records via stdlib logging.

This project prefers minimal/native solutions over new libraries, so this
uses a custom ``logging.Formatter`` — not structlog or similar.  Every log
line carries at minimum ``timestamp`` (UTC ISO-8601), ``level``, ``logger``,
and ``message``; anything logged from inside job processing additionally
carries ``job_id``, injected by :class:`JobIdFilter` from a ContextVar
(rather than manual string formatting at every call site).

Output format is JSON by default; set ``LOG_FORMAT=text`` for human-readable
local development.  ``configure_logging()`` is idempotent and is called once
from ``app/api/main.py`` at import time, so both the uvicorn server and the
test process get the same records (uvicorn's access logs keep their own
format — this covers application records).
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import sys
from contextvars import ContextVar
from datetime import datetime, timezone

DEFAULT_LOG_FORMAT = "json"

# Current job being processed by *this* thread/task.  Set inside the worker
# thread (job_runner) and the SSE stream generator (sse), so any logger call
# anywhere in the call stack below gets job_id for free.
_job_id_ctx: ContextVar[str | None] = ContextVar("inframind_job_id", default=None)


class JobIdFilter(logging.Filter):
    """Attach the ambient ``job_id`` to a record, defaulting to ``-``.

    stdlib Filters mutate the record in place, which is exactly the
    injection point — call sites keep writing plain messages.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.job_id = _job_id_ctx.get() or "-"
        return True


@contextlib.contextmanager
def bind_job_id(job_id: str):
    """Run the wrapped block with ``job_id`` attached to every log record.

    Safe to nest; restores the previous value on exit (including via
    exceptions).  When an async generator is torn down by task cancellation
    the runtime may unwind this ``with`` from a copied Context whose reset
    would fail — in that case the whole context is being discarded anyway,
    so there is nothing to restore.
    """
    token = _job_id_ctx.set(job_id)
    try:
        yield
    finally:
        try:
            _job_id_ctx.reset(token)
        except ValueError:
            pass


class JsonFormatter(logging.Formatter):
    """One JSON object per line: timestamp/level/logger/message (+job_id).

    Exc_info is rendered into an ``exception`` field with the standard
    traceback formatting, so ``logger.exception(...)`` keeps its detail.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        job_id = getattr(record, "job_id", None)
        if job_id and job_id != "-":
            payload["job_id"] = job_id
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class TextFormatter(logging.Formatter):
    """Human-readable one-liner for local development (LOG_FORMAT=text)."""

    def __init__(self) -> None:
        super().__init__(
            "%(asctime)s %(levelname)-7s %(name)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S%z",
        )

    def format(self, record: logging.LogRecord) -> str:
        line = super().format(record)
        job_id = getattr(record, "job_id", None)
        if job_id and job_id != "-":
            line = f"{line} [job_id={job_id}]"
        return line


def configure_logging(
    *,
    stream=None,
    force_format: str | None = None,
) -> str:
    """Install the root handler once; returns the format in effect.

    Idempotent: safe to call from multiple import paths.  Does not touch
    the root level (uvicorn/pytest own that); it only *adds* the structured
    handler.  Set ``LOG_FORMAT=text`` for the human-readable variant.
    """
    if getattr(logging.root, "_inframind_configured", False):
        return getattr(logging.root, "_inframind_format", DEFAULT_LOG_FORMAT)

    fmt = (force_format or os.getenv("LOG_FORMAT") or DEFAULT_LOG_FORMAT).lower()
    if fmt not in ("json", "text"):
        fmt = DEFAULT_LOG_FORMAT
    handler = logging.StreamHandler(stream if stream is not None else sys.stderr)
    handler.setFormatter(JsonFormatter() if fmt == "json" else TextFormatter())
    handler.addFilter(JobIdFilter())
    logging.root.addHandler(handler)
    logging.root._inframind_configured = True  # type: ignore[attr-defined]
    logging.root._inframind_format = fmt  # type: ignore[attr-defined]
    return fmt
