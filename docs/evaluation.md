# Evaluation

*Does any of this work? Two axes, two very different answers.*

[<- back to README](../README.md)

---

Most of this repository describes things the system does. This file is the part
that asks whether they work, and reports the answer whether or not it is
flattering. It is the document I would read first.

## Calibration: does a prescription land where it says it will?

When the planner writes "3 x 11 @ 55 lb, RPE 8", does that set come back logged
at RPE 8? Over 612 prescriptions carrying an `rpe_target`, 234 matched to a
logged actual:

```
bias                    +0.03 RPE    95% CI -0.04 to +0.10
SD                       0.56
within 0.5 of target      86%
```

The load model is good. The interesting part is that nobody had ever measured
it. The engine had been prescribing for months on an assumption.

## Predictive validity: does readiness predict the session?

The morning readiness score gates training. That authority rests entirely on
readiness carrying information about capacity. Tested against the session that
actually followed:

```
volume-load        r = -0.07     CI spans zero
mean RPE           r = +0.21     CI spans zero
working sets       r = +0.04     CI spans zero
                                 n = 54
```

It cannot currently be shown to predict anything.

Splitting the composite by input shows where the dead weight sits:

```
hrv      weight 0.40    no signal    (best r +0.21, CI spans zero)
sleep    weight 0.30    PREDICTS     (r +0.30 vs session RPE, CI +0.02 to +0.53)
rhr      weight 0.20    no signal    (best r +0.07, CI spans zero)
```

0.60 of the score sits on inputs with no detectable relationship to the session.
HRV and RHR also correlate at about -0.75 across 913 days, which suggests they
are largely one underlying signal wearing two hats. The API reports that share
as `weight_on_silent_components`.

**The weights were not changed.** Re-weighting readiness is a gate change. It
requires an invariant update and a decision record, and n = 54 with one marginal
correlation is not sufficient grounds. Measuring something is not the same as
having earned the right to act on it.

Two independent results corroborate the null rather than explaining it away: the
load-to-HRV coupling is |r| < 0.06 at every lag from 0 to 5 days across roughly
430 observations, and the invariants already concede that HRV is a weak signal
here because it is corrupted by a beta-blocker taken as needed.

## Why both numbers appear together

The planner prescribes accurately and predicts nothing. Either number alone
tells the wrong story. A system that publishes only the flattering half of its
own evaluation is a marketing asset, not an instrument.

## The noise floor

With one subject, a population threshold answers "where does he sit among
people?" when the question is "did this move?" `shc.stats.noise_floor` gives the
whole application one definition of the smallest worthwhile change: half the
subject's own baseline SD.

Two traps are encoded in the function rather than left to callers, because both
were live in the first version:

- An SWC of exactly 0.0 is an **answer**, not an absence. A flat baseline means
  any movement at all is outside the noise. Callers must test `is not None`.
- The floor must come from the same window as the baseline it bands. Deriving it
  from 28 days while comparing against a 7-day mean answers two questions in one
  verdict.

## Pre-registered n-of-1 studies

Exploratory analysis on your own data is how you find a result you like. The lab
exists to stop that. A study fixes its arms, outcome, test and threshold in
advance, then accumulates days until it can be scored CONFIRMED, REFUTED,
INCONCLUSIVE or INSUFFICIENT.

The volume dose-response is the worked example. Pooled analysis showed 3-5
sets/week producing +1.52 kg of two-week e1RM against +0.86 kg at 6-9 sets,
which is the textbook MEV/MAV shape appearing in one person's own training log.
Centring within exercise shrank it to +0.68 kg, 95% CI -0.04 to +1.40.
Suggestive, not established. It is now pre-registered rather than re-explored.

Two design constraints that turned out to matter more than the statistics:

- **Arm assignment cannot be a hash when the arms describe observable
  conditions.** Studies with arms like "<7h sleep" describe what happened, not
  what was assigned. Auto-logging adherence against a date hash would file an
  8.4-hour night into the "<7h sleep" arm and produce a confident null, which is
  worse than the silence it replaced.
- **One observation per week means classifying on one day per week.** Writing
  all seven days would produce seven perfectly correlated copies of a single
  observation and shrink a p-value on data that does not exist.

## What enforces correctness

| Layer | What it does |
|---|---|
| `ENGINE_INVARIANTS.md` | The athlete-protection contract, with 43 tests in `test_engine_invariants.py` |
| `validate_plan()` | Schema plus deterministic gates. Rejects a model-written plan outright rather than adjusting it |
| Migration tests | 102 migrations, with view and data-integrity tests over the ones that change semantics |
| Suite | 1,028 tests, 13,951 test lines against 33,295 source lines |

The division of labour is deliberate. The model reasons and writes a plan. A
separate deterministic layer decides whether that plan is allowed to exist. The
model is never asked to enforce a rule it could talk itself out of.

## Known limitations

Collected here rather than scattered, because they are the honest state of the
system:

- **Readiness has no demonstrated predictive validity** at n = 54. It still
  gates training, on the grounds that the physiological prior is reasonable and
  the alternative is no gate at all. This is the weakest load-bearing assumption
  in the engine.
- **HRV is a corrupted signal here.** Propranolol taken as needed suppresses
  heart rate, and 0.40 of the readiness composite rests on it.
- **Two e1RM sources disagree** for the same lift and the cause is not yet
  understood. The validator and the ceiling read different numbers.
- **The deload trigger is not personalized.** It can still return
  `using_population_defaults: True`, which is easy to mistake for a fitted value.
- **Four exercise twin pairs are unmapped** pending a human judgment call, where
  the evidence detector disagreed with an existing alias row.
- **Residual ledger duplication is 6.2%**, down from 29.1%, concentrated in
  pre-2021 history below the evidence threshold for automatic pairing.
- **No minute-level heart rate exists in the database**, so within-session
  cardiac drift cannot be computed. A tile that claimed to do it was removed
  rather than repaired.
