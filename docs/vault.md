# The Research Vault

*How a hand-curated Obsidian corpus becomes retrieval context for the planner.*

[<- back to README](../README.md)

---

## The Obsidian Vault

The third input into every AI call, alongside live biometrics and clinical context, is a personal knowledge base of **405 research notes** I've built in Obsidian. Every workout plan Claude generates is grounded in this vault, not in whatever the model learned during pretraining.

The difference matters. Claude knows exercise science in aggregate from its training data. My vault encodes *my* specific protocol decisions, which periodization model I follow, which meta-analyses I trust on rest intervals, what the research actually says about training frequency for hypertrophy vs what gets repeated on the internet. When Claude writes me a plan, it's applying my evidence base, not a generic one.

### What's In It

~416 notes across 8 domains, all ingested from primary sources (textbooks, meta-analyses, RCTs), structured with YAML frontmatter tags, and condensed to actionable prescription sections.

| Domain | Notes | Primary sources |
|---|---|---|
| Strength & Hypertrophy | 147 | Schoenfeld, Israetel, Helms, Bompa/Zatsiorsky, volume landmarks, SRA curves, periodization, DUP |
| Sleep Science | 76 | Walker, Winter, stage targets, SpO2 thresholds, circadian anchoring, sleep × athletic performance |
| LLM Engineering & RAG | 67 | Self-RAG, ReAct, Reflexion, Constitutional AI, informs how the retrieval system is designed |
| Nutrition | 55 | Israetel, Helms, Attia, priority hierarchy, protein targets, recomposition conditions, supplement tiers |
| Longevity & Healthspan | 35 | Attia. VO₂max, centenarian decathlon, Zone 2, ApoB vs LDL-C, compression of morbidity |
| HRV & Biometric Research | 15 | Task Force 1996, Kiviniemi, Plews, Tanaka, Dial, the papers behind every HRV and zone design decision |
| Concurrent Training & Sports Science | 11 | Wilson, Coffey & Hawley, Schumann, Suchomel, Seiler, interference theory, AMPK/mTOR, sport compatibility |
| N-of-1 Methodology | 5 | Schork, Daza, Piccininni, single-subject experimental design as rigorous science, not just self-tracking |

---

### How the Vault Gets Used

On every workout generation or briefing call, `load_vault_research()` selects the 4 most relevant notes based on what's going on with me today:

```python
signals = {
    "hrv_anomaly",         # HRV σ-deviation < -1.0
    "high_acwr",           # ACWR > 1.3
    "deload",              # gates.deload_required = True
    "illness",             # checkin.illness_flag = True OR rr_delta ≥ 1.0
    "poor_sleep",          # last night < 6h
    "push_pull_imbalance", # 28d ratio > 1.2 or < 0.8
    "volume_spike",        # 4-week volume Δ > 40%
    "recomposition",       # always active
    "exercise_selection",  # always active
    "pickleball_focus",    # pickleball_min_7d ≥ 60
    "concurrent_training", # pickleball_min_7d ≥ 150 — triggers concurrent-training vault notes
}
```

Each note has YAML frontmatter tags. The retriever scores tags against active signals (`+2` per match, `+1` for default) and returns the top 4. On a high-ACWR/low-HRV day, overtraining and deload notes automatically beat out rest-interval notes.

**Example: ACWR = 1.42, HRV σ = −1.8**

| Note | Score |
|---|---|
| `overtraining-and-deload.md` | **+6** (deload+2, hrv_anomaly+2, high_acwr+2) |
| `fitness-fatigue-theory.md` | **+4** (deload+2, hrv_anomaly+2) |
| `supercompensation-theory.md` | **+3** (volume_spike+2, default+1) |
| `rest-interval-hypertrophy.md` | **+1** (default+1) |

Six notes also load unconditionally on every plan call, exercise selection, exercise order, Schoenfeld's hypertrophy mechanisms, rest intervals for strength and hypertrophy. These are the foundation that every plan builds on regardless of the day's signals.

Raw notes get stripped down to just the actionable sections before being sent to Claude:

```
## Summary          → the principle
## Prescription     → the actual numbers
## Key Claims       → what the research says
## Practical Takeaways → how to apply it
```

A 3,000-word hypertrophy paper becomes a 400-word prescription. Every plan Claude generates has to cite which vault notes it applied, there's a `vault_insights` field that's validated server-side, so the model can't silently ignore the research I handed it.

---

