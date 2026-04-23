# Savage Health Center

A self-hosted personal health command center — recovery, sleep, training, and clinical data unified in a single dashboard, with AI-generated coaching.

## What it is

A premium health OS built around WHOOP, Apple Health, and manual training logs. It computes derived metrics (HRV deviation, ACWR, sleep consistency, readiness composites) and surfaces them in a dark, data-dense dashboard. Claude Sonnet 4.6 generates next-workout recommendations and daily briefings with full clinical context.

Not a generic wellness app. Built for a single user with known medical context, medications, and multi-year training history.

---

## Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.12, FastAPI, DuckDB 1.1 |
| Package manager | `uv` |
| Scheduler | APScheduler |
| LLM | Claude Sonnet 4.6 (Anthropic SDK) + Ollama fallback |
| Frontend | Next.js 15, React 19, TypeScript |
| Styling | Tailwind CSS v4, OKLCH tokens |
| UI components | shadcn/ui + Radix UI |
| Charts | Recharts |
| Data fetching | TanStack Query v5 |
| Secrets | macOS Keychain |

---

## Quickstart

### Prerequisites

- macOS (Keychain required for secrets)
- Python 3.12+
- Node 20+
- `uv` (`brew install uv`)
- `honcho` (`pip install honcho`)
- Ollama (optional, for local LLM fallback)

### Install

```bash
git clone <repo-url> savage-health-center
cd savage-health-center
make install
```

### Configure

```bash
cp env.example .env
```

Edit `.env` — minimum required keys:

| Variable | Purpose |
|---|---|
| `ANTHROPIC_API_KEY` | Claude API for AI coaching + briefings |
| `WHOOP_CLIENT_ID` | WHOOP OAuth app ID |
| `WHOOP_CLIENT_SECRET` | WHOOP OAuth secret |
| `DATA_DIR` | Where DuckDB and logs are stored (default: `data/`) |

