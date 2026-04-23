# API Reference

Base URL: `http://127.0.0.1:8000`

All dashboard endpoints return JSON. Errors follow FastAPI's default `{"detail": "..."}` shape.

---

## Health

### `GET /healthz`

Liveness check. Returns `{"status": "ok"}` immediately.

### `GET /readyz`

Readiness check. Verifies DuckDB is reachable and migrations are applied.

```json
{"status": "ok", "db": "connected"}
```

---

## Auth

### `GET /auth/whoop`

Redirects to WHOOP OAuth authorization URL.

### `GET /auth/whoop/callback`

OAuth callback. Exchanges code for tokens, stores them in Keychain, and redirects to the dashboard.

### `GET /api/oauth/status`

```json
{
  "whoop": {
    "connected": true,
    "last_sync": "2026-04-22T19:30:00Z",
    "needs_reauth": false
  }
}
```

---

## Recovery

### `GET /api/recovery/today`

Today's recovery snapshot from WHOOP.

```json
{
  "date": "2026-04-22",
  "score": 74,
  "hrv_ms": 68.4,
  "rhr_bpm": 52,
  "skin_temp_celsius": 36.1
}
```

Returns `null` fields if today's data hasn't synced yet.

### `GET /api/recovery/trend`

**Query params:** `days` (int, default 14)

Array of daily recovery scores, oldest-first.

```json
[
  {"date": "2026-04-09", "score": 81, "hrv_ms": 72.1, "rhr_bpm": 50},
  ...
]
```

---

## HRV

### `GET /api/hrv/trend`

**Query params:** `days` (int, default 28)

HRV trend with 28-day rolling average and ±1 SD band.

```json
{
  "values": [
    {"date": "2026-04-09", "hrv_ms": 72.1}
  ],
  "avg_28d": 66.8,
  "sd_28d": 8.2,
  "deviation_sigma": 0.63
}
```

`deviation_sigma` = `(today − avg_28d) / sd_28d`.

---

## Sleep

### `GET /api/sleep/recent`

**Query params:** `days` (int, default 7)

```json
[
  {
    "night_date": "2026-04-21",
    "total_hours": 7.4,
    "deep_hours": 1.2,
    "rem_hours": 1.8,
    "light_hours": 3.9,
    "awake_hours": 0.5,
    "spo2_avg": 96.2,
    "rhr_bpm": 51,
    "hrv_ms": 70.1
  }
]
```

---

## Readiness

### `GET /api/readiness/today`

Composite readiness score (HRV 40% + sleep 30% + RHR 20% + subjective 10%).

```json
{
  "date": "2026-04-22",
  "score": 71,
  "tier": "green",
  "components": {
    "hrv": 0.78,
    "sleep": 0.65,
    "rhr": 0.72,
    "subjective": null
  },
  "delta_7d": 4
}
```

`tier` is `"green"` (≥70), `"yellow"` (50–69), or `"red"` (<50).

---

## Stats summary

### `GET /api/stats/summary`

Aggregated metrics used by the Command Briefing strip.

```json
{
  "acwr": 1.02,
  "hrv_deviation_sigma": 0.63,
  "sleep_consistency_score": 0.81,
  "recovery_streak_days": 5,
  "sleep_streak_days": 3,
  "pr_count_30d": 4
}
```

`acwr` = 7d avg recovery / 28d avg recovery. Safe zone 0.8–1.3.

---

## Insights

### `GET /api/insights`

Coach-style insight cards derived from 90-day correlation analysis.

```json
[
  {
    "title": "Sleep drives HRV",
    "body": "On nights with >7.5h sleep your next-day HRV averages 12% higher.",
    "correlation": 0.74,
    "confidence": "high"
  }
]
```

---

## Training

### `GET /api/training/heatmap`

**Query params:** `weeks` (int, default 52)

GitHub-style activity heatmap. Each cell is one calendar day.

```json
[
  {"date": "2026-04-21", "session_count": 1, "total_sets": 32, "volume_kg": 4180}
]
```

### `GET /api/training/weekly`

**Query params:** `weeks` (int, default 16)

Weekly rollup for bar charts.

```json
[
  {
    "week_start": "2026-04-14",
    "session_count": 4,
    "total_sets": 128,
    "volume_kg": 16200
  }
]
```

### `GET /api/training/prs`

Personal records by exercise, sorted by date descending.

