"""
Tests for real-time SSE progress streaming.

Covers:
  * GET /api/recommend/{job_id}/stream — current state on connect, one event
    per state transition, server-side close on done/error, 404 for unknown
    jobs, and termination when the job-timeout watchdog fires.
  * Client-disconnect handling: the stream stops and releases its slot (the
    documented SSE pitfall of generating for a browser that has gone away).
  * The concurrent-open-streams-per-IP cap (and that the requests-per-minute
    limiter is deliberately NOT applied to this endpoint).
  * Backward compatibility: GET /api/recommend/{job_id} polling keeps
    working unchanged and returns the identical document each event carries.
  * GET /api/share/{job_id} — 404 unless the job is done.
  * The event bus backends (in-process + Redis via fakeredis) and the store
    publish hooks at the existing update points.

No LLM calls, no live AWS/Vantage calls, no real Redis server.  Streaming is
driven over raw ASGI because httpx's ASGITransport buffers a whole response
body, which never completes for a stream that is intentionally held open.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import threading
import time
from typing import Any
from unittest.mock import patch

import fakeredis
import httpx
import pytest

os.environ.setdefault("CORS_ALLOWED_ORIGIN", "http://localhost:3000")
os.environ.setdefault("PORT", "8000")

from app.api import main as main_module
from app.api.event_bus import (
    InMemoryEventBus,
    RedisEventBus,
    _decode_message,
    build_event_bus,
)
from app.api.job_store import (
    InMemoryJobStore,
    Job,
    RedisJobStore,
    job_snapshot_from_job,
)
from app.api.main import (
    RATE_LIMIT_MAX_REQUESTS,
    app,
    event_bus,
    jobs,
    recommend_rate_limiter,
    stream_limiter,
)
from app.models.schemas import UserRequirements

_IP = "198.51.100.7"

_TRANSPORT = httpx.ASGITransport(app=app)


def _make_state() -> dict[str, Any]:
    return {
        "requirements": UserRequirements(),
        "latest_user_message": "test message",
        "next_question": None,
        "pending_field": None,
        "repo_analysis": None,
        "repo_analysis_note": None,
        "technical_needs": None,
        "instance_candidates": None,
        "database_candidates": None,
        "cache_candidates": None,
        "recommendation": None,
        "system_design_recommendation": None,
        "terraform_files": None,
    }


def _new_job(
    job_id: str,
    *,
    status: str = "collecting",
    stage: str = "Initializing",
    result: dict[str, Any] | None = None,
    error: str | None = None,
    next_question: str | None = None,
) -> Job:
    return Job(
        job_id=job_id,
        status=status,  # type: ignore[arg-type]
        current_stage=stage,
        state=_make_state(),
        result=result,
        error=error,
        next_question=next_question,
    )


def _put_job(
    job_id: str,
    *,
    status: str = "collecting",
    stage: str = "Initializing",
    result: dict[str, Any] | None = None,
    error: str | None = None,
    next_question: str | None = None,
) -> Job:
    job = _new_job(
        job_id,
        status=status,
        stage=stage,
        result=result,
        error=error,
        next_question=next_question,
    )
    jobs.put(job)
    return job


async def _aget(path: str, *, client_ip: str | None = None) -> httpx.Response:
    """One in-process HTTP request through the real app (polling paths)."""
    transport = (
        _TRANSPORT
        if client_ip is None
        else httpx.ASGITransport(app=app, client=(client_ip, 51900))
    )
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        return await client.get(path)


@pytest.fixture(autouse=True)
def _reset_api_state():
    """Keep limiter/bus state isolated between tests (in-process backends)."""
    assert isinstance(event_bus, InMemoryEventBus), (
        "these tests assume the in-process event bus; unset REDIS_URL"
    )
    recommend_rate_limiter.clear()
    stream_limiter.clear()
    event_bus.clear()
    yield
    recommend_rate_limiter.clear()
    stream_limiter.clear()
    event_bus.clear()


class _StreamDriver:
    """Drives the ASGI app directly so SSE frames can be read incrementally."""

    def __init__(
        self,
        path: str,
        *,
        client_ip: str = _IP,
        spec_version: str = "2.3",
    ) -> None:
        self.path = path
        self.client_ip = client_ip
        self.spec_version = spec_version
        self.status_code: int | None = None
        self.headers: dict[str, str] = {}
        self.body_parts: list[bytes] = []
        self._chunks: asyncio.Queue[bytes] = asyncio.Queue()
        self._buffer = ""
        self._incoming: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None
        self._incoming.put_nowait(
            {"type": "http.request", "body": b"", "more_body": False}
        )

    # -- ASGI plumbing -------------------------------------------------------

    async def _receive(self) -> dict[str, Any]:
        return await self._incoming.get()

    async def _send(self, message: dict[str, Any]) -> None:
        if message["type"] == "http.response.start":
            self.status_code = message["status"]
            self.headers = {
                key.decode("latin-1").lower(): value.decode("latin-1")
                for key, value in message.get("headers", [])
            }
            return
        body = message.get("body", b"")
        if body:
            self.body_parts.append(body)
            await self._chunks.put(body)

    def start(self) -> "_StreamDriver":
        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": self.spec_version},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": self.path,
            "raw_path": self.path.encode(),
            "query_string": b"",
            "root_path": "",
            "headers": [(b"host", b"testserver")],
            "client": (self.client_ip, 51900),
            "server": ("testserver", 80),
        }
        self._task = asyncio.create_task(app(scope, self._receive, self._send))
        return self

    async def __aenter__(self) -> "_StreamDriver":
        return self.start()

    async def __aexit__(self, *exc_info: Any) -> None:
        await self.close()

    # -- frame reading -------------------------------------------------------

    async def next_frame(self, timeout: float = 1.0) -> str:
        """Return the next complete SSE frame (comments included) as text."""
        try:
            while "\n\n" not in self._buffer:
                self._buffer += (
                    await asyncio.wait_for(self._chunks.get(), timeout)
                ).decode("utf-8")
        except (asyncio.TimeoutError, TimeoutError) as exc:
            raise TimeoutError(
                f"no SSE frame within {timeout}s (buffer={self._buffer!r})"
            ) from exc
        frame, self._buffer = self._buffer.split("\n\n", 1)
        return frame

    async def next_payload(self, timeout: float = 1.0) -> dict[str, Any]:
        """Next data frame's JSON payload, skipping comment/heartbeat frames."""
        while True:
            frame = await self.next_frame(timeout)
            if frame.startswith(":"):
                continue  # keep-alive comment
            assert frame.startswith("data: "), frame
            return json.loads(frame[len("data: ") :])

    # -- lifecycle -----------------------------------------------------------

    async def wait_app_done(self, timeout: float = 2.0) -> None:
        """Wait until the app stopped serving this request.

        Covers a normal server-side close *and* the cancellation-driven close
        an ASGI server performs when the client disappears, so this is the
        right signal for "the generator finished, one way or another" — a
        still-open stream times out and fails the test.
        """
        assert self._task is not None, "driver not started"
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.wait_for(self._task, timeout)

    async def disconnect(self) -> None:
        """Simulate the browser going away (tab closed / navigated off)."""
        await self._incoming.put({"type": "http.disconnect"})

    async def close(self) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    def json_body(self) -> Any:
        return json.loads(b"".join(self.body_parts).decode("utf-8"))


