# InfraMind — AWS Instance Advisor

[![Backend Tests](https://github.com/PRITIK03/Infra-Mind/actions/workflows/backend-tests.yml/badge.svg)](https://github.com/PRITIK03/Infra-Mind/actions/workflows/backend-tests.yml)
[![Frontend Tests](https://github.com/PRITIK03/Infra-Mind/actions/workflows/frontend-tests.yml/badge.svg)](https://github.com/PRITIK03/Infra-Mind/actions/workflows/frontend-tests.yml)

An AI agent that gathers your workload requirements, reasons about system design, researches live AWS instance data across compute, database, and cache tiers, and recommends the optimal setup — with deployable Terraform files generated automatically.

This repository is a monorepo with two projects:

```
aws-instance-advisor/   ← Python backend (FastAPI + LangGraph agent)
aws-advisor-ui/         ← Next.js frontend (chat UI + results dashboard)
```

---

## How it works

1. You describe your application and expected workload (via CLI or the web UI).
2. The agent asks clarifying questions until it has enough context.
3. It reasons about system design — concurrency, resource profile, traffic pattern, scaling strategy.
4. It researches live EC2, RDS, and ElastiCache instance data.
5. It returns a full architecture recommendation (compute + database + cache + load balancer) with confidence scores and trade-offs.
6. Terraform files for the recommended setup are written to `aws-instance-advisor/terraform_output/`.

---

## Prerequisites

| Tool | Minimum version |
|------|----------------|
| Python | 3.11 |
| Node.js | 18 |
| npm | 10 |

---

## Quick start (local — both services)

### 1. Clone the repo

```bash
git clone https://github.com/PRITIK03/Infra-Mind--host-rec..-.git
cd Infra-Mind--host-rec..-
```

### 2. Set up the backend

```bash
cd aws-instance-advisor

# Create and activate a virtual environment
python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Copy the env template and fill in your keys
cp .env.example .env
```

Open `.env` and set:

| Variable | Required | Description |
|----------|----------|-------------|
| `API_KEY` | Yes | Your OpenRouter API key |
| `BASE_URL` | Yes | OpenRouter base URL (`https://openrouter.ai/api/v1`) |
| `MODEL_NAME` | Yes | Model slug e.g. `anthropic/claude-3.5-sonnet` |
| `VANTAGE_API_KEY` | Yes | [Vantage](https://www.vantage.sh/) API key for live EC2 pricing data |
| `TAVILY_API_KEY` | No | Enables a web-search round during reasoning. Agent works without it. |
| `LLM_MAX_TOKENS` | No | Overall response token budget (default `8192`) |
| `LLM_REASONING_MAX_TOKENS` | No | Subset of `LLM_MAX_TOKENS` reserved for the model's internal reasoning; mapped onto OpenRouter `reasoning.effort` (default `2048`) |
| `LLM_FALLBACK_MODELS` | No | Optional comma-separated list of OpenRouter model slugs to try server-side when `MODEL_NAME` is rate-limited or unavailable. Additive to `API_KEY_2` failover. |
| `API_KEY_2` | No | Second OpenRouter key for automatic rate-limit failover |
| `CORS_ALLOWED_ORIGIN` | Yes | Explicit frontend origin; use `http://localhost:3000` locally and the real Vercel domain in production |
| `PORT` | No | FastAPI port (default `8000`) |
| `DATABASE_URL` | No | Optional SQLite/Postgres URL enabling run-history persistence via `GET /api/runs`. Without it, jobs are process-local and lost on restart. |
| `RATE_LIMIT_MAX_REQUESTS` | No | Recommendation requests allowed per client IP per window (default `5`) |
| `RATE_LIMIT_WINDOW_SECONDS` | No | Recommendation rate-limit window (default `60`) |
| `REDIS_URL` | No | Optional Redis URL enabling a persistent job store (survives restarts, shared across backend instances). Without it, jobs are in-memory only — fine for single-instance dev/demo. Records expire after 24h. |
| `SENTRY_DSN` | No | Optional Sentry Data Source Name for error monitoring (e.g. `https://<key>@o0.ingest.sentry.io/0`). The app runs identically without it; Sentry's free tier covers this project's scale. |
| `SENTRY_TRACES_SAMPLE_RATE` | No | Fraction of requests traced for performance monitoring (default `0.0` = error monitoring only). Keep `0.0` to protect free-tier quota. |
| `GITHUB_MCP_TOKEN` | No | Optional GitHub PAT (repo read scope) enabling repository analysis. Absent → repo analysis is skipped and the agent runs unchanged. |

### 3. Start the backend API

From `aws-instance-advisor/`:

```bash
uvicorn app.api.main:app --reload --port 8000
```

⚠️ The ASGI application is `app.api.main:app` — never `app.main:app`.
`app.main` is the terminal CLI entrypoint; running `uvicorn app.main:app`
starts a server that silently returns 404 for every route.

The API will be available at `http://localhost:8000`. Verify with:

```bash
curl http://localhost:8000/api/health
```

### 4. Set up the frontend

From the repository root:

```bash
cd aws-advisor-ui
npm install
cp .env.example .env.local
```

`.env.local` only needs:

```
NEXT_PUBLIC_API_URL=http://localhost:8000
```

### 5. Start the frontend

```bash
npm run dev
```

Open `http://localhost:3000` in your browser.

---

## CLI mode (no frontend needed)

From `aws-instance-advisor/` with the venv active:

```bash
python -m app.main
```

---

## Running tests

```bash
# Backend
cd aws-instance-advisor
pytest -v

# Frontend
cd aws-advisor-ui
npm test            # runs Vitest
```

---

## Optional integrations & operational notes

> Every item below is optional. Left unset, the app starts and runs exactly as in the minimal install above — mirroring the same graceful-skip pattern used for `TAVILY_API_KEY` and `DATABASE_URL`.

**Redis (`REDIS_URL`)** — Without it, jobs live in process-local memory only (fine for single-instance dev/demo). Set it to survive backend restarts and to share jobs across multiple instances/pods; job records carry a 24h TTL so Redis doesn't grow unbounded.
> ⚠️ Resume-path caveat on multiple instances: `AgentState` (live candidate lists and Pydantic objects) is intentionally **not** persisted to Redis — it's process-local working memory for the thread executing the job. `POST /api/recommend/{job_id}/answer` therefore has to reach the *same* instance that owns the job. If you scale beyond one backend instance, either pin all job execution to a single replica, or terminate TLS and enable sticky sessions / instance-affinity routing so `/answer` is routed to the correct instance. `GET /api/recommend/{job_id}` polling is fully safe to load-balance.

**Sentry (`SENTRY_DSN`)** — Optional error monitoring via `sentry-sdk`. When set, **unhandled** route exceptions that produce HTTP 5xx are captured automatically by the FastAPI integration — no per-route wiring, and `HTTPException` responses (e.g. the 404/429 above) are intentionally **not** reported. The wall-clock job-timeout path and graph exceptions are caught deliberately by `app/api/main.py` and never reach FastAPI, so those two are reported explicitly (`capture_exception` / `capture_message`); all of it is a silent no-op when `SENTRY_DSN` is unset. Sentry's free tier covers this project's scale. `SENTRY_TRACES_SAMPLE_RATE` defaults to `0.0` (error monitoring only — tracing burns free-tier quota fast).

**GitHub MCP (`GITHUB_MCP_TOKEN`)** — Optional. A GitHub PAT with `repo` scope enables per-repository analysis when a repo URL is supplied; the recommendation then carries the result. Absent the token, the `analyze_repository` node is skipped and the agent runs fully unchanged, surfacing an honest note that no repo context was available (see `app/tools/github_mcp.py`).

**CI/CD (status badges at the top of this file)** — GitHub Actions run `Backend Tests` (pytest) and `Frontend Tests` (Vitest + `next build`) on push to `main`/`V2` and on PRs into those branches. The frontend workflow installs a *pinned* `@rolldown/binding-linux-x64-gnu` (exact version taken from `package-lock.json`) — a workaround for npm's optional-dependency bug `npm/cli#4828`, without which `npm ci` succeeds (exit 0) but the platform binding is silently omitted and vitest exits immediately at startup. Don't remove that step if the frontend tests ever start failing with "Cannot find native binding".

---

## Docker (backend only)

From `aws-instance-advisor/`:

```bash
docker build -t infra-mind .
docker run -p 8000:8000 --env-file .env infra-mind
```

---

## Deploying to Vercel

Deploy the backend separately (Render, Railway, Fly, etc.) using
`aws-instance-advisor/Dockerfile`. Set `CORS_ALLOWED_ORIGIN` to the final
Vercel frontend origin.

In Vercel, set **Root Directory** to `aws-advisor-ui` and configure:

| Variable | Required | Description |
|----------|----------|-------------|
| `NEXT_PUBLIC_API_URL` | Yes | Public HTTPS URL of the deployed backend API, without a trailing slash. |

---

## Project structure

```
.
├── aws-instance-advisor/      # Python backend (FastAPI + LangGraph agent)
│   ├── app/                   # FastAPI + LangGraph agent
│   ├── tests/                 # pytest suite
│   ├── terraform_output/      # Generated Terraform (git-ignored)
│   ├── Dockerfile
│   ├── requirements.txt
│   └── .env.example
│
├── aws-advisor-ui/            # Next.js frontend (chat UI + results dashboard)
│   ├── src/
│   ├── public/
│   ├── package.json
│   └── .env.example
│
├── result_dump.json           # Saved agent result for screenshot / regression testing
└── README.md                  # this file
```

Backend details: see [aws-instance-advisor/README.md](aws-instance-advisor/README.md).

---

## API reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/health` | Liveness probe |
| `POST` | `/api/recommend` | Start a new job `{ "message": "..." }` |
| `GET` | `/api/recommend/{job_id}` | Poll job status / result |
| `POST` | `/api/recommend/{job_id}/answer` | Reply to a follow-up question `{ "answer": "..." }` |
| `GET` | `/api/stats` | Live instance-type counts (EC2 / RDS / cache) for landing page readouts |
| `GET` | `/api/runs` | Paginated run-history list; query params `?page=1&page_size=20` |

Job status values: `collecting` → `running` → `awaiting_input` → `done` / `error`
