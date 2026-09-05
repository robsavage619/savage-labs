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

export type SurfaceId = "today" | "week" | "body" | "lab";

export interface Surface {
  id: SurfaceId;
  route: string;
  label: string;
  /** What this surface is for, in one line. Used by the palette. */
  purpose: string;
}

export const SURFACES: readonly Surface[] = [
  { id: "today", route: "/", label: "Today", purpose: "What to train, and log it" },
  { id: "week", route: "/week", label: "Week", purpose: "What changed and how training is going" },
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
  { id: "session", label: "The session", surface: "today", keywords: ["workout", "plan", "hevy", "lifts", "sets", "reps", "push"] },
  { id: "midday", label: "Midday session", surface: "today", keywords: ["lunch", "nike", "second"] },
  { id: "report", label: "Daily report", surface: "today", keywords: ["narrative", "claude", "prompt"] },
  { id: "checkin", label: "Check-in", surface: "today", keywords: ["soreness", "weight", "energy", "stress", "log"] },

  // ── Week ─────────────────────────────────────────────────────────────────
  { id: "momentum", label: "Momentum", surface: "week", keywords: ["changed", "week over week", "delta"] },
  { id: "recovery", label: "Recovery", surface: "week", keywords: ["whoop", "hrv", "rhr", "skin temp"] },
  { id: "sleep", label: "Sleep", surface: "week", keywords: ["deep", "rem", "debt", "efficiency", "consistency"] },
  { id: "load", label: "Training load", surface: "week", keywords: ["acwr", "acute", "chronic", "ramp"] },
  { id: "vitals", label: "Raw WHOOP vitals", surface: "week", keywords: ["whoop", "spo2", "respiratory"] },
  { id: "recovery-trend", label: "Recovery trend", surface: "week", keywords: ["heatmap", "hrv trend", "monthly"] },
  { id: "patterns", label: "Patterns", surface: "week", keywords: ["day of week", "distribution", "correlation"] },
  { id: "meso", label: "Mesocycle", surface: "week", keywords: ["periodization", "deload", "block", "ctl", "atl"] },
  { id: "performance", label: "Performance curve", surface: "week", keywords: ["ctl", "atl", "tsb", "fitness", "fatigue", "form"] },
  // StrengthPanel was one 1,559px card holding six independent blocks — four
  // of them under 150px tall, trapped in a single column. Split, so each gets
  // its own grid footprint and its own ⌘K entry.
  { id: "last-session", label: "Last session", surface: "week", keywords: ["yesterday", "trained", "recent"] },
  { id: "consistency", label: "Training consistency", surface: "week", keywords: ["heatmap", "streak", "sessions", "2 years"] },
  { id: "balance", label: "Muscle balance", surface: "week", keywords: ["push pull", "ratio", "imbalance"] },
  { id: "recovery-training", label: "Recovery × training", surface: "week", keywords: ["train days", "rest days", "90d"] },
  { id: "volume-load", label: "Volume load", surface: "week", keywords: ["kg lifted", "tonnage", "52 weeks", "progressive overload"] },
  { id: "most-trained", label: "Most trained", surface: "week", keywords: ["e1rm", "prs", "top exercises", "set volume"] },
  // Was one card holding two components stacked (landmarks 342px + per-muscle
  // 641px) — the same mistake StrengthPanel made. Split.
  { id: "volume", label: "Volume vs landmarks", surface: "week", keywords: ["mev", "mav", "mrv", "sets", "group"] },
  { id: "per-muscle", label: "Per-muscle volume", surface: "week", keywords: ["muscle", "sets this week", "mev", "biceps", "chest"] },
  { id: "prescription", label: "Volume prescription", surface: "week", keywords: ["target", "sets", "muscle", "next week"] },
  { id: "cardio", label: "Cardio", surface: "week", keywords: ["zone 2", "z2", "aerobic", "sessions", "log"] },
  // Tournament history was 678px of a 1,138px card — its own thing.
  { id: "sport", label: "Pickleball", surface: "week", keywords: ["dupr", "court", "freshness", "play"] },
  { id: "tournaments", label: "Tournament results", surface: "week", keywords: ["matches", "dupr", "results", "partners", "scores"] },
  { id: "event-prep", label: "Tournament readiness", surface: "week", keywords: ["taper", "prep", "rest", "before event", "recovery on the day", "peaking"] },
  { id: "post", label: "Post-workout", surface: "week", keywords: ["debrief", "retrospective", "after action", "sync"] },
  { id: "goals", label: "2026 goals", surface: "week", keywords: ["scorecard", "targets", "dupr"] },

  // ── Body ─────────────────────────────────────────────────────────────────
  { id: "fueling", label: "Fuelling", surface: "body", keywords: ["protein", "calories", "weight", "hydration"] },
  { id: "physique", label: "Progress photos", surface: "body", keywords: ["photos", "waist", "compare", "upload"] },
  { id: "composition", label: "Body composition", surface: "body", keywords: ["weight", "vo2", "steps", "rhr"] },
  { id: "clinical", label: "Clinical record", surface: "body", keywords: ["labs", "meds", "conditions", "bloodwork", "risk"] },

  // ── Lab ──────────────────────────────────────────────────────────────────
  { id: "subject", label: "Subject dossier", surface: "lab", keywords: ["personalization", "days observed", "enrolled"] },
  { id: "trials", label: "Trials", surface: "lab", keywords: ["n-of-1", "experiments", "studies", "arms"] },
  { id: "findings", label: "Findings", surface: "lab", keywords: ["hypotheses", "confirmed", "refuted", "vault"] },
  { id: "engine", label: "Engine self-assessment", surface: "lab", keywords: ["accuracy", "fitted", "landmarks", "deload trigger"] },
  { id: "signals", label: "Clinical research signals", surface: "lab", keywords: ["sri", "allostatic", "lnrmssd"] },
  { id: "autonomic", label: "Autonomic load", surface: "lab", keywords: ["stress", "behavior impact"] },
  { id: "correlations", label: "What moves your HRV", surface: "lab", keywords: ["journal", "hrv delta", "behaviours"] },
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