def _frame_payload(frame: str) -> dict[str, Any]:
    """Parse a data frame produced by the SSE generator."""
    assert frame.startswith("data: "), frame
    return json.loads(frame[len("data: ") :])


# ---------------------------------------------------------------------------
# Streaming: transitions, ordering, terminal close
# ---------------------------------------------------------------------------


def test_stream_pushes_each_state_transition_in_order_and_closes_on_done():
    async def _scenario():
        job_id = "sse-order-0001"
        _put_job(job_id, status="collecting", stage="Initializing")

        async with _StreamDriver(f"/api/recommend/{job_id}/stream") as driver:
            first = await driver.next_payload()
            assert first["status"] == "collecting"
            assert first["current_stage"] == "Initializing"
            assert driver.status_code == 200
            assert driver.headers["content-type"].startswith("text/event-stream")

            for stage in (
                "Collecting requirements",
                "Researching compute options",
                "Building final recommendation",
            ):
                jobs.update_stage(job_id, stage)
                event = await driver.next_payload()
                assert event["job_id"] == job_id
                assert event["current_stage"] == stage

            jobs.update_retry_info(
                job_id, "Retrying after rate limit (attempt 2 of 4)"
            )
            retry_event = await driver.next_payload()
            assert (
                retry_event["retry_info"]
                == "Retrying after rate limit (attempt 2 of 4)"
            )

            result = {"system_design_recommendation": {"compute": "t3.medium"}}
            jobs.update_status(job_id, "done", result=result)
            final = await driver.next_payload()
            assert final["status"] == "done"
            assert final["result"] == result

            # The terminal event closes the stream server-side.
            await driver.wait_app_done()
            assert stream_limiter.active_count(_IP) == 0
            assert event_bus.subscriber_count(job_id) == 0

    asyncio.run(_scenario())


