"""
Pluggable publish/subscribe backends for real-time job progress streaming.

This mirrors the in-memory/Redis split already used for the job store
(:mod:`app.api.job_store`), and follows exactly the same
graceful-optional pattern:

- ``InMemoryEventBus`` — asyncio-queue fan-out confined to a single
  process.  Zero dependencies, correct for single-instance deployments
  (the current reality) and for the whole test suite.
- ``RedisEventBus`` — Redis Pub/Sub, so an event published by the worker
  thread/process running the graph reaches SSE subscribers connected to
  *any* backend replica (correct multi-instance fan-out for whenever this
  is deployed with more than one replica).

Selection happens once at startup in :func:`build_event_bus`, driven by
the same ``REDIS_URL`` that selects the job store.  Without ``REDIS_URL``
the app behaves exactly as it did before this module existed (in-process
fan-out, single instance), and a configured-but-unreachable Redis logs a
warning and degrades to the in-process bus instead of failing — Redis is
an upgrade, never a hard requirement.

Publishing is synchronous by design
-----------------------------------
``publish`` is called from the very same places that already mutate job
state (``JobStoreBackend.update_stage`` / ``update_status`` /
``update_retry_info``), which run inside worker threads — not on the
event loop.  It therefore never awaits anything: the in-process bus hands
the payload to each subscriber's queue with
``loop.call_soon_threadsafe``, and the Redis bus issues one non-blocking
``PUBLISH``.  A publishing failure is logged and swallowed so progress
streaming can never break a job run.

What is published
-----------------
The payload is exactly the JSON document the polling endpoint returns
(see :func:`app.api.job_store.job_snapshot`): a *state snapshot*, not a
delta.  A client can therefore render a stream event and a poll response
with the same code, and a duplicated or dropped event is harmless — the
next snapshot carries the full truth.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import threading
from typing import Any, Protocol

logger = logging.getLogger(__name__)


# Terminal job statuses: after publishing one of these the SSE route sends
# the event and closes the stream server-side rather than waiting for
# updates that will never come.
TERMINAL_STATUSES: frozenset[str] = frozenset({"done", "error"})

EventPayload = dict[str, Any]

# Bound on buffered events per subscriber.  A stalled/slow consumer must
# not be able to grow backend memory without limit; when the buffer is
# full the *oldest* snapshot is dropped because only the newest state is
# useful for a progress feed.
_MAX_QUEUED_EVENTS = 256

# Upper bound on how long stream teardown waits for a Redis subscriber thread
# to notice the closed PubSub before giving up on the join.  The thread is a
# daemon, so an over-running socket can never block process exit.
_REDIS_CLOSE_JOIN_TIMEOUT_S = 1.0


class EventSubscription(Protocol):
    """A single subscriber's view of one job's event stream.

    Implementations are cheap value objects; the SSE route owns exactly
    one and is responsible for calling :meth:`close` (its ``finally``
    block does so on every exit path).
    """

    async def next_event(self, timeout: float | None = None) -> EventPayload | None:
        """Return the next event, or ``None`` if none arrived in *timeout*.

        ``None`` is the heartbeat signal — the caller uses it to emit an
        SSE comment and to check whether the client is still connected.
        A ``None`` timeout waits indefinitely.
        """
        ...

    def close(self) -> None:
        """Release this subscription (idempotent, never raises)."""
        ...

    @property
    def closed(self) -> bool:
        """True once this subscription can no longer deliver events."""
        ...


class JobEventBus(Protocol):
    """Interface shared by the in-process and Redis event buses.

    Consumed by ``app/api/job_store.py`` (to publish after every state
    transition) and by ``app/api/main.py``'s SSE route (to subscribe).
    Both implementations are interchangeable, so neither call site needs
    to know which backend is configured.
    """

    def publish(self, job_id: str, payload: EventPayload) -> None: ...

    async def subscribe(self, job_id: str) -> EventSubscription: ...

    def subscriber_count(self, job_id: str) -> int:
        """Subscriptions held *by this process* for *job_id*.

        Used by tests and metrics.  With the Redis bus this is deliberately
        process-local: subscribers attached to other replicas are not
        visible here, which is why this is an observability helper and
        never a correctness mechanism.
        """
        ...


# ---------------------------------------------------------------------------
# In-process implementation (default: REDIS_URL unset)
# ---------------------------------------------------------------------------


class _InMemorySubscription:
    """Subscriber queue bridged from publisher threads to one event loop."""

    def __init__(self, bus: "InMemoryEventBus", job_id: str, loop: asyncio.AbstractEventLoop):
        self._bus = bus
        self._job_id = job_id
        self._loop = loop
        self._queue: asyncio.Queue[EventPayload] = asyncio.Queue(
            maxsize=_MAX_QUEUED_EVENTS
        )
        self._closed = False

    # -- producer side (any thread) ------------------------------------------

    def _deliver(self, payload: EventPayload) -> None:
        """Runs on the event loop thread."""
        if self._closed:
            return
        if self._queue.full():
            # Slow consumer: keep the newest snapshots, drop the oldest.
            with contextlib.suppress(asyncio.QueueEmpty):
                self._queue.get_nowait()
        self._queue.put_nowait(payload)

    def offer(self, payload: EventPayload) -> None:
        """Thread-safe hand-off from a publisher thread."""
        if self._closed:
            return
        try:
            self._loop.call_soon_threadsafe(self._deliver, payload)
        except RuntimeError:
            # Event loop already closed (interpreter shutdown / test teardown).
            self._closed = True

    # -- consumer side (event loop thread) -----------------------------------

    async def next_event(self, timeout: float | None = None) -> EventPayload | None:
        if self._closed and self._queue.empty():
            return None
        try:
            if timeout is None:
                return await self._queue.get()
            # wait_for cancels the pending get() on timeout.  Cancelling a
            # Queue.get() is safe (asyncio re-wakes the next waiter, and an
            # item that just landed is returned by the following call),
            # unlike cancelling an async generator's __anext__.
            return await asyncio.wait_for(self._queue.get(), timeout)
        except (asyncio.TimeoutError, TimeoutError):
            return None

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._bus._remove(self._job_id, self)

    @property
    def closed(self) -> bool:
        return self._closed


class InMemoryEventBus:
    """Process-local fan-out built on ``loop.call_soon_threadsafe`` queues.

    Correct for a single backend instance (the current deployment shape)
    and for tests.  With multiple replicas a job's events only reach the
    subscribers attached to the instance that ran the graph — set
    ``REDIS_URL`` to get :class:`RedisEventBus` instead.
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, list[_InMemorySubscription]] = {}
        self._lock = threading.Lock()

    def publish(self, job_id: str, payload: EventPayload) -> None:
        with self._lock:
            subscribers = list(self._subscribers.get(job_id, ()))
        for subscription in subscribers:
            subscription.offer(payload)

    async def subscribe(self, job_id: str) -> EventSubscription:
        loop = asyncio.get_running_loop()
        subscription = _InMemorySubscription(self, job_id, loop)
        with self._lock:
            self._subscribers.setdefault(job_id, []).append(subscription)
        return subscription

    def _remove(self, job_id: str, subscription: _InMemorySubscription) -> None:
        with self._lock:
            current = self._subscribers.get(job_id)
            if not current:
                return
            with contextlib.suppress(ValueError):
                current.remove(subscription)
            if not current:
                self._subscribers.pop(job_id, None)

    def subscriber_count(self, job_id: str) -> int:
        with self._lock:
            return len(self._subscribers.get(job_id, ()))

    def clear(self) -> None:
        """Drop all subscriptions (test/teardown helper)."""
        with self._lock:
            self._subscribers.clear()


