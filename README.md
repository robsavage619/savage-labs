<div align="center">
<br />

```
███████╗ █████╗ ██╗   ██╗ █████╗  ██████╗ ███████╗
██╔════╝██╔══██╗██║   ██║██╔══██╗██╔════╝ ██╔════╝
███████╗███████║██║   ██║███████║██║  ███╗█████╗  
╚════██║██╔══██║╚██╗ ██╔╝██╔══██║██║   ██║██╔══╝  
███████║██║  ██║ ╚████╔╝ ██║  ██║╚██████╔╝███████╗
╚══════╝╚═╝  ╚═╝  ╚═══╝  ╚═╝  ╚═╝ ╚═════╝ ╚══════╝
```

### SAVAGE HEALTH CENTER

*A personal health OS — not a wellness app*

<br />

![Python](https://img.shields.io/badge/Python-3.12-1e1e2e?style=flat-square&labelColor=1e1e2e&color=cba6f7)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-1e1e2e?style=flat-square&labelColor=1e1e2e&color=a6e3a1)
![Next.js](https://img.shields.io/badge/Next.js-15-1e1e2e?style=flat-square&labelColor=1e1e2e&color=89b4fa)
![Claude](https://img.shields.io/badge/Claude-Sonnet_4.6-1e1e2e?style=flat-square&labelColor=1e1e2e&color=f38ba8)
![DuckDB](https://img.shields.io/badge/DuckDB-1.1-1e1e2e?style=flat-square&labelColor=1e1e2e&color=fab387)

<br />
</div>

---

Every morning there is one question: **can I push today?**

WHOOP gives you a score. Apple Health gives you data. Your training log gives you history. None of them know your medications. None of them talk to each other.

SHC does. It pulls from every source, computes the metrics that actually matter — HRV deviation in σ, ACWR, composite readiness, volume progression — and hands off to Claude Sonnet 4.6, which knows your full clinical context, to write today's training call.

Everything runs locally. Your data never leaves your machine.

<br />

## The Dashboard

Five zones, one screen, zero fluff.

```
┌─────────────────────────────────────────────────────────┐
│  COMMAND BRIEFING                                        │
│  Recovery 74 · HRV +0.6σ · Sleep 7.4h · TRAIN          │
├──────────────┬──────────────┬──────────────┬────────────┤
│  RECOVERY    │  SLEEP       │  LOAD        │  READINESS │
│  74 ████░░   │  7-night     │  ACWR 1.02   │  71 ██░░   │
│  HRV +0.6σ   │  stack bars  │  safe zone ✓ │  Δ+4 wk   │
├──────────────┴──────────────┴──────────────┴────────────┤
│  TREND INTELLIGENCE                                      │
│  Recovery · Training Heatmap · Body · Insights · Clinic │
├─────────────────────────────────────┬───────────────────┤
│  STRENGTH  heatmap · PRs · volume   │  RAIL  streaks    │
│                                     │        bests      │
└─────────────────────────────────────┴───────────────────┘
                                          ⌘K  AI ADVISOR
```

| Zone | Signal |
|:---|:---|
| **Command Briefing** | Recovery · HRV vs 28d avg · sleep · readiness verdict |
| **Four Pillars** | Recovery Intelligence · Sleep Architecture · Training Load · Readiness Composite |
| **Trend Intelligence** | 90-day recovery, heatmap, body metrics, correlation insights, clinical |
| **Right Rail** | Streaks · personal bests · week summary |
| **AI Advisor `⌘K`** | A coach that knows your HRV, your meds, and your last 12 weeks |

<br />

## Stack

```
Backend     Python 3.12 · FastAPI · DuckDB 1.1 (embedded, encrypted)
AI          Claude Sonnet 4.6 · Ollama fallback · APScheduler
Frontend    Next.js 15 · React 19 · TypeScript
UI          Tailwind CSS v4 · OKLCH · shadcn/ui · Recharts · TanStack Query v5
Secrets     macOS Keychain — nothing sensitive touches disk
```

<br />

## Quickstart

**Requires:** macOS · Python 3.12+ · Node 20+ · [`uv`](https://github.com/astral-sh/uv)

```bash
git clone <repo-url> savage-health-center
cd savage-health-center
make install && cp env.example .env
```

Three keys to fill in:

```bash
ANTHROPIC_API_KEY=        # Claude API — next-workout + daily briefings
WHOOP_CLIENT_ID=          # From your WHOOP developer portal
WHOOP_CLIENT_SECRET=
```

```bash
make seed   # populate with 90 days of synthetic data
make dev    # API :8000 · Web :3000
```

<br />

## Commands

```bash
make dev          # start everything via honcho
make seed         # 90d synthetic data
make reset        # nuke + reseed  (CONFIRM=1)
make doctor       # check config, DuckDB, Ollama
make logs         # tail all log files
make lint         # ruff check + format
make typecheck    # pyright
make test         # pytest
```

<br />

## How it works

```
WHOOP API ─────────────┐
Apple Health (iCloud) ─┼──► ingest ──► DuckDB (encrypted) ──► FastAPI ──► Next.js
Manual checkins ───────┘                       │
                                               └──► Claude Sonnet 4.6
                                                     ├── /api/workout/next
                                                     └── /api/briefing
```

Single encrypted DuckDB file. Migrations run at startup. No database server. No Docker.

<br />

### Computed metrics

Raw scores are noise. These are signals:

| Metric | Definition |
|:---|:---|
| **HRV deviation** | `(today − 28d avg) ÷ 28d SD` — standard deviations from your own baseline |
| **ACWR** | 7d avg ÷ 28d avg recovery — acute:chronic ratio, safe zone 0.8–1.3 |
| **Sleep consistency** | σ of sleep hours across 7 nights — low is good |
| **Readiness** | HRV 40% + Sleep 30% + RHR 20% + Subjective 10% |
| **Volume progression** | recent 8w vs prior 8w — are you actually overloading? |

<br />

### AI coaching

`/api/workout/next` sends Claude your readiness tier, 28d HRV trend, recent training volume, and active medications. Back comes a structured session: warmup → blocks with RPE targets → cooldown → clinical notes. Cached per day; `?regen=true` forces a fresh call.

`/api/briefing` does the same for your daily training call and readiness headline.

```bash
SHC_LLM_MODE=auto         # Claude API with Ollama fallback (default)
SHC_LLM_MODE=local_only   # air-gapped — never calls Anthropic
```

Every call is logged with token counts, cache hit/miss, and cost in USD. Daily spend is capped at `ANTHROPIC_DAILY_CAP_USD`.

<br />

## Data sources

| Source | Method | |
|:---|:---|:---|
| WHOOP | OAuth 2.0 → background sync | ✓ live |
| Apple Health | iCloud HealthAutoExport → CCDA XML | ✓ live |
| Manual checkin | `POST /api/checkin` | ✓ live |
| Fitbod | CSV import | — P2 |
| Hevy | REST API | — P2 |

<br />

## Configuration

```bash
# Storage
DATA_DIR=data

# Anthropic
ANTHROPIC_API_KEY=
ANTHROPIC_DAILY_CAP_USD=2.00

# WHOOP
WHOOP_CLIENT_ID=
WHOOP_CLIENT_SECRET=
WHOOP_REDIRECT_URI=http://127.0.0.1:8000/auth/whoop/callback

# LLM
SHC_LLM_MODE=auto
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=llama3.3:70b

# Server
HOST=127.0.0.1
PORT=8000
FRONTEND_ORIGIN=http://localhost:3000
```

> OAuth tokens, DB encryption key, and Hevy API key live in macOS Keychain — not here.

<br />

## Security

All data is local. No telemetry. Outbound calls: WHOOP sync, Claude API, Anthropic — nothing else. DuckDB is encrypted at rest (`shc auth set-db-key`). A session-token layer gates the dashboard against casual PHI exposure on shared machines.

<br />

---

<div align="center">

[API Reference](docs/API.md) · [Contributing](CONTRIBUTING.md) · [Changelog](CHANGELOG.md)

</div>
