"""
Rate-limit retry strategy and context management for LLM calls.

Rate-limit retry strategy
--------------------------
We set ``max_retries=0`` on ChatOpenAI to disable the OpenAI SDK's own
internal retry loop entirely. That loop uses tenacity/httpx-retry with
exponential backoff *inside* the SDK, meaning it never surfaces a
``RateLimitError`` to our code — it just sleeps, potentially for
minutes, pinning the worker thread indefinitely under sustained 429s.

Instead, ``_call_with_failover`` owns all retry logic with explicit
hard bounds:

  - Up to MAX_RATE_LIMIT_ATTEMPTS total attempts across all configured
    keys (primary, secondary, tertiary), cycled in order so every key
    gets a chance on each round.
  - Exponential backoff between attempts: BACKOFF_BASE_S * 2^attempt,
    capped at BACKOFF_MAX_S. This is wall-clock sleep that the caller
    can reason about.
  - After all attempts are exhausted, raises RateLimitExhaustedError
    with a user-facing message suitable for surfacing in the API response.
"""

from __future__ import annotations

import time
from contextvars import ContextVar
from typing import TYPE_CHECKING, Callable, TypeVar

from openai import RateLimitError
from pydantic import BaseModel

from app.config import get_llm_settings

if TYPE_CHECKING:
    from langchain_openai import ChatOpenAI

T = TypeVar("T", bound=BaseModel)

# ---------------------------------------------------------------------------
# Rate-limit retry constants — all in one place for easy tuning.
# ---------------------------------------------------------------------------

# Total attempts across ALL configured keys combined.  With 3 keys and
# 6 attempts each key gets exactly 2 tries.  With 2 keys it's 3 tries
# each.  With 1 key, it gets all 6 tries.  The ratio is the same as
# the original 2-key/4-attempt design: 2 rounds across however many
# keys exist.
MAX_RATE_LIMIT_ATTEMPTS: int = 6

# Initial sleep before the second attempt (doubles each round, capped below).
BACKOFF_BASE_S: float = 2.0

# Hard ceiling on any single inter-attempt sleep to avoid very long waits.
BACKOFF_MAX_S: float = 16.0

# ---------------------------------------------------------------------------
# Thread-local retry context
# ---------------------------------------------------------------------------

# A ContextVar holding an optional callback (attempt, max_attempts) -> None.
# Set by api/main.py's _run_graph_with_streaming for the duration of a graph
# pass so that every invoke_structured call in that thread automatically
# updates job.retry_info without needing changes to node function signatures.
# Defaults to None (no-op) — safe to call from CLI or tests without any setup.
_retry_context: ContextVar[Callable[[int, int], None] | None] = ContextVar(
    "_retry_context", default=None
)


class RateLimitExhaustedError(RuntimeError):
    """
    Raised when all rate-limit retry attempts across all configured keys
    are exhausted without a successful response.

    The message is intentionally user-facing and safe to surface directly
    in an API error response.
    """


def _call_with_failover(
    fn: Callable[[ChatOpenAI], T],
    *,
    retry_callback: Callable[[int, int], None] | None = None,
    model_override: str | None = None,
) -> T:
    """
    Call *fn* with bounded retry and multi-key failover on RateLimitError.

    Attempt schedule (MAX_RATE_LIMIT_ATTEMPTS=6, three keys configured):
      attempt 0 — primary    (no sleep before)
      attempt 1 — secondary  (sleep BACKOFF_BASE_S * 2^0 = 2s)
      attempt 2 — tertiary   (sleep BACKOFF_BASE_S * 2^1 = 4s)
      attempt 3 — primary    (sleep BACKOFF_BASE_S * 2^2 = 8s)
      attempt 4 — secondary  (sleep BACKOFF_BASE_S * 2^3 = 16s)
      attempt 5 — tertiary   (sleep BACKOFF_BASE_S * 2^4 = 16s, capped)
      → RateLimitExhaustedError

    With two keys: slot = attempt % 2 (primary / secondary, 3 tries each).
    With one key:  all 6 attempts use the primary key.

    Non-RateLimitError exceptions propagate immediately without retrying —
    errors are never swallowed.

    Parameters
    ----------
    fn:
        Callable that receives a ChatOpenAI model and returns a result.
    retry_callback:
        Optional explicit callback invoked at the start of each retry
        attempt (attempt > 0) with (current_attempt, max_attempts).
        If None, falls back to the thread-local _retry_context value so
        callers don't need to thread the callback manually — it's set
        once per graph pass by api/main.py.
    model_override:
        When set, every attempt is built against this model slug instead
        of the configured primary.  Used only by opt-in consensus mode.
    """
    from app.llm.client import get_chat_model

    settings = get_llm_settings()
    has_secondary = bool(settings.api_key_secondary)
    has_tertiary = bool(settings.api_key_tertiary)

    # Determine how many distinct key slots we cycle through.
    # slot 0 = primary, slot 1 = secondary, slot 2 = tertiary.
    num_slots = 1 + int(has_secondary) + int(has_tertiary)
    last_exc: RateLimitError | None = None

    # Resolve callback: explicit arg wins; fall back to context var.
    cb = retry_callback if retry_callback is not None else _retry_context.get()

    for attempt in range(MAX_RATE_LIMIT_ATTEMPTS):
        slot = attempt % num_slots  # 0=primary, 1=secondary, 2=tertiary
        use_secondary = slot == 1
        use_tertiary = slot == 2

        if attempt > 0:
            sleep_s = min(BACKOFF_BASE_S * (2 ** (attempt - 1)), BACKOFF_MAX_S)
            if use_tertiary:
                key_label = "tertiary"
            elif use_secondary:
                key_label = "secondary"
            else:
                key_label = "primary"
            print(
                f"[rate-limit] attempt {attempt + 1}/{MAX_RATE_LIMIT_ATTEMPTS} "
                f"(key={key_label}, backoff={sleep_s:.0f}s) …"
            )
            if cb is not None:
                cb(attempt + 1, MAX_RATE_LIMIT_ATTEMPTS)
            time.sleep(sleep_s)
        try:
            return fn(
                get_chat_model(
                    use_secondary=use_secondary,
                    use_tertiary=use_tertiary,
                    model_override=model_override,
                )
            )
        except RateLimitError as exc:
            last_exc = exc
            continue  # try next attempt

    raise RateLimitExhaustedError(
        "Rate limited after multiple attempts — please try again in a few minutes."
    ) from last_exc