def test_stream_on_finished_job_sends_final_state_immediately_then_closes():
    async def _scenario():
        job_id = "sse-done-0002"
        result = {"recommendation": {"recommended_instance": "m5.large"}}
        _put_job(job_id, status="done", stage="Complete", result=result)

        async with _StreamDriver(f"/api/recommend/{job_id}/stream") as driver:
            payload = await driver.next_payload()
            assert payload["status"] == "done"
            assert payload["result"] == result
            # Nothing more is coming, so the stream must not stay open.
            await driver.wait_app_done()
            assert stream_limiter.active_count(_IP) == 0
            assert event_bus.subscriber_count(job_id) == 0

    asyncio.run(_scenario())


def test_stream_on_errored_job_sends_error_and_closes():
    async def _scenario():
        job_id = "sse-error-0003"
        _put_job(
            job_id,
            status="error",
            stage="Researching compute options",
            error="RateLimitExhaustedError: rate limited",
        )

        async with _StreamDriver(f"/api/recommend/{job_id}/stream") as driver:
            payload = await driver.next_payload()
            assert payload["status"] == "error"
            assert "RateLimitExhaustedError" in payload["error"]
            await driver.wait_app_done()
            assert event_bus.subscriber_count(job_id) == 0

    asyncio.run(_scenario())


def test_stream_returns_404_for_unknown_job():
    async def _scenario():
        driver = _StreamDriver(
            "/api/recommend/00000000-0000-0000-0000-000000000000/stream"
        )
        async with driver:
            await driver.wait_app_done()
        assert driver.status_code == 404
        assert "not found" in driver.json_body()["detail"].lower()
        # A 404 must not consume a stream slot.
        assert stream_limiter.active_count(_IP) == 0

    asyncio.run(_scenario())


# ---------------------------------------------------------------------------
# Client disconnect
# ---------------------------------------------------------------------------


class _StubRequest:
    """Minimal Request stand-in for generator-level disconnect tests."""

    def __init__(self, *, disconnects_after: int = 0) -> None:
        self._disconnects_after = disconnects_after
        self.checks = 0

    async def is_disconnected(self) -> bool:
        self.checks += 1
        return self.checks > self._disconnects_after


def test_stream_stops_when_client_disconnects_and_releases_slot():
    async def _scenario():
        job_id = "sse-disc-0004"
        _put_job(job_id, status="running", stage="Reasoning about system design")

        async with _StreamDriver(f"/api/recommend/{job_id}/stream") as driver:
            first = await driver.next_payload()
            assert first["status"] == "running"
            assert stream_limiter.active_count(_IP) == 1
            assert event_bus.subscriber_count(job_id) == 1

            await driver.disconnect()
            await driver.wait_app_done(timeout=3.0)

        assert stream_limiter.active_count(_IP) == 0
        assert event_bus.subscriber_count(job_id) == 0

        # Nothing is left listening: further transitions go nowhere instead of
        # resurrecting a subscription for a browser that has gone away.
        jobs.update_stage(job_id, "Should not be delivered")
        assert event_bus.subscriber_count(job_id) == 0

    asyncio.run(_scenario())


