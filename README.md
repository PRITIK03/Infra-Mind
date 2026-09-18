# InfraMind — AWS Instance Advisor

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
