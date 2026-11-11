/**
 * The one manifest of every addressable section in the app.
 *
 * This exists because the nav and the sections drifted apart: `REVIEW_SECTIONS`
 * listed four cluster ids while the page carried eight different section ids,
 * with zero overlap, so the deep-link expansion could never fire and every nav
 * click scrolled to an inert divider. That was hand-patched once. This is the
 * structural fix — the pages render FROM this list and the command palette
 * reads THE SAME list, so an id that doesn't exist is a type error rather than
 * a dead scroll.
 *
 * Adding a section means adding a row here. There is no second place.
 */

export type SurfaceId = "today" | "training" | "recovery" | "body" | "lab";

export interface Surface {
  id: SurfaceId;
  route: string;
  label: string;
  /** What this surface is for, in one line. Used by the palette. */
  purpose: string;
}

export const SURFACES: readonly Surface[] = [
  { id: "today", route: "/", label: "Today", purpose: "What to train, and log it" },
  { id: "training", route: "/training", label: "Training", purpose: "Am I growing, muscle by muscle" },
  { id: "recovery", route: "/recovery", label: "Recovery", purpose: "Am I absorbing the work" },
  { id: "body", route: "/body", label: "Body", purpose: "Fuelling, physique, clinical record" },
  { id: "lab", route: "/lab", label: "Lab", purpose: "Trials, findings, what the engine has learned" },
] as const;

export interface Section {
  /** Anchor id. Must be unique across the app. */
  id: string;
  label: string;
  surface: SurfaceId;
  /** Extra search terms for the command palette — the words Rob would type. */
  keywords?: string[];
}

/**
 * Column span on the 4-column grid, by information density. A sparkline tile
 * and a 104-week heatmap should not occupy the same footprint; giving every
 * card the full width is what turned "hidden behind accordions" into "a
 * 6,700px single column".
 */
export type Span = 1 | 2 | 3 | 4;