```json
[
  {
    "exercise": "Squat",
    "weight_kg": 140,
    "reps": 3,
    "estimated_1rm_kg": 156,
    "date": "2026-04-18"
  }
]
```

### `GET /api/training/overload-signal`

Progressive overload analysis comparing the most recent 8 weeks to the prior 8.

```json
{
  "volume_progression_pct": 8.2,
  "trend": "progressing",
  "recommendation": "On track — continue adding load at current rate."
}
```

`trend` is `"progressing"`, `"maintaining"`, or `"deloading"`.

---

## Workout

### `GET /api/workout/next`

**Query params:** `regen` (bool, default `false`)

AI-generated next session. Cached per day unless `regen=true`.

```json
{
  "readiness_tier": "green",
  "generated_at": "2026-04-22T18:00:00Z",
  "cached": true,
  "plan": {
    "warmup": ["5 min row", "Hip 90/90 x 8 each"],
    "blocks": [
      {
        "name": "Primary",
        "exercises": [
          {
            "name": "Squat",
            "sets": 4,
            "reps": "5",
            "rpe_target": 8,
            "notes": "Work up from last session +2.5kg"
          }
        ]
      }
    ],
    "cooldown": ["10 min walk", "Quad stretch 60s each"],
    "clinical_notes": "Beta blocker will suppress HR response — use RPE not HR zones."
  }
}
```

### `POST /api/checkin`

Submit daily subjective scores.

**Body:**

```json
{
  "date": "2026-04-22",
  "energy": 7,
  "stress": 4,
  "motivation": 8,
  "soreness": 3
}
```

All fields 1–10. Returns `{"ok": true}`.

---

## Personal bests

### `GET /api/personal-bests`

All-time highs and lows for key metrics.

```json
{
  "hrv_peak": {"value": 98.2, "date": "2026-02-14"},
  "rhr_low": {"value": 46, "date": "2026-03-01"},
  "sleep_longest": {"value": 9.2, "date": "2026-01-08"}
}
```

---

## Week summary

### `GET /api/week/summary`

Current week (Mon–Sun) recovery and sleep by day.

```json
[
  {"date": "2026-04-21", "recovery_score": 74, "sleep_hours": 7.4},
  {"date": "2026-04-22", "recovery_score": null, "sleep_hours": null}
]
```

Null for days that haven't happened yet or haven't synced.

---

## Body

### `GET /api/body/trend`

**Query params:** `days` (int, default 90)

Body mass trend from Apple Health measurements.

```json
[
  {"date": "2026-04-21", "weight_kg": 84.2}
]
```

---

## Clinical

### `GET /api/clinical/overview`

Current medications, conditions, and most recent key labs.

```json
{
  "medications": [
    {
      "name": "Metoprolol",
      "dose": "25mg",
      "frequency": "daily",
      "notes": "Beta blocker — suppresses HR response, affects WHOOP strain accuracy"
    }
  ],
  "conditions": [
    {"name": "Hypertension", "status": "managed", "since": "2023-01-01"}
  ],
  "labs": [
    {
      "name": "HbA1c",
      "value": 5.4,
      "unit": "%",
      "date": "2026-03-15",
      "reference_range": "<5.7"
    }
  ]
}
```

---

## Briefing

### `GET /api/briefing`

Latest AI-generated daily briefing (cached per calendar day).

```json
{
  "date": "2026-04-22",
  "training_call": "Moderate day — recovery is solid but sleep debt from the weekend remains. Prioritise quality over volume.",
  "readiness_headline": "74 — Good to train",
  "flags": ["HRV slightly below 28d avg", "3 consecutive training days"],
  "coaching_notes": "Consider a deload if fatigue flags persist past Wednesday."
}
```

---

## Chat

### `POST /api/chat`

Streaming AI advisor. Request body:

```json
{"message": "Should I train today?"}
```

Returns a Server-Sent Events stream. Each event:

```
data: {"delta": "Based on your recovery score of 74..."}
```

Final event:

```
data: {"done": true}
```

---

## LLM observability

### `GET /api/llm/stats`

Aggregated LLM usage for the current day and month.

```json
{
  "today": {
    "calls": 3,
    "input_tokens": 4200,
    "output_tokens": 820,
    "cache_read_tokens": 3100,
    "cost_usd": 0.12
  },
  "month": {
    "cost_usd": 1.84,
    "cap_usd": 2.00
  }
}
```