Full variable reference: [Environment variables](#environment-variables).

### Seed and run

```bash
make seed    # populate DuckDB with 90 days synthetic data
make dev     # API on :8000, web on :3000
```

Open [http://localhost:3000](http://localhost:3000).

---

## Make targets

```
make install     Install backend (uv sync) + frontend (npm install)
make dev         Start all services via honcho (Procfile)
make seed        Seed DuckDB with 90 days synthetic data
make reset       Drop DB, re-run migrations, re-seed (requires CONFIRM=1)
make logs        Tail all log files
make doctor      Verify config, DuckDB, and Ollama connectivity
make lint        Run ruff lint + format check
make typecheck   Run pyright (basic mode)
make test        Run pytest
```

---

## Architecture

```
savage-health-center/
├── backend/
│   └── src/shc/
│       ├── api/
│       │   ├── main.py          # FastAPI app, lifespan hooks, CORS
│       │   └── routers/
│       │       ├── dashboard.py # 20+ data endpoints
│       │       ├── auth.py      # WHOOP OAuth flow
│       │       └── chat.py      # AI advisor streaming
│       ├── ai/
│       │   └── briefing.py      # Claude API calls, token caching, cost logging
│       ├── auth/
│       │   └── keychain.py      # macOS Keychain token storage
│       ├── db/
│       │   ├── schema.py        # DuckDB init, migrations, write lock
│       │   └── migrations/      # SQL migrations (0001–0005)
│       ├── ingest/
│       │   ├── whoop.py         # WHOOP OAuth client, sync jobs
│       │   └── apple.py         # Apple Health CCDA XML parser
│       ├── scheduler/
│       │   └── jobs.py          # APScheduler background tasks
│       └── config.py            # Pydantic Settings
└── frontend/
    ├── app/
    │   ├── page.tsx             # Root dashboard layout
    │   ├── layout.tsx           # Font + metadata
    │   └── globals.css          # Design tokens (OKLCH, dark theme)
    ├── components/
    │   ├── command-briefing.tsx # Today's headline strip
    │   ├── pillar-recovery.tsx  # Recovery Intelligence card
    │   ├── pillar-sleep.tsx     # Sleep Architecture card
    │   ├── pillar-training-load.tsx  # ACWR + strain card
    │   ├── pillar-readiness.tsx # Composite readiness card
    │   ├── strength-panel.tsx   # Training heatmap + PRs
    │   ├── trend-intelligence.tsx    # 90d tabbed trends
    │   ├── next-workout.tsx     # AI-generated next session
    │   ├── advisor-chat.tsx     # Cmd+K AI chat sheet
    │   └── right-rail.tsx       # Streaks, bests, weekly summary
    └── lib/
        └── api.ts               # Typed fetch wrappers + TanStack Query
```

### Data flow

```
WHOOP API ──────────────┐
Apple Health (iCloud) ──┤──► ingest layer ──► DuckDB ──► FastAPI ──► Next.js
Manual checkins ────────┘                               │
                                                        └──► Claude API ──► /api/workout/next
                                                                          └──► /api/briefing
```

### Database

Embedded DuckDB at `$DATA_DIR/shc.duckdb`. Key tables:

| Table | Contents |
|---|---|
| `recovery` | WHOOP daily: score, HRV, RHR, skin temp |
| `sleep` | Stage durations (JSON), SpO2, consistency |
| `workout_sets` | Exercise, sets, reps, volume_kg, RPE |
| `cardio_sessions` | Cardio with strain, zone distribution |
| `measurements` | Generic time-series (VO₂ max, body mass, step count) |
| `medications` | Bitemporal (valid_from/valid_to) |
| `conditions` | Diagnoses with bitemporal tracking |
| `labs` | Lab results by date |
| `llm_calls` | Observability: model, tokens, cache hits, cost |
| `ai_briefing` | Generated training calls and coaching notes |

Migrations live in `backend/src/shc/db/migrations/` and run automatically on startup.

---

## Data sources

| Source | Method | Status |
|---|---|---|
| WHOOP | OAuth 2.0 → background sync | Wired |
| Apple Health | iCloud HealthAutoExport → CCDA XML | Wired |
| Fitbod | CSV import | Planned (P2) |
| Hevy | API key | Planned (P2) |
| Manual checkin | POST `/api/checkin` | Wired |

---

## AI features

### Next workout

`GET /api/workout/next` calls Claude Sonnet 4.6 with:
- Today's readiness tier (green / yellow / red)
- 28-day HRV trend and deviation
- Recent workout volume and set counts
- Active medications and conditions with clinical notes

Returns a structured plan (warmup → blocks → cooldown) with RPE targets and clinical adjustments. Response is cached in `ai_briefing` to avoid repeated API calls; pass `?regen=true` to force refresh.

### Daily briefing

`GET /api/briefing` generates a daily training call and readiness headline. Cached per calendar day.

### LLM mode

| `SHC_LLM_MODE` | Behaviour |
|---|---|
| `auto` (default) | Try Claude API; fall back to Ollama on error |
| `local_only` | Always use Ollama (no Anthropic calls) |

Cost is capped at `ANTHROPIC_DAILY_CAP_USD` (default `2.00`). Every LLM call is logged to `llm_calls` with token counts, cache hit/miss, and USD cost.

---

## Computed metrics

| Metric | Definition |
|---|---|
| HRV deviation (σ) | `(today − 28d avg) / 28d SD` |
| ACWR | 7d avg recovery / 28d avg recovery (safe zone 0.8–1.3) |
| Sleep consistency | stddev of sleep hours across 7 nights |
| Readiness composite | HRV 40% + sleep 30% + RHR 20% + subjective 10% |
| Volume progression | prior 8-week avg vs recent 8-week avg |

---

## Environment variables

```bash
# Storage
DATA_DIR=data                         # DuckDB + logs root

# WHOOP OAuth
WHOOP_CLIENT_ID=
WHOOP_CLIENT_SECRET=
WHOOP_REDIRECT_URI=http://127.0.0.1:8000/auth/whoop/callback

# Anthropic
ANTHROPIC_API_KEY=
ANTHROPIC_DAILY_CAP_USD=2.00

# LLM routing
SHC_LLM_MODE=auto                     # auto | local_only

# Ollama (local fallback)
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=llama3.3:70b

# Server
HOST=127.0.0.1
PORT=8000
FRONTEND_ORIGIN=http://localhost:3000
```

Sensitive tokens (WHOOP refresh token, Hevy API key, DB encryption key) are stored in macOS Keychain, not `.env`.

---

## Logging

Logs write to `$DATA_DIR/logs/shc.log` (10 MB rotating, 5 backups) and to stdout (JSON format). Level defaults: `shc.*` at DEBUG, everything else at INFO.

Override via `logging.yaml` at the repo root.

---

## Security & privacy

All data stays local. No telemetry, no cloud sync outside of source APIs (WHOOP, Apple Health iCloud export). DuckDB can be encrypted at rest — set the key via `shc auth set-db-key` (stored in Keychain).

The session-token auth layer (`010bc73`) gates the dashboard behind a locally-issued token to prevent casual access to PHI on shared machines.

---

## API reference

See [docs/API.md](docs/API.md) for the full endpoint list with request/response shapes.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

---

## Changelog

See [CHANGELOG.md](CHANGELOG.md).
