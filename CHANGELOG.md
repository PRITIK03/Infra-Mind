# Changelog

All notable changes to the **InfraMind (AWS Instance Advisor)** project are documented in this file.
This changelog is derived from the repository git history.

## [Unreleased] - 2026-10-02

### Added
- **Architecture Documentation:** Comprehensive `ARCHITECTURE.md` documenting LangGraph pipeline stages, Mermaid system architecture diagrams, and real technical decisions (SSE vs WebSockets, deterministic Terraform, anti-hallucination grounding, dual-store pattern, and consensus scoping).
- **Docker Compose Stack:** Root `docker-compose.yml` spinning up FastAPI backend and local Redis instance with healthcheck-driven startup for local multi-instance state verification.
- **Fail-Fast Startup Configuration Validation:** Consolidated `validate_startup_config()` ensuring required env vars fail immediately at startup with clear diagnostic error messages.
- **Quota-Free Infrastructure Load Test:** `scripts/load_test.py` benchmarking HTTP liveness (1030+ req/s), seeded polling (1020+ req/s), and verifying strict per-IP SSE concurrent stream cap enforcement (5 streams admitted, 3 rejected with 429).
- **Housekeeping & Governance:** Standard `LICENSE` (MIT), `CONTRIBUTING.md` documenting branch workflow (`V2` base, CI green requirements), and pinned `requirements.txt` dependencies.

---

## [V2.2.0] - 2026-10-01

### Added
- **Playwright E2E Smoke Suite:** End-to-end browser test suite verifying user interaction, multi-tier result rendering, and read-only share view over a seeded test stack.
- **Accessibility & Axe Suite:** `vitest-axe` suite auditing WCAG/a11y compliance across all major components and views.
- **Social Previews & Meta:** OpenGraph previews populated from real job result attributes, `/how-it-works` documentation page, and keyboard shortcuts palette.
- **Readiness Probes:** `GET /api/health/ready` performing non-blocking zero-outbound checks on Redis connectivity and active integrations.

---

## [V2.1.0] - 2026-09-30

### Added
- **Server-Sent Events (SSE) Streaming:** `GET /api/recommend/{job_id}/stream` for real-time progress updates with heartbeat support and automatic fallback to HTTP polling.
- **Per-IP Concurrent Stream Limiting:** `InMemoryConcurrentStreamLimiter` enforcing a strict concurrent connection cap to protect event loop resources.
- **Modular API Architecture:** Clean separation of schemas, rate limiting, SSE generators, and job runners into dedicated submodules.

---

## [V2.0.0] - 2026-09-21 - 2026-09-29

### Added
- **Multi-Tier AWS Sizing Pipeline:** Complete LangGraph V2 graph covering EC2 compute, RDS database, and ElastiCache caching tiers.
- **Deterministic Well-Architected Review:** Static analysis of architecture selections against AWS Well-Architected Framework pillars without additional LLM latency.
- **Deterministic ECS Fargate Sizing:** Alternative containerized sizing heuristics when a Dockerfile is detected.
- **Opt-In Multi-Model Consensus:** Secondary model validation (`CONSENSUS_MODEL`) comparing architectural tiers with deterministic disagreement metrics.
- **Pluggable Redis Job Store:** TTL-backed `RedisJobStore` with automatic fallback to in-memory store on connection failure.
- **Three-Key Rate Limit Failover:** Cycling primary (`API_KEY`), secondary (`API_KEY_2`), and tertiary (`API_KEY_3`) keys upon 429 rate limit errors.
- **Interactive Conversational Follow-Up:** `POST /api/recommend/{job_id}/followup` allowing users to ask architectural questions grounded in the generated recommendation.

---

## [V1.0.0] - 2026-08-12 - 2026-09-12

### Added
- **Initial Agent & LangGraph Pipeline:** Multi-turn requirement gathering loop with conversational slot-filling.
- **Live Vantage EC2 Data Integration:** Real-time catalog fetching for instance specifications, vCPU, memory, and pricing.
- **Deterministic Terraform Generator:** Production of valid HCL templates (`main.tf`, `variables.tf`, `outputs.tf`) with least-privilege security groups.
- **Next.js Frontend:** Interactive dashboard featuring topology diagrams, candidate landscape tables, and confidence indicators.