def test_stream_generator_notices_disconnect_on_heartbeat(monkeypatch):
    """The idle heartbeat is the wake-up that detects a vanished client."""
    monkeypatch.setattr(main_module, "SSE_HEARTBEAT_SECONDS", 0.02)

    async def _scenario():
        job_id = "sse-hb-0005"
        _put_job(job_id, status="running", stage="Researching compute options")
        assert stream_limiter.acquire(_IP)
        subscription = await event_bus.subscribe(job_id)
        request = _StubRequest(disconnects_after=1)

        stream = main_module._sse_event_stream(request, job_id, subscription, _IP)
        snapshot = _frame_payload(await stream.__anext__())
        heartbeat = await stream.__anext__()
        with pytest.raises(StopAsyncIteration):
            await stream.__anext__()

        assert snapshot["status"] == "running"
        assert heartbeat == ": keep-alive\n\n"
        assert request.checks >= 2
        assert stream_limiter.active_count(_IP) == 0
        assert event_bus.subscriber_count(job_id) == 0

    asyncio.run(_scenario())


def test_stream_generator_releases_state_when_cancelled_mid_stream():
    """Cancellation (the ASGI server's other teardown path) also cleans up."""

    async def _scenario():
        job_id = "sse-cancel-0006"
        _put_job(job_id, status="running", stage="Researching cache options")
        assert stream_limiter.acquire(_IP)
        subscription = await event_bus.subscribe(job_id)

        stream = main_module._sse_event_stream(
            _StubRequest(disconnects_after=10_000), job_id, subscription, _IP
        )
        _frame_payload(await stream.__anext__())  # snapshot
        pending = asyncio.ensure_future(stream.__anext__())  # parked on heartbeat
        await asyncio.sleep(0.05)
        pending.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await pending

        assert stream_limiter.active_count(_IP) == 0
        assert event_bus.subscriber_count(job_id) == 0

    asyncio.run(_scenario())


# ---------------------------------------------------------------------------
# Concurrency limiting: open streams per IP, not requests per minute
# ---------------------------------------------------------------------------


def test_stream_cap_limits_concurrent_open_streams_per_ip():
    async def _scenario():
        job_id = "sse-cap-0007"
        _put_job(job_id, status="running", stage="Building final recommendation")
        cap = stream_limiter.max_streams
        path = f"/api/recommend/{job_id}/stream"

        held: list[_StreamDriver] = []
        try:
            for _ in range(cap):
                driver = _StreamDriver(path)
                driver.start()
                await driver.next_payload()  # live connection holding a slot
                held.append(driver)
            assert stream_limiter.active_count(_IP) == cap

            # One more from the same IP is refused...
            sixth = _StreamDriver(path)
            async with sixth:
                await sixth.wait_app_done()
            assert sixth.status_code == 429
            assert sixth.headers["retry-after"] == "5"
            assert "concurrent progress streams" in sixth.json_body()["detail"]

            # ...while another IP is unaffected (the cap is per client).
            other = _StreamDriver(path, client_ip="203.0.113.9")
            async with other:
                assert (await other.next_payload())["status"] == "running"
                assert other.status_code == 200

            # Closing a stream hands its slot back.
            await held.pop().close()
            assert stream_limiter.active_count(_IP) == cap - 1
            replacement = _StreamDriver(path)
            async with replacement:
                assert (await replacement.next_payload())["status"] == "running"
                assert replacement.status_code == 200
        finally:
            for driver in held:
                await driver.close()
        assert stream_limiter.active_count(_IP) == 0

    asyncio.run(_scenario())


def test_stream_works_after_requests_per_minute_quota_is_exhausted():
    """The requests-per-minute limiter deliberately does not gate streams."""

    async def _scenario():
        job_id = "sse-quota-0008"
        _put_job(job_id, status="collecting", stage="Initializing")

        for _ in range(RATE_LIMIT_MAX_REQUESTS):
            allowed, _ = recommend_rate_limiter.allow(_IP)
            assert allowed
        blocked, _ = recommend_rate_limiter.allow(_IP)
        assert not blocked, "precondition: per-IP request quota is exhausted"

        async with _StreamDriver(f"/api/recommend/{job_id}/stream") as driver:
            payload = await driver.next_payload()
            assert payload["status"] == "collecting"
            # An open stream is one stream, and is not gated by request quota.
            assert stream_limiter.active_count(_IP) == 1

        # A long-lived stream must not consume request-window slots either.
        still_blocked, _ = recommend_rate_limiter.allow(_IP)
        assert not still_blocked

    asyncio.run(_scenario())


