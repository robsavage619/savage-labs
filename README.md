<div align="center">

<img src="images/banner.png" width="100%" />

<br />

**Lab thinking, consumer sensors, daily action.**

<sub>Wearable physiology, training logs, subjective context, progress photos, sport outcomes, research priors, and deterministic gates, fused into one decision, every morning.</sub>

<br />

<table>
<tr>
<td>

[![Python](https://img.shields.io/badge/Python-3.12-1e1e2e?style=for-the-badge&logo=python&logoColor=cba6f7&labelColor=1e1e2e&color=cba6f7)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-1e1e2e?style=for-the-badge&logo=fastapi&logoColor=a6e3a1&labelColor=1e1e2e&color=a6e3a1)](https://fastapi.tiangolo.com/)
[![DuckDB](https://img.shields.io/badge/DuckDB-1.1-1e1e2e?style=for-the-badge&logo=duckdb&logoColor=fab387&labelColor=1e1e2e&color=fab387)](https://duckdb.org/)

</td>
<td>

[![Next.js](https://img.shields.io/badge/Next.js-15-1e1e2e?style=for-the-badge&logo=next.js&logoColor=89b4fa&labelColor=1e1e2e&color=89b4fa)](https://nextjs.org/)
[![React](https://img.shields.io/badge/React-19-1e1e2e?style=for-the-badge&logo=react&logoColor=74c7ec&labelColor=1e1e2e&color=74c7ec)](https://react.dev/)
[![TypeScript](https://img.shields.io/badge/TypeScript-5-1e1e2e?style=for-the-badge&logo=typescript&logoColor=89dceb&labelColor=1e1e2e&color=89dceb)](https://www.typescriptlang.org/)

</td>
<td>

[![Claude](https://img.shields.io/badge/Claude-Opus_4.8-1e1e2e?style=for-the-badge&logo=anthropic&logoColor=f5c2e7&labelColor=1e1e2e&color=f5c2e7)](https://anthropic.com/)
[![Obsidian](https://img.shields.io/badge/Obsidian-RAG-1e1e2e?style=for-the-badge&logo=obsidian&logoColor=cba6f7&labelColor=1e1e2e&color=cba6f7)](https://obsidian.md/)
[![License](https://img.shields.io/badge/License-MIT-1e1e2e?style=for-the-badge&labelColor=1e1e2e&color=a6e3a1)](LICENSE)

</td>
</tr>
</table>

<br />

</div>

---

## What This Is

Savage Labs fuses wearable physiology, training logs, blood work, subjective
check-ins, and a hand-curated research corpus into one decision every morning:
train or do not, how hard, and on what. It runs entirely on one machine, for one
person. Nothing leaves the laptop.

The interesting part is not the dashboard. It is that a language model writes the
training plan and a deterministic layer is allowed to reject it.

---

## The Constraints That Forced the Design

Every design choice below follows from one of these. None of them are
preferences.

**One subject, forever.** There is no cohort and never will be. A population
threshold answers "where does he sit among people?" when the only question that
matters is "did this move?" So the system carries its own noise floor, derived
from the subject's own baseline SD, and bands every metric against that instead
of against published norms. It also means n is small and permanently small,
which is why results get reported with intervals and why an underpowered null
is published rather than buried.

**The output can hurt someone.** A bad recommendation is a torn hamstring or a
missed cardiac signal, not a bad movie night. So the model never has final say.
It reasons, drafts, and explains. A separate layer checks the draft against hard
gates and rejects it outright, without negotiating. Gates are deterministic code
with tests, not prompt instructions, because a prompt instruction is a
suggestion to a system that is optimizing for looking helpful.

**The sensors are consumer-grade and confounded.** A beta-blocker taken as
needed suppresses heart rate, which makes the wearable's recovery score
meaningless on exactly the days it matters most. Year-round allergies inflate
skin temperature and respiratory rate. So raw vendor scores are never displayed
or trusted. Everything is recomputed from the underlying signals with the known
confounds modelled explicitly.

**Two apps hold overlapping copies of a decade of training.** History was
imported across a migration, so the same session exists twice under different
names. Deduplication is therefore a first-class data-model concern rather than a
cleanup script, and identity has to be derived from behaviour rather than from
string similarity.

**One hour, four days a week.** Volume prescriptions have to fit a real budget.
The planner publishes its weekly set capacity against demand instead of silently
dropping whatever does not fit.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         DATA SOURCES                            │
│  WHOOP OAuth  │  Apple Health XML  │  Hevy API  │  Check-in    │
│                      DUPR api.dupr.gg                           │
└───────┬───────┴────────┬───────────┴──────┬─────┴──────┬───────┘
        │                │                  │            │
        ▼                ▼                  ▼            ▼
┌─────────────────────────────────────────────────────────────────┐
│                    INGESTION LAYER                              │
│   OAuth token refresh  │  CCDA/lxml XML parse  │  REST client  │
│   APScheduler jobs     │  Content-hash dedup   │  Pydantic DTOs│
└───────────────────────────────┬─────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                       DuckDB (encrypted)                        │
│  measurements  │  workouts  │  workout_sets  │  sleep           │
│  recovery      │  cardio    │  daily_checkin │  medications     │
│  conditions    │  labs      │  daily_cycle    │  workout_plans  │
│  mesocycles    │  muscle_volume_targets       │  lab_questions  │
│  lab_findings  │  workout_retrospectives      │  working_weights│
│  dupr_snapshots│  dupr_matches                │  oauth_state    │
│                                                                 │
│  Views: v_hrv_baseline_28d, v_session_load, v_daily_load        │
└───────────────────────────────┬─────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                      METRICS ENGINE                             │
│                  compute_daily_state()                          │
│                                                                 │
│  HRV σ-deviation  │  True ACWR  │  Sleep composite              │
│  Readiness score  │  Gates      │  Epley e1RM                   │
│  Push:pull ratio  │  Zone calc  │  Regression detection         │
│  Sleep arch.      │  Banister CTL/ATL/TSB │ Mesocycle phase     │
│  After-action     │  Fueling balance      │ Allostatic load     │
│  SRI · lnRMSSD    │  Drug-adjusted HRV    │ N-of-1 lab runners  │
│  RR sentinel      │  WHOOP-measured HRmax │ Pickleball volume   │
│  Concurrent-load signal       │  Percent-recorded filter        │
└──────────┬────────────────────────────────┬─────────────────────┘
           │                                │
           ▼                                ▼
┌──────────────────────┐      ┌─────────────────────────────────┐
│    FastAPI REST       │      │         AI LAYER                │
│    124 endpoints      │      │                                 │
│                       │      │  build_daily_context()          │
│  /api/state/today     │      │  build_training_context()       │
│  /api/daily/brief     │      │  build_clinical_context()       │
│  /api/workout/*       │      │  load_vault_research()          │
│  /api/training/*      ├──────┤                                 │
│  /api/training/load-curve    │  Claude Opus 4.8                │
│  /api/training/after-action  │  -> validate_plan()             │
│  /api/training/mesocycle     │  -> Ollama fallback (air-gapped)│
│  /api/clinical-research/*                                      │
│  /api/lab/{questions,findings,run}                             │
│  /api/fueling/{today,trend}                                    │
│  /api/chat · /api/briefing · /api/insights                     │
│  /api/hevy/push · /api/vault/search                            │
└──────────┬────────────┘      └─────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Next.js 15 + React 19                        │
│                                                                 │
│  TanStack Query v5  │  Recharts  │  Tailwind v4 (OKLCH)        │
│  shadcn/ui          │  Motion    │  Orbitron + Geist fonts      │
│                                                                 │
│  NOW  /         today's call · session · check-in               │
│  REVIEW /review momentum · signals · training + body history    │
│  LAB  /lab      dossier · studies · engine self-assessment      │
│                                                                 │
│  Command Briefing  │  Four Pillars  │  Trend Intelligence       │
│  Workout Planner   │  AI Advisor    │  Clinical Overview        │
│  Periodization Strip · After-Action · Fueling Panel             │
│  Clinical Research Signals · Research Lab (N-of-1)              │
└─────────────────────────────────────────────────────────────────┘
```

---

---

## Five Problems Worth Reading About

**A language model that cannot overrule the safety layer.**
Claude drafts the session. `validate_plan()` checks it against schema and
against today's gates: intensity cap, forbidden muscle groups, per-exercise
e1RM ceiling, rep windows, RPE coherence. A plan that trains legs 30 hours after
the last leg session is rejected and regenerated, not adjusted and not warned
about. The model is for reasoning. Correctness is not delegated to it.
[Details](docs/ai-integration.md)

**The engine grades itself, and the result is split.**
Prescription calibration is good: +0.03 RPE bias over 234 matched prescriptions,
86% landing within 0.5 of target. Predictive validity is a null: readiness
versus the session that follows is r = -0.07 on volume-load, every interval
spanning zero at n = 54. Both numbers are published, because either one alone
tells the wrong story. The weights were not changed on the strength of an
underpowered result. [Details](docs/evaluation.md)

**27% of the training history was the same sessions logged twice.**
Two apps, one imported from the other, the same set recorded as `61.235` and
`61.23497000135107` under two different exercise names. An exact-match join
finds zero duplicates; rounding to 0.1 kg first finds twelve thousand. The
deduplication view was catching 1 of 17 real twin pairs. Live decision windows
were never affected, which was verified rather than assumed, but the 104-week
landmark fit was inflated by up to 57% per muscle. Fixed with a normalized
canonical key plus an evidence-derived twin table, where every pairing comes
from two names appearing on the same day with an identical set sequence.
[Details](docs/engine.md)

**A missing OAuth parameter that read as "the vendor logs me out daily."**
The token endpoint requires a `scope` parameter to return a replacement refresh
token. Without it, every refresh spent the current token and received nothing to
replace it, so the connection worked for exactly one access-token lifetime and
then died permanently. Deterministic, not a race, which is why an earlier
shutdown fix narrowed the window without closing it. The rotation hand-off is
now ordered so the irreplaceable half is stored first.
[Details](docs/engine.md)

**Auditing the seams instead of the algorithms.**
The expensive failures here have never been wrong formulas. They are two
internally consistent components that disagree at the boundary, where nothing
throws. Exercise selection ranked and rotated correctly, then emitted a name the
logging app has never heard of, so the swap silently did nothing for months. A
research panel showed six tiles, two of which had never once rendered a value
because a bare `except Exception` was swallowing a wrong column name.

---

## How It Is Verified

| Layer | What it covers |
|---|---|
| [`ENGINE_INVARIANTS.md`](ENGINE_INVARIANTS.md) | The athlete-protection contract, 43 tests behind it |
| `validate_plan()` | Schema plus deterministic gates, rejects rather than adjusts |
| Migrations | 102 of them, with view and data-integrity tests on the ones that change semantics |
| Suite | 1,030 tests, 14,120 test lines against 33,295 lines of source |
| Self-evaluation | Calibration and predictive validity, measured and published |

---

## Known Limitations

The honest state of the system. Full list in [docs/evaluation.md](docs/evaluation.md).

- **Readiness has no demonstrated predictive validity** at n = 54, and still
  gates training. This is the weakest load-bearing assumption in the engine.
- **HRV is corrupted here** by a beta-blocker taken as needed, and carries 0.40
  of the readiness composite.
- **Two e1RM sources disagree** for the same lift, cause not yet understood.
- **The deload trigger is not personalized** and can still return population
  defaults that look like fitted values.
- **Residual ledger duplication is 6.2%**, concentrated in pre-2021 history
  below the threshold for automatic pairing.

---

## Documentation

| Document | What is in it |
|---|---|
| [docs/evaluation.md](docs/evaluation.md) | Does it work? Calibration, the null, the noise floor, n-of-1 studies, limitations |
| [docs/engine.md](docs/engine.md) | Metrics, gates, readiness, ACWR, volume model, exercise intelligence |
| [docs/sports-science.md](docs/sports-science.md) | Sleep architecture, periodization, fueling, clinical signals, the research lab |
| [docs/ai-integration.md](docs/ai-integration.md) | Context assembly, plan generation, running without a model |
| [docs/interface.md](docs/interface.md) | The board, what each surface shows, design system |
| [docs/vault.md](docs/vault.md) | The curated research corpus and how it reaches the planner |
| [docs/API.md](docs/API.md) | Endpoint reference |
| [ENGINE_INVARIANTS.md](ENGINE_INVARIANTS.md) | The rules the engine may not break |
| [DECISIONS.md](DECISIONS.md) | Architecture decision log |
| [CHANGELOG.md](CHANGELOG.md) | What changed, what broke, and what I got wrong |

---

## Stack

Python 3.12, FastAPI, DuckDB, APScheduler, Pydantic. Next.js 15, React 19,
TypeScript, Tailwind, Recharts. Claude for plan drafting and narrative. Obsidian
as the research corpus. `uv` for packaging, `ruff` for lint and format, `pyright`
for types, `pytest` for the suite.

## Data Sources

WHOOP (public OAuth API plus the private iOS API for signals the public one does
not expose), Apple Health XML export, Hevy for strength logging, DUPR for
pickleball rating and match history, blood work from a YAML clinical profile, and
a daily subjective check-in.

## Privacy

Everything runs locally against a DuckDB file on one machine. No cloud database,
no analytics, no telemetry. `backend/data` is gitignored because this repository
is public, and test fixtures are synthetic by construction rather than scrubbed
after the fact.

## Running It

```bash
./dev-restart.sh          # API on :8000, frontend on :3000
```

Migrations apply on API start. Without an API key for the model the system still
computes every metric, gate and prescription; only the narrative and plan
drafting are unavailable.
