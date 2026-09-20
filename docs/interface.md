# The Interface

*What the board shows and why it is laid out this way.*

[<- back to README](../README.md)

---

## The Dashboard

What I actually look at every day. Built with Next.js 15 + React 19.

**Three surfaces, one per moment of use.** This started as one long page organised by data domain, recovery, sleep, load, strength, cardio, body. That's a schema, not a sequence. I use this at four distinct moments (phone at 6am, phone mid-workout, post-session logging, desktop on Sunday), and each one needs a different 5% of the page. A single 10,500px dashboard served the rarest of them best.

| Route | Question it answers | What's on it |
|---|---|---|
| **NOW** `/` | *What am I doing today?* | Today's command, the session (exercises first), the check-in. Phone-first, capped at ~2 screens. |
| **REVIEW** `/review` | *Am I progressing?* | Momentum vs last week, the three signal pillars, then training and body history as drill-downs. |
| **LAB** `/lab` | *How much should I trust this thing?* | Subject dossier, n-of-1 studies, the standing research program, engine self-assessment. |

<table>
<tr>
<td width="50%">

**⚡ Athlete OS Panel**. NOW
The top card. Fuses today's readiness verdict (engine-gate-aware, not client-side), goal pressure (push:pull ratio, court load), active experiment status, and personal lab findings into four decision cells. One read, one decision.

**🧠 Command Briefing**. NOW
Claude's written assessment of the day, recovery, training intent, and what to watch. Sits below the OS Panel.

**📡 Biometric HUD**, all routes
Persistent header with today's vitals and data freshness. This is the **only** place the composite readiness score is printed, every other panel refers to the verdict by name, and WHOOP's own recovery score is always labelled as WHOOP's. Six near-identical numbers under five different labels is how a system starts looking like it disagrees with itself.

**🫀 WHOOP Recovery**. REVIEW
WHOOP's recovery ring plus a 14-day sparkline with the 34/67 bands drawn in. Points outside the band are colored, easy to spot anomalous nights at a glance.

**😴 Sleep Architecture**. REVIEW
7-night stacked bar (total / deep / REM), sleep debt accumulator, SpO2. Tiles that are single-night rather than 7-night aggregates are marked `1n`, because a wakes count of 14 reads very differently as a week's total than as one bad night.

</td>
<td width="50%">

**🏋️ Training Load**. REVIEW
ACWR trend with the safe-zone band drawn in, weekly volume by muscle group, push:pull ratio. I built this after noticing I was chronically over-pushing and under-pulling.

**📈 Momentum**. REVIEW
Recovery, sleep and session count against the previous 7 days. *What changed since I last looked* is the question a longitudinal tool exists to answer, so it opens the page.

**💬 AI Advisor** `⌘K`
Claude chat, but it already knows everything before I type anything. Every message includes today's full DailyState, medications, labs, training history, and gate state.

**🌊 Ambient Layer**
The page background hue shifts with readiness, greenish when I'm good, reddish when I'm not. It's subtle but I notice it before I read anything.

</td>
</tr>
</table>

### 2026 Goal Scorecard

Three north-star metrics tracked on a dedicated section between Signals and Training:

| Track | What it shows |
|---|---|
| **DUPR doubles** | Current rating (glowing 32px Orbitron), gap to 5.0 target, gradient progress bar, DUPR sparkline with target reference line, latest tournament context card (W/L · DUPR arc · WHOOP recovery) |
| **Key compound e1RM** | Top-5 key lifts (squat, bench, deadlift, press, row, pull) with latest e1RM in lbs and 8-week trend (↑ climbing / -> holding / ↓ declining), color-coded left border per trend |
| **Body weight** | Current weight in lbs, 4-week trend in lbs/wk, plain-language concurrent-training interpretation (stable / gaining / losing) |

### The Sports-Science Strip

Six newer panels stack between the daily-readiness row and the legacy Strength / Cardio panels:

| Panel | What it shows |
|---|---|
| **Periodization** | Mesocycle phase strip (W-of-N, deload-week amber) + PMC chart (CTL/ATL/TSB over 180d with zone bands) |
| **After-Action** | Per-exercise Hevy-driven autoreg: actuals vs plan, next-session weight suggestion, verdict tint |
| **Clinical Research Signals** | Six peer-reviewed tiles. SRI, lnRMSSD, red-streak, allostatic load, drug-adjusted HRV, Z2 drift, with plain-language meaning and range scale |
| **Fueling** | Body comp strip (weight / BF% / lean mass) + macros (kcal in/out/balance, protein g/kg, hydration) + 14d energy-balance bar chart |
| **Research Lab** | Six active pre-registered hypothesis cards (CONFIRMED / REFUTED / INCONCLUSIVE / INSUFFICIENT) + automatic rotation from an 8-question queued bank; verdicts injected into every AI call |

### Trend Intelligence

Six tabs I open when I want to dig into something:

| Tab | What's in it |
|---|---|
| **Recovery** | 90-day HRV with 7d EWMA + ±0.5σ guidance band, recovery score, RHR with 28d moving average, pre-illness alarm strip |
| **Body** | Weight trend, 4-week regression line, Apple Health sync |
| **Patterns** | Sleep vs recovery and HRV vs readiness scatter plots. Pearson-r per plot |
| **Insights** | Computed correlation cards, unlocks after 7 days of data |
| **Sport** | Pickleball KPIs (sessions, court time, play freshness); Play Freshness bar chart (WHOOP recovery on court days); Post-play HRV delta chart; Tournament results, match history grouped by event with per-game WIN/LOSS rows, scores, DUPR arc, and WHOOP recovery/HRV for tournament days |
| **Clinical** | Timeline of medications, diagnoses, and labs, abnormal values flagged |

### Today's Workout

Generated by Claude with full context injected. Comes back as structured blocks, warm-up, main, accessory, with exercises, sets × reps, weight, RPE, and coaching notes, each citing which vault note justified the choice. I can push it directly to Hevy as a routine with one button.

The card leads with the work, session strip, warm-up, exercises, and collapses the readiness narrative, the rationale, the clinical notes and the vault citations behind *Why this session*. The reasoning is the most interesting part of the system and the least useful thing to scroll past mid-set.

**It knows when it's already been done.** Adherence linking runs in the nightly scheduler, which is too late for a card you're looking at in the evening: a plan written at 09:11 and trained at 09:41 would still present itself as today's action, at loads set *before* the session and therefore lighter than what was actually lifted. `plan_execution_status()` answers it live, a session on the plan's date, started after the plan's `created_at`, carrying at least one working set, and the card re-titles to **Completed**, summarises the logged session, and stops offering the prescription as a target.

---

