# Post-workout retrospective

The single source for what a retrospective contains. The unattended coach job reads
STEP 2 and STEP 3; it fetches its own data, so there is no STEP 1 here. Restored from
the `RETROSPECTIVE_PROMPT` constant that lived in `frontend/components/post-workout-panel.tsx`
until 8b696a8 removed that panel.

Inputs: `GET /api/training/after-action` gives per-exercise actual reps, load and RPE
against the plan target, the next-session suggestion and verdict (drop, progress,
repeat) for each lift, and a `## VAULT RESEARCH` section of notes chosen from this
session's execution signals. Ground every adjustment in that section.

## STEP 2: write the summary

Tone: a coach debriefing at the gym door. Direct, plain language, second person
("you"). No academic phrasing, no filename citations. Two or three short paragraphs:

1. **How it went against the plan.** Did you hit the prescribed sets, reps and load?
   Where did RPE land relative to target? Call out the standout lift (best
   progression) and the one that lagged.
2. **What to adjust next session.** Translate the after-action verdicts into plain
   guidance: which lifts to add load to, which to hold or drop, and why (cite the RPE
   or rep reason, not the percentage). Ground each adjustment in the mechanism from
   the VAULT RESEARCH section, e.g. why a rep miss means dropping load (too few
   effective reps near failure), not adding it.
3. **Flags worth carrying forward.** A lift that felt off, a rep-miss pattern, a joint
   niggle if noted. Skip the paragraph if nothing is notable.

## STEP 3: the POST body

`POST /api/workout/retrospective`:

```json
{
  "workout_id": "<the session's workout_id>",
  "summary": "<the 2-3 paragraph text>",
  "progressive_overload_achieved": true,
  "rpe_vs_target": "<one phrase, e.g. 'on target', 'ran 1-2 above plan', 'easier than prescribed'>",
  "flags": ["<short flag strings, or empty>"],
  "vault_insights": ["<2+ notes, each citing a vault filename from VAULT RESEARCH and the mechanism it justifies, e.g. 'effective-reps-hypertrophy.md: rep miss = too few effective reps near failure, drop load to finish the range'>"]
}
```

`progressive_overload_achieved` is true when at least half the lifts hit progress or
repeat-at-target. Confirm the POST succeeded.
