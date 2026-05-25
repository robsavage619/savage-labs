# Progress-Photo Measurement — Methodology & Grounding

This document is the **spec the vision code must obey**. Every numeric threshold in
`shc.vision.*` traces to a published source listed here. **No threshold may be
invented in code** — if a constant isn't grounded here, it doesn't ship.

The design follows the honest constraint agreed with Rob: photos cannot measure
"the smallest changes" precisely. We therefore (a) measure with deterministic code,
not a language model, (b) set every threshold from published measurement-error
figures, and (c) refuse to report change that sits inside the error band.

---

## 1. What 2D photos can validly reveal

Model-based 2D-photo body composition is now a validated field, not guesswork:

- AI 2D-photo body-fat estimation reaches concordance **CCC ≥ 0.96 vs DXA**,
  outperforming consumer BIA scales (CCC 0.90–0.95).
  — *npj Digital Medicine* 2024, https://www.nature.com/articles/s41746-024-01380-6
- Front + side (+ back) images → a parameterized body model fitted to a
  **canonical pose** yields consistent circumference / waist-to-hip estimates,
  validated on 1,200 participants (MeasureNet).
  — *npj Digital Medicine* 2023, https://www.nature.com/articles/s41746-023-00909-5

**Implication for this build:** we extract pose-normalized *geometric ratios* as the
primary signal. An absolute body-fat % estimate is explicitly out of scope until a
DXA-validated model is added, and even then must be surfaced with its error band —
never as a point truth.

**Robustness to real-world capture.** Single photos vary in pose, arm position, and
lighting. We absorb that variation three ways: (a) **arm exclusion** — arms are
masked out of the silhouette via the elbow/wrist landmark chains before measuring, so
arm position can't inflate the waist; (b) **anatomical region measurement** — shoulder
breadth is the widest row near the shoulder line, the waist is the narrowest row in the
lower-middle trunk (≈45–90% of the shoulder→hip span, where the natural waist sits, per
ISAK rib-to-crest convention), and the hip is taken at the hip line — this avoids the
degenerate "narrowest row is the bony shoulder" failure; (c) **rolling-median trend**
(frontend) — the displayed trend is a median over recent shots, so a single off-pose or
off-light photo cannot move it.

## 2. Noise floor — smallest detectable change (ISAK TEM)

Technical Error of Measurement from the ISAK standard defines how much a repeated
measurement varies due to method, not real change:

- Intra-rater **girth TEM ≈ 1–2%**; skinfold TEM ≈ 5%.
  — Technical error of measurement in anthropometry,
    https://www.researchgate.net/publication/262707035_Technical_error_of_measurement_in_anthropometry_English_version
  — ISAK Standards for Anthropometry Assessment,
    https://www.researchgate.net/publication/333585249_Standards_for_Anthropometry_Assessment

**Code constant (`noise.py`):**
- `GIRTH_NOISE_FRACTION = 0.02` — a width/girth-derived delta below 2% of baseline is
  reported as **"within measurement error — no detectable change"** and the photo pair
  is *withheld* from any interpretation layer.
- Ratios (waist-to-shoulder, waist-to-hip) combine two girth measurements; we apply the
  same 2% floor to the ratio delta as a conservative bound.

This 2% floor is the literal, expert-derived definition of "the smallest change we can
honestly claim." It is the structural block against confabulated progress.

## 3. Capture standardization — required input conditions

No method survives non-standardized capture. The quality gate enforces these; a photo
violating them is flagged/rejected before measurement (garbage in is refused, not measured).

- **Camera:** chest height, perpendicular to body, same distance/spot each session.
- **Lighting:** even, diffuse, ~45° and slightly above; no overhead/side shadows.
- **Timing:** morning, post-bathroom, pre-food, **≥24 h post-training** (pump inflates
  size 5–10%).
- **Cadence:** monthly — meaningful physique change takes ~a month to appear.
- **Consistency:** identical pose, clothing, background, camera, lighting every session.
  — Legion progress-photo protocol, https://legionathletics.com/how-to-take-progress-photos/
  — Updated standards for photographic documentation in aesthetic medicine,
    https://pmc.ncbi.nlm.nih.gov/articles/PMC5585426/

**Severity matters — block only what breaks measurement.** Real-world capture varies
(lighting, distance, time of day). The silhouette segmentation is robust to lighting,
and the headline ratios are distance-invariant, so those are treated as **advisory
notes**, not failures. Only genuinely unmeasurable shots are blocked.

**Code constants (`quality_gate.py`):**
- *Blocking* — `MIN_POSE_CONFIDENCE = 0.7` (per-landmark visibility floor for shoulders
  + hips) and the torso-in-frame check (`LOWER_BODY_MIN_VISIBILITY = 0.5`, landmarks
  within `[0,1]`). A shot failing either can't be measured → `quality_pass = False`.
- *Advisory* — `MAX_SCALE_DRIFT_FRACTION = 0.10` (camera-distance change vs baseline;
  ratios are distance-invariant so this is informational) and
  `MAX_BRIGHTNESS_ASYMMETRY = 0.15` (uneven lighting; segmentation is lighting-robust,
  so this never corrupts geometry). Surfaced as notes; the photo still passes.

## 4. Scale normalization

Camera distance cancels by expressing every width as a fraction of a stable internal
reference length. We use **shoulder-midpoint → hip-midpoint pixel distance** (trunk
span) as the scale unit — skeletally stable (it does not change with fat/muscle) and,
critically, present in any shot framed **shoulders-to-hips**. Feet are never required,
so a normal torso photo is sufficient.

The headline metrics — **waist-to-shoulder** and **waist-to-hip** ratios — are
width/width, hence dimensionless and camera-distance-invariant regardless of scale.
The shoulder→hip span is used to normalize absolute widths and for the scale-drift
gate. Minimum valid frame: both shoulders and both hips in-frame (`incomplete_frame`
fires otherwise), since the waist is measured as the narrowest silhouette row between
them.

## 5. Cross-source corroboration

Photo geometry is never trusted alone. Each comparison is checked against existing
DuckDB data — scale/check-in weight and Hevy strength volume. If the photo signal and
the weight/strength signal disagree in direction, the system **flags the contradiction**
rather than averaging it (per project rule: surface conflicts, fail visibly).

## 6. Physique critique (Claude-as-judge) — shipped with consistency guardrails

A qualitative critique is generated via the copy-prompt → Claude → POST-back flow
(`/api/progress-photos/critique-prompt` → `/api/progress-photos/critique`). To stop it
drifting with daily lighting it is **hybrid and anchored**:

1. **Change verdict is not the model's call.** The leaner/stable/softer verdict is the
   deterministic 2%-gated measurement, passed into the prompt; the model must not
   contradict it.
2. **Shape & change (authoritative)** is keyed to the silhouette-derived numbers
   (lighting-invariant), not the photo's pixels. No body-fat % claims.
3. **Visible detail (advisory)** comes from the photo and is explicitly labelled
   *lighting-dependent* with no change claims.
4. **Anchored to the measurement basis.** A stored critique records the median ratios it
   was generated against; the UI only offers a refresh once the median clears the 2%
   floor — so a new photo under different lighting shows the *same* critique. It updates
   on real measured change, never on lighting.

Backed by the blind-control eval (`tests/test_vision_controls.py`): same-photo-twice
yields "no change"; known-direction pairs call direction correctly.
