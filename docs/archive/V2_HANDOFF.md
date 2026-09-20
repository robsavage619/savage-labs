# Savage Labs — V2 Dashboard Agent Handoff

## Full Project Plan

The complete architecture plan lives at:
`/Users/robsavage/.claude/plans/i-m-looking-to-build-groovy-parrot.md`

**Read this first.** It covers the full 6-phase roadmap, data model, stack decisions, LLM advisor architecture, security posture, clinical rule engine, and frontend design system. Everything below is additive to that plan — focused specifically on making v2 of the dashboard dramatically better than what P1 shipped.

The current codebase completed **P1** of that plan. You are picking up at **P2** and beyond, but your immediate priority is making the dashboard worthy of the product vision described in the plan before continuing with Hevy/Fitbod/advisor work.

---

## Who You Are / What You're Building

You are picking up a personal health intelligence platform called **Savage Labs**. The owner is Rob Savage — a serious lifter, WHOOP wearer, and senior software engineer who wants a premium, data-rich health OS that he could theoretically sell to the public. Rob's exact words: *"Imagine you were going to sell this to the public. Think anyone would buy this?"* — meaning v1 absolutely does not clear the bar.

Your job: build a dashboard that looks and feels like something between **Whoop.com**, **Levels**, and **Arc Browser** threw a party. Dense with insight, premium dark aesthetic, zero wasted space, every number tells a story.

---

## Current State (What Exists)

### Repo location
`/Users/robsavage/projects/savage-health-center/.claude/worktrees/nostalgic-hopper-6b62bd/`

### What's running
- **Backend**: FastAPI on `http://127.0.0.1:8000` — DuckDB, migrations, WHOOP OAuth scaffolding, APScheduler
- **Frontend**: Next.js 15 on `http://localhost:3000` — Geist font, OKLCH color tokens, TanStack Query

### What v1 shipped (the bare minimum)
- Recovery score ring (SVG arc, animated)
- HRV 28-day trend with ±1 SD band
- Sleep 7-night stacked stage bars
- Sync status banner
- Placeholder cards: "Workout history — coming in P2" and "AI advisor — coming in P3"

### Why it's not good enough
It looks like a loading skeleton that never filled in. Three cards. No story. No insight. No density. A fitness app from 2018 had more. Rob needs to *feel* the data.

---

## The V2 Vision

Think: **what would a world-class coach see when they look at your last 30 days?** Surface that. Every card should answer a question Rob didn't even know to ask.

### Design Philosophy
- **Dark premium**: background `oklch(0.10 0 0)`, cards `oklch(0.15 0 0)`, hairline borders `oklch(1 0 0 / 0.07)`
- **Data density without clutter**: small numbers, meaningful hierarchy, no decorative chrome
- **Every metric earns its space**: if it doesn't change behavior, cut it
- **Micro-interactions**: hover reveals context, click drills down, numbers animate on load
- **Color language**: green = above baseline, amber = at baseline, red = below — consistent everywhere
- **Typography**: Geist + Geist Mono, tabular-nums on all metrics, `font-feature-settings: "ss01" "tnum"`, max weight 500 on large numbers

---

## What V2 Must Contain

### Zone 1 — The Command Briefing (top of page, full width)
A single "today" strip that Rob reads in 3 seconds:

```
TODAY  |  Recovery 82 ↑  |  HRV 71.9ms (+6% vs baseline)  |  RHR 57  |  Sleep 6.8h  |  Readiness: TRAIN HARD
```

With a subtle gradient bar showing where each metric sits on its personal range. Not a score — a *verdict with evidence*.

### Zone 2 — The Four Pillars (2×2 grid, primary cards)

**1. Recovery Intelligence**
- Recovery score with 14-day sparkline + 7-day trend arrow
- HRV: today vs 28d avg vs personal best, deviation in SD units ("+0.7σ above baseline")
- RHR: today + 7d trend + contextual note ("elevated 3rd day in a row — watch load")
- Skin temp delta (when WHOOP provides it)
- "What's driving this" — ranked contributing factors pulled from the data

**2. Sleep Architecture**
- 7-night stacked horizontal bars (existing — but make them *beautiful*)
- Summary row: avg deep %, avg REM %, avg total
- SpO2 trend if available
- Sleep consistency score (variance in bedtime/wake time — WHOOP studies show this matters as much as duration)
- "Best night this week" callout + what made it different

**3. Training Load & Strain**
- Acute:Chronic Workload Ratio (ACWR) — 7-day vs 28-day rolling load
  - Green zone: 0.8–1.3 (optimal adaptation)
  - Amber: 1.3–1.5 (caution, overreach risk)
  - Red: >1.5 or <0.8 (undertraining or injury risk)
- Weekly strain sparkline (14 weeks)
- Today's WHOOP strain gauge
- Zone distribution pie/donut (Z1/Z2/Z3/Z4/Z5) when available
- Days since last rest day

**4. Readiness Score (composite)**
- A Rob-specific composite: weight HRV (40%) + Sleep (30%) + RHR (20%) + Subjective checkin (10%)
- Trend over 14 days
- "This week vs last week" delta
- Next 3 days projection based on trend (if slope is negative: "load may need to drop")

---

### Zone 3 — Trend Intelligence (below the fold, tabs)

