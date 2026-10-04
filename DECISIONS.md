# Architecture Decision Log

Why things are the way they are. Each entry records the problem, what was
considered, what was chosen, and what it cost. Split by month; this page is the
index.

46 decisions recorded, 2026-04 to 2026-10.

---

## October 2026

- **2026-10-03** [The volume ramp read the wrong week, and yellow was the scale's centre](docs/decisions/2026-10.md#2026-10-03-the-volume-ramp-read-the-wrong-week-and-yellow-was-the-scales-centre)

## September 2026

- **2026-09-05** [The chart follows the data's shape, and an impossible reading is shown, not dropped](docs/decisions/2026-09.md#2026-09-05-the-chart-follows-the-datas-shape-and-an-impossible-reading-is-shown-not-dropped)
- **2026-09-05** [`shc seed` wrote 90 fabricated nights into the live database](docs/decisions/2026-09.md#2026-09-05-shc-seed-wrote-90-fabricated-nights-into-the-live-database)

## August 2026

- **2026-08-20** [Detraining is not fatigue, and only exposure can tell them apart](docs/decisions/2026-08.md#2026-08-20-detraining-is-not-fatigue-and-only-exposure-can-tell-them-apart)
- **2026-08-16** [WHOOP sync now resumes from a cursor instead of re-walking full history](docs/decisions/2026-08.md#2026-08-16-whoop-sync-now-resumes-from-a-cursor-instead-of-re-walking-full-history)
- **2026-08-12** [WHOOP daily reauth: the refresh request never asked for `offline`](docs/decisions/2026-08.md#2026-08-12-whoop-daily-reauth-the-refresh-request-never-asked-for-offline)
- **2026-08-10** [The sleep history has two eras, and no live code spans the seam](docs/decisions/2026-08.md#2026-08-10-the-sleep-history-has-two-eras-and-no-live-code-spans-the-seam)
- **2026-08-06** [WHOOP reauth kept dying because restarts abandoned in-flight token refreshes](docs/decisions/2026-08.md#2026-08-06-whoop-reauth-kept-dying-because-restarts-abandoned-in-flight-token-refreshes)
- **2026-08-05** [The engine writes the numbers; effort gets a block axis](docs/decisions/2026-08.md#2026-08-05-the-engine-writes-the-numbers-effort-gets-a-block-axis)

## July 2026

- **2026-07-31** [Every enforced check in the validator was an upper bound](docs/decisions/2026-07.md#2026-07-31-every-enforced-check-in-the-validator-was-an-upper-bound)
- **2026-07-28** ["I feel like I'm ALWAYS in a deload state"](docs/decisions/2026-07.md#2026-07-28-i-feel-like-im-always-in-a-deload-state)
- **2026-07-26** [Why the suite was green through a dozen calculation bugs, and what actually catches them](docs/decisions/2026-07.md#2026-07-26-why-the-suite-was-green-through-a-dozen-calculation-bugs-and-what-actually-catches-them)
- **2026-07-26** [Closing the open items: the prompt was still teaching the old rule](docs/decisions/2026-07.md#2026-07-26-closing-the-open-items-the-prompt-was-still-teaching-the-old-rule)
- **2026-07-26** [The load cap was fighting the RPE model, and the RPE model was right](docs/decisions/2026-07.md#2026-07-26-the-load-cap-was-fighting-the-rpe-model-and-the-rpe-model-was-right)
- **2026-07-26** [The load model was blind to effort, which is the one thing load is for](docs/decisions/2026-07.md#2026-07-26-the-load-model-was-blind-to-effort-which-is-the-one-thing-load-is-for)
- **2026-07-26** [e1RM assumed every set went to failure; it never does](docs/decisions/2026-07.md#2026-07-26-e1rm-assumed-every-set-went-to-failure-it-never-does)
- **2026-07-26** [Four evidence gaps closed by ingesting the literature, not by citing it](docs/decisions/2026-07.md#2026-07-26-four-evidence-gaps-closed-by-ingesting-the-literature-not-by-citing-it)
- **2026-07-26** [Catalogue curation, a grow-tier API, and two silent-corruption bugs found on the way](docs/decisions/2026-07.md#2026-07-26-catalogue-curation-a-grow-tier-api-and-two-silent-corruption-bugs-found-on-the-way)
- **2026-07-26** [The engine implemented 3 of its own framework's 4 volume landmarks](docs/decisions/2026-07.md#2026-07-26-the-engine-implemented-3-of-its-own-frameworks-4-volume-landmarks)
- **2026-07-25** [Exercise rotation: the engine was citing its own evidence backwards](docs/decisions/2026-07.md#2026-07-25-exercise-rotation-the-engine-was-citing-its-own-evidence-backwards)
- **2026-07-25** [Staleness checks compare content, not arrival time](docs/decisions/2026-07.md#2026-07-25-staleness-checks-compare-content-not-arrival-time)
- **2026-07-25** [night_date is frozen at write time; onset-vs-wake is OPEN](docs/decisions/2026-07.md#2026-07-25-nightdate-is-frozen-at-write-time-onset-vs-wake-is-open)
- **2026-07-25** [An ingest row describes one version of a record, or it describes nothing](docs/decisions/2026-07.md#2026-07-25-an-ingest-row-describes-one-version-of-a-record-or-it-describes-nothing)
- **2026-07-25** [Freshness describes persisted rows, never a sync attempt](docs/decisions/2026-07.md#2026-07-25-freshness-describes-persisted-rows-never-a-sync-attempt)
- **2026-07-23** [Conditioning leg-volume HOLD floored at population; RPE gaps found on a "why is my plan glutes-only" deep dive](docs/decisions/2026-07.md#2026-07-23-conditioning-leg-volume-hold-floored-at-population-rpe-gaps-found-on-a-why-is-my-plan-glutes-only-deep-dive)
- **2026-07-23** [Conditioning forbid_legs tighten now requires outcome evidence, not just a percentile (Phase C)](docs/decisions/2026-07.md#2026-07-23-conditioning-forbidlegs-tighten-now-requires-outcome-evidence-not-just-a-percentile-phase-c)
- **2026-07-19** [CONFIRMED n-of-1 priors now actuate volume targets; gate_loosen schema shipped, NOT wired](docs/decisions/2026-07.md#2026-07-19-confirmed-n-of-1-priors-now-actuate-volume-targets-gateloosen-schema-shipped-not-wired)
- **2026-07-19** [Two low-priority ACWR/deload-fitting gaps accepted, not fixed](docs/decisions/2026-07.md#2026-07-19-two-low-priority-acwrdeload-fitting-gaps-accepted-not-fixed)
- **2026-07-19** [Resistance ACWR bands retired; only conditioning is personalized](docs/decisions/2026-07.md#2026-07-19-resistance-acwr-bands-retired-only-conditioning-is-personalized)
- **2026-07-18** [A crashed lab runner is ERROR, never a verdict](docs/decisions/2026-07.md#2026-07-18-a-crashed-lab-runner-is-error-never-a-verdict)
- **2026-07-17** [Muscle-group gate is overridable, explicitly and audited](docs/decisions/2026-07.md#2026-07-17-muscle-group-gate-is-overridable-explicitly-and-audited)
- **2026-07-17** [Exercise selection rotates on LIVE plateaus and explains itself](docs/decisions/2026-07.md#2026-07-17-exercise-selection-rotates-on-live-plateaus-and-explains-itself)
- **2026-07-12** [Hevy logs per-hand; load mechanics no longer halves](docs/decisions/2026-07.md#2026-07-12-hevy-logs-per-hand-load-mechanics-no-longer-halves)
- **2026-07-12** [Illness gate requires corroboration (allergy vs infection)](docs/decisions/2026-07.md#2026-07-12-illness-gate-requires-corroboration-allergy-vs-infection)
- **2026-07-12** [Progression trend is contamination- and rep-range-robust](docs/decisions/2026-07.md#2026-07-12-progression-trend-is-contamination--and-rep-range-robust)
- **2026-07-12** [Fail conservative on missing/stale signals; one deload authority](docs/decisions/2026-07.md#2026-07-12-fail-conservative-on-missingstale-signals-one-deload-authority)
- **2026-07-10** [Emphasis lower-body muscles keep an MEV floor under conditioning interference](docs/decisions/2026-07.md#2026-07-10-emphasis-lower-body-muscles-keep-an-mev-floor-under-conditioning-interference)
- **2026-07-03** [ACWR uses a 21-day uncoupled chronic window (deliberate deviation from Gabbett 28-day)](docs/decisions/2026-07.md#2026-07-03-acwr-uses-a-21-day-uncoupled-chronic-window-deliberate-deviation-from-gabbett-28-day)

## June 2026

- **2026-06-03** [Sports-science panel review: muscle taxonomy + signal-quality decisions](docs/decisions/2026-06.md#2026-06-03-sports-science-panel-review-muscle-taxonomy--signal-quality-decisions)

## May 2026

- **2026-05-24** [Vault retrieval: semantic (model2vec) + lexical, with citation validation](docs/decisions/2026-05.md#2026-05-24-vault-retrieval-semantic-model2vec--lexical-with-citation-validation)

## April 2026

- **2026-04-25** [DuckDB WAL corruption recovery](docs/decisions/2026-04.md#2026-04-25-duckdb-wal-corruption-recovery)
- **2026-04-25** [Orbitron font via browser `<link>`, not `next/font/google`](docs/decisions/2026-04.md#2026-04-25-orbitron-font-via-browser-link-not-nextfontgoogle)
- **2026-04-24** [Migration numbering: never reuse a prefix](docs/decisions/2026-04.md#2026-04-24-migration-numbering-never-reuse-a-prefix)
- **2026-04-23** [DailyState as single source of truth](docs/decisions/2026-04.md#2026-04-23-dailystate-as-single-source-of-truth)
- **2026-04-22** [HRmax via Tanaka, not Fox (220 − age)](docs/decisions/2026-04.md#2026-04-22-hrmax-via-tanaka-not-fox-220--age)
- **2026-04-21** [Push to main, no PRs](docs/decisions/2026-04.md#2026-04-21-push-to-main-no-prs)

