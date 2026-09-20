# AI Integration

*How context is built, how plans are generated, and what happens without a model.*

[<- back to README](../README.md)

---

## AI Integration

### Slim Daily Brief Endpoint

`GET /api/daily/brief` returns a single 24KB payload that replaces the previous multi-endpoint context-building pattern (which required fetching ~293KB across 6+ endpoints). The brief combines:

- Full `DailyState` DTO (all computed metrics)
- 5 signal-ranked vault notes × 800 chars each
- Last 7 days of training sessions
- Top 20 working weights
- Complete Hevy exercise catalog
- Mesocycle + ACWR + muscle-group rest status

This endpoint is what the `shc-workout` Claude Code skill uses. Context is fetched once, in one shot, in ~500ms rather than 6+ minutes.

---

### How Context Gets Built

Every time Claude gets called, `build_daily_context()` assembles:

- Today's full DailyState (all computed metrics)
- 28-day cardio composition (Zone 2 vs threshold vs VO₂max minutes)
- Push:pull imbalance direction and magnitude
- Skin-temp delta from my 28-day baseline
- Active medications with dosing and onset dates
- Active diagnoses
- 20 most recent lab values with reference ranges
- Recent PRs, volume trend, last session per muscle group
- Active gate reasons
- Signal-ranked vault research

`build_clinical_context()` structures the clinical data into a dedicated block that appears early in the system prompt. The HEALTH_SYSTEM prompt encodes drug-class interpretation rules so Claude doesn't have to infer pharmacology from first principles.

### Workout Generation Flow

```
SYSTEM: HEALTH_SYSTEM + gate enforcement rules + personal context
USER:   build_training_context()
        → readiness tier + score
        → HRV σ, sleep quality, ACWR
        → volume push/pull/legs 28d
        → last session per muscle group (hours ago)
        → gates (max_intensity, forbid_muscle_groups, zone shifts)
        → signal-ranked vault research (top 4 notes)
        → pinned exercise science foundation (6 notes always)
        → session goals
```

Plan comes back as JSON, gets validated against gates, cached for 24h. `?regen=true` forces a fresh call.

### Running Locally Without Claude

`SHC_LLM_MODE=local_only` routes everything to a local Ollama instance (`llama3.3:70b`). Same context injection, lower reasoning quality, works fully offline. I use this when I'm traveling.

---

