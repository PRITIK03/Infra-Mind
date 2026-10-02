"""
Quota-free load and characterization test script.

Exercises:
1. Health & readiness endpoints (/api/health, /api/health/ready)
2. Polling endpoint throughput (/api/recommend/{job_id}) on seeded fixture
3. SSE concurrent stream capacity & enforcement (/api/recommend/{job_id}/stream)

Runs using seeded fixtures without making live LLM or external AWS/Vantage calls.
"""

from __future__ import annotations

import asyncio
import statistics
import time
from typing import Any

import httpx

# Pre-set mock env before app import to satisfy startup validation
import os
os.environ.setdefault("API_KEY", "dummy-key")
os.environ.setdefault("BASE_URL", "https://example.com/v1")
os.environ.setdefault("MODEL_NAME", "dummy-model")
os.environ.setdefault("VANTAGE_API_KEY", "dummy-vantage-key")
os.environ.setdefault("CORS_ALLOWED_ORIGIN", "http://localhost:3000")

from app.api.job_store import Job
from app.api.main import app
from app.api.rate_limit import stream_limiter
from app.api.runtime import jobs


def seed_test_job(job_id: str = "load-test-seeded-001") -> str:
    jobs.put(
        Job(
            job_id=job_id,
            status="done",
            current_stage="Complete",
            state={},
            result={
                "system_design_recommendation": {
                    "architecture_summary": "Two-tier web service behind an ALB.",
                    "compute": {
                        "recommended_instance": "m5.large",
                        "why": "Standard benchmark workload.",
                        "confidence": "high",
                    },
                    "estimated_cost": {"total_monthly_low": 120.0, "total_monthly_high": 150.0},
                }
            },
        )
    )
    return job_id


async def benchmark_endpoint(
    client: httpx.AsyncClient,
    path: str,
    total_requests: int = 200,
    concurrency: int = 20,
) -> dict[str, Any]:
    latencies: list[float] = []
    status_counts: dict[int, int] = {}
    sem = asyncio.Semaphore(concurrency)

    async def _fetch():
        async with sem:
            t0 = time.perf_counter()
            resp = await client.get(path)
            t1 = time.perf_counter()
            latencies.append((t1 - t0) * 1000.0)  # ms
            status_counts[resp.status_code] = status_counts.get(resp.status_code, 0) + 1

    t_start = time.perf_counter()
    await asyncio.gather(*[_fetch() for _ in range(total_requests)])
    t_total = time.perf_counter() - t_start

    latencies.sort()
    p50 = statistics.median(latencies)
    p95 = latencies[int(len(latencies) * 0.95)]
    p99 = latencies[int(len(latencies) * 0.99)]
    rps = total_requests / t_total

    return {
        "path": path,
        "total_requests": total_requests,
        "concurrency": concurrency,
        "total_duration_sec": round(t_total, 3),
        "requests_per_sec": round(rps, 1),
        "lat_p50_ms": round(p50, 2),
        "lat_p95_ms": round(p95, 2),
        "lat_p99_ms": round(p99, 2),
        "min_ms": round(min(latencies), 2),
        "max_ms": round(max(latencies), 2),
        "status_counts": status_counts,
    }


async def verify_sse_stream_capacity(client: httpx.AsyncClient, job_id: str) -> dict[str, Any]:
    """Test concurrent stream cap enforcement per client IP."""
    stream_limiter.clear()
    
    # We will attempt 8 concurrent connections where max is 5
    results: list[int] = []

    async def _connect_stream(idx: int):
        try:
            # We initiate a streaming request
            async with client.stream("GET", f"/api/recommend/{job_id}/stream") as response:
                results.append(response.status_code)
                if response.status_code == 200:
                    # Read the first event then wait slightly
                    async for _ in response.aiter_lines():
                        await asyncio.sleep(0.05)
                        break
        except Exception:
            results.append(500)

    tasks = [asyncio.create_task(_connect_stream(i)) for i in range(8)]
    await asyncio.gather(*tasks)

    count_200 = results.count(200)
    count_429 = results.count(429)

    return {
        "attempted_concurrent_streams": 8,
        "configured_max_streams_per_ip": stream_limiter.max_streams,
        "streams_admitted_200": count_200,
        "streams_rejected_429": count_429,
        "cap_strictly_enforced": (count_200 == stream_limiter.max_streams and count_429 == 3),
    }


async def run_full_load_test():
    job_id = seed_test_job()
    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 50000))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        print("--- [1/3] Benchmarking Liveness /api/health ---")
        health_res = await benchmark_endpoint(client, "/api/health", total_requests=300, concurrency=25)
        print(f"  RPS: {health_res['requests_per_sec']} req/s | p50: {health_res['lat_p50_ms']}ms | p95: {health_res['lat_p95_ms']}ms | p99: {health_res['lat_p99_ms']}ms")
        
        print("\n--- [2/3] Benchmarking Seeded Job Polling /api/recommend/{job_id} ---")
        poll_res = await benchmark_endpoint(client, f"/api/recommend/{job_id}", total_requests=250, concurrency=25)
        print(f"  RPS: {poll_res['requests_per_sec']} req/s | p50: {poll_res['lat_p50_ms']}ms | p95: {poll_res['lat_p95_ms']}ms | p99: {poll_res['lat_p99_ms']}ms")

        print("\n--- [3/3] Testing SSE Concurrency Stream Cap Enforcement ---")
        sse_res = await verify_sse_stream_capacity(client, job_id)
        print(f"  Attempted: {sse_res['attempted_concurrent_streams']} streams | Allowed (200): {sse_res['streams_admitted_200']} | Rejected (429): {sse_res['streams_rejected_429']}")
        print(f"  Cap Enforced: {sse_res['cap_strictly_enforced']}")

        return {
            "health_benchmark": health_res,
            "polling_benchmark": poll_res,
            "sse_concurrency_test": sse_res,
        }


if __name__ == "__main__":
    asyncio.run(run_full_load_test())
