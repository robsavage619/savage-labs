import type { DailyState, DailyStateGates } from "@/lib/api";

export type VerdictTone = "positive" | "neutral" | "negative";

export interface ReconciledVerdict {
  /** Display word, e.g. "Push it", "Deload". */
  label: string;
  tone: VerdictTone;
  /** 0 (rest) … 4 (train hard); -1 when readiness is unknown. */
  rank: number;
  /** True when an auto-regulation gate capped the score-based verdict. */
  gated: boolean;
}

const VERDICT_LABELS = ["Rest & restore", "Active recovery", "Moderate", "Push it", "Train hard"];

function scoreRank(score: number | null | undefined): number {
  if (score == null) return -1;
  if (score >= 80) return 4;
  if (score >= 67) return 3;
  if (score >= 50) return 2;
  if (score >= 34) return 1;
  return 0;
}

function gateCeiling(gates: DailyStateGates): number {
  if (gates.deload_required) return 1;
  switch (gates.max_intensity) {
    case "rest":
      return 0;
    case "low":
      return 1;
    case "moderate":
      return 2;
    default:
      return 4;
  }
}

/**
 * Reconcile the readiness score with the auto-regulation gates into a single
 * verdict. A high readiness score never overrides a deload or intensity cap —
 * the gates set the ceiling, so the headline can't say "Push it" on a day the
 * plan prescribes a deload.
 */
export function reconciledVerdict(state: DailyState): ReconciledVerdict {
  const base = scoreRank(state.readiness.score);
  if (base < 0) return { label: "Awaiting data", tone: "neutral", rank: -1, gated: false };
  const rank = Math.min(base, gateCeiling(state.gates));
  const gated = rank < base;
  const label = state.gates.deload_required && rank <= 1 ? "Deload" : VERDICT_LABELS[rank];
  const tone: VerdictTone = rank >= 3 ? "positive" : rank >= 1 ? "neutral" : "negative";
  return { label, tone, rank, gated };
}