# ---------------------------------------------------------------------------
# Redis Pub/Sub implementation (REDIS_URL configured)
# ---------------------------------------------------------------------------


class _RedisSubscription:
    """Forwards Redis Pub/Sub messages into an asyncio queue.

    redis-py's PubSub client is blocking, so the blocking ``listen()`` loop
    lives on a short-lived daemon thread that hands each decoded payload to
    the consumer's event loop with ``call_soon_threadsafe``.  That keeps the
    event loop free (the same discipline as wrapping job-store reads in
    ``asyncio.to_thread``) while staying entirely on the synchronous redis
    client the job store already uses.
    """

    def __init__(self, bus: "RedisEventBus", job_id: str, loop: asyncio.AbstractEventLoop):
        self._bus = bus
        self._job_id = job_id
        self._loop = loop
        self._channel = f"{bus._key_prefix}{job_id}"
        self._queue: asyncio.Queue[EventPayload] = asyncio.Queue(
            maxsize=_MAX_QUEUED_EVENTS
        )
        self._stop = threading.Event()
        self._closed = False
        self._pubsub = bus._redis.pubsub()
        self._pubsub.subscribe(self._channel)
        self._thread = threading.Thread(
            target=self._run,
            name=f"sse-redis-sub-{job_id}",
            daemon=True,
        )

    @property
    def channel(self) -> str:
        return self._channel

    def start(self) -> None:
        self._thread.start()

    def _run(self) -> None:
        try:
            for message in self._pubsub.listen():
                if self._stop.is_set():
                    break
                if message.get("type") != "message":
                    continue  # subscribe/unsubscribe confirmations
                payload = _decode_message(message.get("data"))
                if payload is None:
                    continue
                if self._closed:
                    break
                try:
                    self._loop.call_soon_threadsafe(self._deliver, payload)
                except RuntimeError:
                    # Consumer's event loop closed — nothing left to serve.
                    break
        except Exception as exc:  # pragma: no cover - transport dependent
            if not self._stop.is_set():
                logger.debug(
                    "Redis SSE subscription for %s ended: %s", self._job_id, exc
                )

    def _deliver(self, payload: EventPayload) -> None:
        if self._closed:
            return
        if self._queue.full():
            with contextlib.suppress(asyncio.QueueEmpty):
                self._queue.get_nowait()
        self._queue.put_nowait(payload)

    async def next_event(self, timeout: float | None = None) -> EventPayload | None:
        if self._closed and self._queue.empty():
            return None
        try:
            if timeout is None:
                return await self._queue.get()
            return await asyncio.wait_for(self._queue.get(), timeout)
        except (asyncio.TimeoutError, TimeoutError):
            return None

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._stop.set()
        # Closing the PubSub unblocks listen() so the thread exits promptly.
        # The join is bounded: one wedged socket must not hang teardown.
        with contextlib.suppress(Exception):
            self._pubsub.close()
        if self._thread.is_alive() and self._thread is not threading.current_thread():
            self._thread.join(timeout=_REDIS_CLOSE_JOIN_TIMEOUT_S)
        self._bus._remove(self._job_id, self)

    @property
    def closed(self) -> bool:
        return self._closed