def test_polling_endpoint_unchanged_while_stream_is_open():
    """Backward compatibility: polling still works and agrees with events."""

    async def _scenario():
        job_id = "sse-compat-0009"
        _put_job(job_id, status="running", stage="Analyzing repository")

        async with _StreamDriver(f"/api/recommend/{job_id}/stream") as driver:
            first = await driver.next_payload()
            assert first["current_stage"] == "Analyzing repository"

            jobs.update_stage(job_id, "Researching database options")
            event = await driver.next_payload()

            resp = await _aget(f"/api/recommend/{job_id}")
            assert resp.status_code == 200
            assert resp.json() == event  # polling + streaming share one projection

            jobs.update_status(
                job_id, "awaiting_input", next_question="How much traffic?"
            )
            awaiting = await driver.next_payload()
            assert awaiting["status"] == "awaiting_input"
            assert awaiting["next_question"] == "How much traffic?"
            assert (await _aget(f"/api/recommend/{job_id}")).json() == awaiting

    asyncio.run(_scenario())


# ---------------------------------------------------------------------------
# Job-timeout watchdog integration
# ---------------------------------------------------------------------------


def test_stream_receives_timeout_error_and_closes_when_watchdog_fires(monkeypatch):
    """The existing wall-clock watchdog ends the stream — it must not hang."""
    monkeypatch.setattr(main_module, "JOB_TIMEOUT_SECONDS", 0.2)
    job_id = "sse-watchdog-0010"

    def _hanging_run(jid: str, state: Any) -> None:
        time.sleep(1.5)  # outlives the patched timeout
        jobs.update_status(jid, "done")

    async def _scenario():
        _put_job(job_id, status="running", stage="Researching compute options")

        async with _StreamDriver(f"/api/recommend/{job_id}/stream") as driver:
            first = await driver.next_payload()
            assert first["status"] == "running"

            main_module._submit_with_timeout(_hanging_run, job_id, _make_state())

            final = await driver.next_payload(timeout=3.0)
            assert final["status"] == "error"
            assert "timed out" in final["error"].lower()

            # Stream closes; the watchdog's terminal event is the last frame.
            await driver.wait_app_done()
            assert event_bus.subscriber_count(job_id) == 0
            assert stream_limiter.active_count(_IP) == 0

    asyncio.run(_scenario())


# ---------------------------------------------------------------------------
# Share alias
# ---------------------------------------------------------------------------


def test_share_returns_the_same_result_as_polling_for_a_done_job():
    async def _scenario():
        job_id = "share-done-0001"
        result = {"system_design_recommendation": {"compute": "t3.medium"}}
        _put_job(job_id, status="done", stage="Complete", result=result)

        shared = await _aget(f"/api/share/{job_id}")
        polled = await _aget(f"/api/recommend/{job_id}")
        assert shared.status_code == 200
        assert shared.json() == polled.json()
        assert shared.json()["result"] == result

    asyncio.run(_scenario())


def test_share_returns_404_for_any_job_that_is_not_done():
    async def _scenario():
        _put_job("share-running-0002", status="running", stage="Analyzing repository")
        _put_job(
            "share-awaiting-0003",
            status="awaiting_input",
            stage="Collecting requirements",
            next_question="How much traffic?",
        )
        _put_job(
            "share-error-0004",
            status="error",
            stage="Researching cache options",
            error="TimedOut: job took too long",
        )

        for job_id in ("share-running-0002", "share-awaiting-0003", "share-error-0004"):
            resp = await _aget(f"/api/share/{job_id}")
            assert resp.status_code == 404, job_id
            assert "not found" in resp.json()["detail"].lower()
            # In-progress detail must not leak through the share path.
            assert "How much traffic?" not in resp.text
            assert "TimedOut" not in resp.text

        unknown = await _aget("/api/share/00000000-0000-0000-0000-000000000000")
        assert unknown.status_code == 404

    asyncio.run(_scenario())