export const SECTIONS: readonly Section[] = [
  // ── Today ────────────────────────────────────────────────────────────────
  { id: "call", label: "Today's call", surface: "today", keywords: ["verdict", "readiness", "gates", "locked", "intensity"] },
  { id: "overnight", label: "Did anything move overnight", surface: "today", keywords: ["noise floor", "swc", "baseline", "hrv", "rhr", "moved"] },
  { id: "readiness", label: "Readiness breakdown", surface: "today", keywords: ["readiness", "score", "components", "weights"] },
  { id: "load-split", label: "Load ratio split", surface: "today", keywords: ["acwr", "lifting", "conditioning", "spike"] },
  { id: "fresh", label: "Muscle freshness", surface: "today", keywords: ["recovered", "days since", "dose", "ready"] },
  { id: "session", label: "The session", surface: "today", keywords: ["workout", "plan", "hevy", "lifts", "sets", "reps", "push"] },
  { id: "midday", label: "Midday session", surface: "today", keywords: ["lunch", "nike", "second"] },
  { id: "report", label: "Daily report", surface: "today", keywords: ["narrative", "claude", "prompt"] },
  { id: "checkin", label: "Check-in", surface: "today", keywords: ["soreness", "weight", "energy", "stress", "log"] },

  // ── Training + Recovery (split from Week, 2026-11-09) ────────────────────
  { id: "sleep-need", label: "Sleep need", surface: "recovery", keywords: ["need", "debt", "strain", "how much sleep"] },
  { id: "aerobic-base", label: "Aerobic base", surface: "recovery", keywords: ["zone 2", "z2", "z3", "aerobic", "180"] },
  { id: "plan", label: "The session to do", surface: "training", keywords: ["workout", "plan", "lifts", "today"] },
  { id: "rotation", label: "The rotation", surface: "training", keywords: ["swap", "swapped in", "menu", "held", "plateau", "exercise selection"] },
  { id: "volume", label: "Sets against target", surface: "training", keywords: ["mev", "mav", "mrv", "sets", "muscle", "landmarks", "volume", "per-muscle", "biceps", "glutes"] },
  { id: "court", label: "What the court costs", surface: "training", keywords: ["pickleball", "court", "glutes", "leg gate"] },
  { id: "lifts", label: "Strength", surface: "training", keywords: ["e1rm", "progressing", "stalled", "sliding", "strength", "working weights"] },
  { id: "hrv", label: "HRV vs baseline", surface: "recovery", keywords: ["hrv", "heart rate variability", "band", "nervous system"] },
  { id: "rhr", label: "Resting heart rate", surface: "recovery", keywords: ["rhr", "resting", "heart rate"] },
  { id: "recovery", label: "Recovery score", surface: "recovery", keywords: ["whoop", "green", "red", "score"] },
  { id: "sleep", label: "Sleep architecture", surface: "recovery", keywords: ["deep", "rem", "light", "stages"] },
  { id: "sleep-timing", label: "Sleep timing", surface: "recovery", keywords: ["consistency", "midpoint", "efficiency", "wake"] },
  { id: "momentum", label: "This week vs last", surface: "recovery", keywords: ["changed", "week over week", "delta", "momentum"] },
  { id: "spo2", label: "Overnight oxygen", surface: "recovery", keywords: ["spo2", "oxygen", "airway", "vitals"] },
  { id: "patterns", label: "Best and worst days", surface: "recovery", keywords: ["day of week", "weekday", "patterns"] },
  { id: "recovery-trend", label: "Green, yellow, red", surface: "recovery", keywords: ["distribution", "share", "all time"] },

  // ── Body ─────────────────────────────────────────────────────────────────
  { id: "fueling", label: "Fuelling", surface: "body", keywords: ["protein", "calories", "weight", "hydration"] },
  { id: "physique", label: "Progress photos", surface: "body", keywords: ["photos", "waist", "compare", "upload"] },
  { id: "composition", label: "Body weight", surface: "body", keywords: ["weight", "scale", "lbs", "recomp"] },
  { id: "vo2", label: "VO₂ max", surface: "body", keywords: ["vo2", "aerobic", "fitness", "cardio"] },
  { id: "steps", label: "Daily steps", surface: "body", keywords: ["steps", "walking", "neat", "movement"] },
  { id: "rhr-devices", label: "Resting HR, both devices", surface: "body", keywords: ["rhr", "apple watch", "whoop", "resting"] },
  { id: "airway", label: "Overnight oxygen", surface: "body", keywords: ["spo2", "oxygen", "saturation", "apnea", "osa", "cpap"] },
  { id: "resp", label: "Breathing rate", surface: "body", keywords: ["respiratory", "breathing", "breaths", "illness"] },
  { id: "tape", label: "Tape measurements", surface: "body", keywords: ["waist", "tape", "girth", "inches"] },
  { id: "clinical", label: "Clinical record", surface: "body", keywords: ["labs", "meds", "conditions", "bloodwork", "risk"] },

  // ── Lab ──────────────────────────────────────────────────────────────────
  { id: "team", label: "The researchers", surface: "lab", keywords: ["team", "specialists", "agenda", "leads", "researchers"] },
  { id: "forecast", label: "Forecast desk", surface: "lab", keywords: ["forecast", "predict", "skill", "tomorrow", "bet"] },
  { id: "beliefs", label: "Belief ledger", surface: "lab", keywords: ["beliefs", "prior", "posterior", "what we know", "research team"] },
  { id: "questions", label: "Questions in flight", surface: "lab", keywords: ["hypotheses", "questions", "pipeline", "review"] },
  { id: "notebook", label: "Team conversation", surface: "lab", keywords: ["notebook", "threads", "agents", "methodologist", "analyst"] },
  { id: "misses", label: "Where the lab is wrong", surface: "lab", keywords: ["misses", "errors", "residuals", "weekday", "sunday"] },
  { id: "coverage", label: "What the team can see", surface: "lab", keywords: ["data", "coverage", "streams", "stale"] },
  { id: "subject", label: "Subject dossier", surface: "lab", keywords: ["personalization", "days observed", "enrolled"] },
  { id: "trial-progress", label: "Trial progress", surface: "lab", keywords: ["arms", "days", "minimum", "n-of-1"] },
  { id: "effects", label: "Trial results", surface: "lab", keywords: ["forest", "confidence interval", "effect size", "p value"] },
  { id: "hrv-drivers", label: "What moves your HRV", surface: "lab", keywords: ["journal", "habits", "what moves hrv", "correlations", "hrv delta"] },
  { id: "engine-bullets", label: "Engine scorecard", surface: "lab", keywords: ["adherence", "load accuracy", "skill"] },
  { id: "priors", label: "Proven priors", surface: "lab", keywords: ["confirmed", "proven", "actuation"] },
  { id: "trials", label: "Trials", surface: "lab", keywords: ["n-of-1", "experiments", "studies", "arms"] },
  { id: "findings", label: "Findings", surface: "lab", keywords: ["hypotheses", "confirmed", "refuted", "vault"] },
  { id: "engine", label: "Engine self-assessment", surface: "lab", keywords: ["accuracy", "fitted", "landmarks", "deload trigger"] },
  { id: "signals", label: "Clinical research signals", surface: "lab", keywords: ["sri", "allostatic", "lnrmssd"] },
  { id: "autonomic", label: "Autonomic load", surface: "lab", keywords: ["stress", "behavior impact"] },
  { id: "suggested", label: "Suggested studies", surface: "lab", keywords: ["suggest", "new trial", "shortlist"] },
] as const;

export function sectionsFor(surface: SurfaceId): Section[] {
  return SECTIONS.filter((s) => s.surface === surface);
}

export function surfaceFor(sectionId: string): Surface | undefined {
  const sec = SECTIONS.find((s) => s.id === sectionId);
  return sec ? SURFACES.find((v) => v.id === sec.surface) : undefined;
}

/** Deep link to a section, wherever it lives. */
export function hrefFor(sectionId: string): string {
  const surface = surfaceFor(sectionId);
  return surface ? `${surface.route}#${sectionId}` : "/";
}
