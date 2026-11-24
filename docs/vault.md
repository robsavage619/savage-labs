# The Research Vault

*How a hand-curated Obsidian corpus becomes retrieval context for the planner.*

[<- back to README](../README.md)

---

## The Obsidian Vault

The third input into every AI call, alongside live biometrics and clinical context, is a personal knowledge base of research notes I've built in Obsidian. Every workout plan Claude generates is grounded in this vault, not in whatever the model learned during pretraining.

The difference matters. Claude knows exercise science in aggregate from its training data. My vault encodes *my* specific protocol decisions, which periodization model I follow, which meta-analyses I trust on rest intervals, what the research actually says about training frequency for hypertrophy vs what gets repeated on the internet. When Claude writes me a plan, it's applying my evidence base, not a generic one.

### What's In It

The vault is multi-domain and larger than the planner needs: the wiki folder holds about 1,500 notes, and only the roughly 500 that classify into the planner's five domains (training, nutrition, sleep, HRV, health) are ever candidates. The rest (LLM engineering, career, sports business and so on) never reach a plan. Notes are ingested from primary sources (textbooks, meta-analyses, RCTs), carry YAML frontmatter tags, and are condensed to their actionable sections before use.

The domain comes from frontmatter tags and filename keywords, so a note can silently fall out of scope if its tags change. At index build the server logs the in-scope count and warns when it falls below a floor.

| In-scope domain | Primary sources |
|---|---|
| Training | Schoenfeld, Israetel, Helms, Bompa/Zatsiorsky, volume landmarks, SRA curves, periodization, concurrent training |
| Sleep | Walker, Winter, stage targets, SpO2 thresholds, circadian anchoring, sleep × athletic performance |
| Nutrition | Israetel, Helms, Attia, priority hierarchy, protein targets, recomposition conditions, supplement tiers |
| HRV | Task Force 1996, Kiviniemi, Plews, Tanaka, Dial, the papers behind every HRV and zone design decision |
| Health | Attia on VO₂max, Zone 2, ApoB vs LDL-C and compression of morbidity; clinical references |

---

### How the Vault Gets Used

On every workout generation or briefing call, `load_vault_research()` asks `VaultIndex.query` for the top 20 notes (the clinical-findings panel in the briefing asks for 6, scoped to its own domains and ranked against an explicit question). Retrieval has three parts:

**1. Signals from today's state.** `state_signals()` derives a set from DailyState, for example `hrv_anomaly`, `high_acwr`, `deload`, `illness`, `poor_sleep`, `push_pull_imbalance`, `volume_spike`, `pickleball_focus` and `concurrent_training`, plus always-on `recomposition` and `exercise_selection`. Callers add keyword hints from the day's plan context.

**2. A blended score per note.** Lexical points: `+2` for each frontmatter tag that maps to an active signal (`+1` for the default signal), `+1` for a signal word in the filename, `+3` for a hint in the title or filename, `+1` for a hint in the body excerpt, `+0.5` per hint in a heading. Semantic points: cosine similarity between an embedded query (signals, hints and any explicit question) and each note, from a small static embedding model (`potion-base-8M`), weighted by 4. A note with zero lexical score is still eligible if its similarity clears 0.45, which recovers notes whose wording differs from the signal vocabulary. If the model cannot load, scoring falls back to lexical only.

**3. Pinned foundations, capped.** Seventeen foundation notes (exercise selection and order, hypertrophy mechanisms, rest intervals, volume landmarks, SRA, periodization, load selection) are pinned, but pins may take at most 40% of the result, 8 of 20, in a fixed priority order. The rest of the slots go to the state-ranked notes, so a high-ACWR, low-HRV day surfaces overtraining and deload notes ahead of generic ones.

The prompt also carries a compact catalog of every in-scope note, titles and filenames only, which is the citation inventory the model is told to cite from.

Raw notes get stripped down to just the actionable sections before being sent to Claude:

```
## Summary          → the principle
## Prescription     → the actual numbers
## Key Claims       → what the research says
## Practical Takeaways → how to apply it
```

A 3,000-word hypertrophy paper becomes a 400-word prescription. Every plan Claude generates has to cite which vault notes it applied, there's a `vault_insights` field that's validated server-side, so the model can't silently ignore the research I handed it.

---

### When the Vault Is Missing

The vault lives on the host's disk, outside the repo, so a host without it used to plan with no grounding and say nothing. Since 39178f6 that is reported at every layer:

- `vault_context()` returns a `## VAULT UNAVAILABLE` notice instead of an empty string, telling the model its output is not grounded in the vault and to cite no note. The planner and the briefing both carry it.
- `/api/freshness` has a Vault row: state `ok` with a note count, or `missing` when the index reads no notes. The sync chip lists a missing vault under its own wording.
- Citation validation has nothing to check against when the allow-list is empty, so it skips rather than rejecting every plan. That is the one silent path left, and the notice above is what makes it visible.