**Recovery Tab**
- 90-day recovery score with annotated deload zones
- HRV with 28d rolling avg ± 1 SD band (existing — keep, make bigger)
- Personal HRV baseline card: "Your HRV baseline is 64.6ms. Top 15% for your age range."
- Monthly average table: Month | Avg HRV | Avg Recovery | Avg Sleep

**Training Tab** (P2 data — scaffold the UI, show "connect WHOOP / Hevy to populate")
- Volume load per week (sets × reps × weight) — bar chart
- Intensity distribution by muscle group
- Personal records table: Exercise | PR | Date | Delta vs 90d ago
- Consistency heatmap (GitHub-style, 52 weeks, color = training load)
- Last 7 workouts list with strain, duration, muscle groups

**Body Metrics Tab** (scaffold for Apple Health data)
- Weight trend (30/90/180d toggle)
- Body fat % if available
- Resting metabolic markers

**Insights Tab** — the "why" layer
- Correlation cards (auto-computed from DB):
  - "When you sleep >7.5h, next-day HRV averages +8.2ms"
  - "Your Sunday recovery consistently underperforms Monday (+12 pts drop)"
  - "HRV drops an avg of 9ms within 48h of high-strain days (>14 WHOOP strain)"
- These should feel like a coach's observations, not analytics jargon

---

### Zone 4 — Quick-Access Right Rail (when viewport > 1400px) or Bottom Strip

- **Streak tracker**: consecutive days with recovery >60, sleep >7h, trained ≥ scheduled days
- **Personal bests**: top 5 HRV days (date + context), lowest RHR ever
- **7-day summary card**: Mon–Sun color-coded blocks (recovery color + emoji for training)
- **Goals progress** (manual input, no external API needed): e.g., "Avg HRV >70ms for 30 days" — progress bar

---

### Zone 5 — AI Advisor Chat (P3 — but wire the UI shell now)
Docked right-side Sheet, 420px, Cmd+K, streaming responses. Just the UI shell — no LLM calls yet.
Quick-action buttons in header: Build Programme · Swap Exercise · Deload Week · Plateau Buster · Session Check-in

---

## Data Available Right Now (Seeded / API)

Rob will provide sample data. Until then, the DB has 90 days of synthetic WHOOP recovery + sleep.

**API endpoints live:**
- `GET /api/recovery/today` → `{date, score, hrv, rhr, skin_temp}`
- `GET /api/recovery/trend?days=N` → array of `{date, score, hrv, rhr}`
- `GET /api/hrv/trend?days=N` → array of `{date, hrv, avg, sd}` from `v_hrv_baseline_28d`
- `GET /api/sleep/recent?days=N` → array of `{date, stages, spo2, rhr}`
- `GET /api/readiness/today` → `{date, recovery_score, hrv, rhr, sleep_hours, energy, stress}`
- `GET /api/oauth/status` → array of `{source, last_sync_at, needs_reauth}`

**What you can compute client-side from existing data:**
- ACWR: sum last 7 days recovery scores / sum last 28 days (normalized) — rough but useful
- HRV deviation in σ: `(today - avg) / sd` — already in the trend endpoint
- Sleep consistency score: stddev of sleep_hours across last 7 nights
- Recovery trend direction: linear regression slope on last 7 days scores

**What needs new backend endpoints (add them):**
- `GET /api/recovery/trend?days=90` — already works, just use larger window
- `GET /api/stats/summary` → computed stats: acwr, hrv_deviation_sigma, sleep_consistency, streaks
- `GET /api/sleep/trend?days=90` — extend the sleep endpoint

---

## Stack Constraints (Non-Negotiable)

- **Python 3.12**, `uv`, `ruff`, `pyright`, `src/shc/` layout
- `from __future__ import annotations` at top of every Python file
- **Next.js 15** + **shadcn/ui** + **Recharts** (via shadcn charts) + **Motion** (not Framer Motion)
- **OKLCH** color tokens in `globals.css` — extend the existing token set
- **TanStack Query** for all data fetching — already wired
- No Tremor, no Chart.js, no D3 unless you need a custom SVG
- Conventional commits: `feat:` `fix:` `chore:` etc.
- No comments unless the WHY is non-obvious

---

## Files You'll Touch Most

```
frontend/
  app/page.tsx                    ← main layout, rebuild this
  app/globals.css                 ← add OKLCH tokens as needed
  components/hero-recovery.tsx    ← the recovery ring, enhance
  components/hrv-chart.tsx        ← existing, good bones
  components/sleep-card.tsx       ← existing, needs visual polish
  components/sync-status.tsx      ← existing, keep
  lib/api.ts                      ← add new fetch methods here

backend/
  src/shc/api/routers/dashboard.py  ← add new computed endpoints
  src/shc/db/migrations/            ← add 0003+ if new tables needed
```

---

## What "Done" Looks Like

A visitor who has never heard of Savage Labs opens the dashboard and within 10 seconds:
1. Knows exactly how Rob's body is doing today
2. Can see a clear trend story over the last month
3. Understands the *relationship* between sleep, recovery, and training
4. Wants to use this product themselves

That's the bar. Don't ship until it clears it.

---

## Rob's Working Style

- Terse responses — no trailing summaries, no "here's what I did"
- No unsolicited refactors — stay in scope
- Show output, not plans
- No comments in code unless truly non-obvious
- `from __future__ import annotations` in every Python file
- f-strings only, never `.format()` or `%`
- No bare `except:` — catch specific exceptions