def _decode_message(data: Any) -> EventPayload | None:
    """Decode one Pub/Sub payload, tolerating junk on the channel."""
    if isinstance(data, (bytes, bytearray)):
        try:
            data = data.decode("utf-8")
        except UnicodeDecodeError:
            logger.warning("Ignoring non-UTF8 SSE pub/sub message")
            return None
    if not isinstance(data, str):
        return None
    try:
        payload = json.loads(data)
    except ValueError:
        logger.warning("Ignoring non-JSON SSE pub/sub message")
        return None
    return payload if isinstance(payload, dict) else None


class RedisEventBus:
    """Redis Pub/Sub event bus: one channel per job.

    Publishing from the instance running the job reaches subscribers on
    every replica, which is what makes the SSE endpoint correct once the
    backend is scaled horizontally (the in-memory bus cannot do that).
    Redis Pub/Sub is fire-and-forget by nature: a subscriber that attaches
    mid-run gets the current state from the store as its first event, so
    nothing published before it subscribed is required.
    """

    def __init__(
        self,
        redis_client: Any,
        *,
        key_prefix: str = "inframind:events:",
    ) -> None:
        self._redis = redis_client
        self._key_prefix = key_prefix
        self._subscriptions: dict[str, list[_RedisSubscription]] = {}
        self._lock = threading.Lock()

    @classmethod
    def from_url(
        cls,
        redis_url: str,
        *,
        key_prefix: str = "inframind:events:",
    ) -> "RedisEventBus":
        """Build a bus from a Redis URL using a shared connection pool."""
        import redis

        pool = redis.ConnectionPool.from_url(redis_url)
        return cls(redis.Redis(connection_pool=pool), key_prefix=key_prefix)

    def publish(self, job_id: str, payload: EventPayload) -> None:
        # Fire-and-forget: unlike job records this is not durable state, so
        # there is nothing to read back from PUBLISH's subscriber count.
        self._redis.publish(f"{self._key_prefix}{job_id}", json.dumps(payload))

    async def subscribe(self, job_id: str) -> EventSubscription:
        loop = asyncio.get_running_loop()

        # SUBSCRIBE is a real round-trip; keep it off the event loop.
        subscription = await asyncio.to_thread(_RedisSubscription, self, job_id, loop)
        with self._lock:
            self._subscriptions.setdefault(job_id, []).append(subscription)
        subscription.start()
        return subscription

    def _remove(self, job_id: str, subscription: _RedisSubscription) -> None:
        with self._lock:
            current = self._subscriptions.get(job_id)
            if not current:
                return
            with contextlib.suppress(ValueError):
                current.remove(subscription)
            if not current:
                self._subscriptions.pop(job_id, None)

    def subscriber_count(self, job_id: str) -> int:
        with self._lock:
            return len(self._subscriptions.get(job_id, ()))

    def clear(self) -> None:
        """Close and drop all subscriptions (test/teardown helper)."""
        with self._lock:
            subscriptions = [
                sub for subs in self._subscriptions.values() for sub in subs
            ]
            self._subscriptions.clear()
        for subscription in subscriptions:
            subscription.close()


# ---------------------------------------------------------------------------
# Backend selection — same graceful-optional pattern as build_job_store()
# ---------------------------------------------------------------------------


def build_event_bus() -> JobEventBus:
    """Select the publish/subscribe backend from configuration.

    Uses Redis Pub/Sub when ``REDIS_URL`` is configured (so events fan out
    across backend replicas), otherwise an in-process asyncio bus — which is
    all a single-instance deployment needs.  If the Redis package is missing
    or the initial connection fails, the app logs a warning and falls back to
    the in-process bus: real-time progress is an enhancement, never a hard
    requirement, and the polling endpoint keeps working either way.
    """
    from app.config import get_redis_settings

    settings = get_redis_settings()
    if settings.redis_url is None:
        logger.info("Event bus: in-process asyncio fan-out (REDIS_URL unset)")
        return InMemoryEventBus()

    try:
        bus = RedisEventBus.from_url(settings.redis_url)
        # Fail fast at startup rather than on the first event.
        bus._redis.ping()
        logger.info("Event bus: Redis Pub/Sub (REDIS_URL configured)")
        return bus
    except Exception as exc:  # pragma: no cover - depends on local env
        logger.warning(
            "REDIS_URL is configured but Redis is unavailable for the event "
            "bus (%s); falling back to in-process progress fan-out.",
            exc,
        )
        return InMemoryEventBus()