# ---------------------------------------------------------------------------
# Event bus backends
# ---------------------------------------------------------------------------


def test_inmemory_bus_delivers_events_and_cleans_up_on_close():
    async def _scenario():
        bus = InMemoryEventBus()
        subscription = await bus.subscribe("bus-job-1")
        assert bus.subscriber_count("bus-job-1") == 1
        assert await subscription.next_event(timeout=0.01) is None  # idle

        bus.publish("bus-job-1", {"status": "running"})
        assert await subscription.next_event(timeout=1.0) == {"status": "running"}

        # Published from a worker thread — the real call pattern.
        thread = threading.Thread(
            target=bus.publish, args=("bus-job-1", {"status": "done"})
        )
        thread.start()
        thread.join()
        assert await subscription.next_event(timeout=1.0) == {"status": "done"}

        subscription.close()
        assert subscription.closed
        assert bus.subscriber_count("bus-job-1") == 0
        assert await subscription.next_event(timeout=0.01) is None

        # Publishing to a job nobody subscribes to is a harmless no-op.
        bus.publish("bus-job-nobody", {"status": "done"})

    asyncio.run(_scenario())


def test_inmemory_bus_fans_out_to_every_subscriber():
    async def _scenario():
        bus = InMemoryEventBus()
        first = await bus.subscribe("bus-job-2")
        second = await bus.subscribe("bus-job-2")
        assert bus.subscriber_count("bus-job-2") == 2

        bus.publish("bus-job-2", {"current_stage": "Analyzing repository"})
        assert (await first.next_event(timeout=1.0)) == {
            "current_stage": "Analyzing repository"
        }
        assert (await second.next_event(timeout=1.0)) == {
            "current_stage": "Analyzing repository"
        }

        first.close()
        assert bus.subscriber_count("bus-job-2") == 1
        second.close()
        assert bus.subscriber_count("bus-job-2") == 0

    asyncio.run(_scenario())


def test_redis_bus_publishes_and_fans_out_via_pubsub():
    """fakeredis stands in for a real Redis server (no network)."""

    async def _scenario():
        bus = RedisEventBus(fakeredis.FakeStrictRedis())
        subscription = await bus.subscribe("redis-job-1")
        assert bus.subscriber_count("redis-job-1") == 1
        assert subscription.channel == "inframind:events:redis-job-1"

        thread = threading.Thread(
            target=bus.publish, args=("redis-job-1", {"status": "running"})
        )
        thread.start()
        thread.join()

        assert await subscription.next_event(timeout=2.0) == {"status": "running"}

        subscription.close()
        assert bus.subscriber_count("redis-job-1") == 0
        assert subscription.closed

    asyncio.run(_scenario())


def test_decode_message_tolerates_junk_on_the_channel():
    assert _decode_message(b'{"status": "done"}') == {"status": "done"}
    assert _decode_message('{"status": "done"}') == {"status": "done"}
    assert _decode_message(b"not-json") is None
    assert _decode_message(b'["not", "a", "dict"]') is None
    assert _decode_message(None) is None


def test_build_event_bus_defaults_to_in_process_when_redis_url_unset(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    assert isinstance(build_event_bus(), InMemoryEventBus)


def test_build_event_bus_uses_redis_when_configured(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    with patch(
        "app.api.event_bus.RedisEventBus.from_url",
        return_value=RedisEventBus(fakeredis.FakeStrictRedis()),
    ) as from_url:
        bus = build_event_bus()
    from_url.assert_called_once_with("redis://localhost:6379/0")
    assert isinstance(bus, RedisEventBus)


def test_build_event_bus_falls_back_when_redis_unavailable(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    with patch(
        "app.api.event_bus.RedisEventBus.from_url",
        side_effect=ConnectionError("connection refused"),
    ):
        assert isinstance(build_event_bus(), InMemoryEventBus)


# ---------------------------------------------------------------------------
# Store publish hooks — the existing update points ARE the publish triggers
# ---------------------------------------------------------------------------


class _RecordingPublisher:
    """Stand-in bus that records every published snapshot."""

    def __init__(self) -> None:
        self.published: list[tuple[str, dict[str, Any]]] = []

    def publish(self, job_id: str, payload: dict[str, Any]) -> None:
        self.published.append((job_id, payload))

    async def subscribe(self, job_id: str):  # pragma: no cover - not used here
        raise AssertionError("subscribe() is not exercised by these tests")

    def subscriber_count(self, job_id: str) -> int:
        return 0


class _ExplodingPublisher:
    """Bus that fails — streaming must never break the job that emits it."""

    def publish(self, job_id: str, payload: dict[str, Any]) -> None:
        raise RuntimeError("event bus unavailable")

    async def subscribe(self, job_id: str):  # pragma: no cover - not used here
        raise AssertionError("subscribe() is not exercised by these tests")

    def subscriber_count(self, job_id: str) -> int:
        return 0


def test_module_level_store_is_wired_to_the_event_bus():
    """The app's single job store publishes into the app's single bus."""
    assert jobs._publisher is event_bus


def test_inmemory_store_publishes_from_existing_update_points():
    publisher = _RecordingPublisher()
    store = InMemoryJobStore(publisher=publisher)
    job = _new_job("pub-1")
    store.put(job)

    store.update_stage(job.job_id, "Analyzing repository")
    store.update_status(job.job_id, "done", result={"ok": True})
    store.update_retry_info(job.job_id, "Retrying after rate limit (attempt 2 of 4)")

    assert [job_id for job_id, _ in publisher.published] == ["pub-1"] * 3
    assert [payload["status"] for _, payload in publisher.published] == [
        "collecting",  # update_stage only changes current_stage
        "done",
        "done",
    ]
    assert [payload["current_stage"] for _, payload in publisher.published] == [
        "Analyzing repository",
        "Analyzing repository",
        "Analyzing repository",
    ]
    assert publisher.published[1][1]["result"] == {"ok": True}
    # Each event is exactly the polling projection for the new state.
    assert publisher.published[2][1] == job_snapshot_from_job(store.get(job.job_id))

    # update_state is intentionally not a publish trigger: next_question is
    # always accompanied by update_status("awaiting_input").
    published_before = len(publisher.published)
    store.update_state(
        job.job_id, {**_make_state(), "next_question": "How much traffic?"}
    )
    assert len(publisher.published) == published_before

    store.update_status(job.job_id, "awaiting_input", next_question="How much traffic?")
    assert publisher.published[-1][1]["next_question"] == "How much traffic?"


def test_inmemory_store_without_publisher_behaves_as_before():
    store = InMemoryJobStore()
    job = _new_job("pub-2")
    store.put(job)
    store.update_stage(job.job_id, "Validating requirements")
    assert store.get(job.job_id).current_stage == "Validating requirements"


def test_store_swallows_publish_failures():
    store = InMemoryJobStore(publisher=_ExplodingPublisher())
    job = _new_job("pub-3")
    store.put(job)

    store.update_stage(job.job_id, "Validating requirements")  # must not raise
    store.update_status(job.job_id, "error", error="boom")

    assert store.get(job.job_id).current_stage == "Validating requirements"
    assert store.get(job.job_id).error == "boom"


def test_redis_store_publishes_after_each_durable_write():
    publisher = _RecordingPublisher()
    store = RedisJobStore(fakeredis.FakeStrictRedis(), publisher=publisher)
    job = _new_job("pub-redis-1")
    store.put(job)

    store.update_stage(job.job_id, "Analyzing repository")
    store.update_status(job.job_id, "done", result={"ok": True})

    assert [payload["current_stage"] for _, payload in publisher.published] == [
        "Analyzing repository",
        "Analyzing repository",
    ]
    assert publisher.published[-1][1]["status"] == "done"
    assert publisher.published[-1][1]["result"] == {"ok": True}
    # Published only after the record is durable (same store, same snapshot).
    assert store.get(job.job_id).status == "done"
