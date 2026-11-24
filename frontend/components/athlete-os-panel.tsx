import type { DailyState, WorkoutPlan } from "@/lib/api";
import { reconciledVerdict, type VerdictTone } from "@/lib/readiness";

// The AthleteOSPanel that lived here was rendered nowhere and was removed; only this
// helper is used (by today-brief).
export function readinessCommand(state: DailyState | undefined, plan: WorkoutPlan | undefined): {
  label: string;
  detail: string;
  tone: VerdictTone;
} {
  if (!state) {
    return {
      label: "Awaiting signal lock",
      detail: "Consumer sensors are still resolving today's read.",
      tone: "neutral",
    };
  }
  const verdict = reconciledVerdict(state);
  const planIntensity = plan?.recommendation.intensity;
  const label =
    planIntensity === "rest"
      ? "Rest & restore"
      : planIntensity === "low"
        ? "Active recovery"
        : verdict.label;
  const tone: VerdictTone = planIntensity === "rest" ? "negative" : verdict.tone;
  // Focus is deliberately omitted: the session strip prints it verbatim a
  // screen below, and the readiness score is the header HUD's job. This card
  // carries the one thing neither of those shows — why today looks like this.
  const rawFocus = plan?.recommendation.focus ?? "Today's training choice";
  const rationale = plan?.recommendation.rationale ?? state.gates.reasons[0] ?? state.gates.deload_reason;
  const detail = rationale
    ? shorten(rationale, 150)
    : shorten(rawFocus.split(" — ")[0] ?? rawFocus, 118);
  return { label, detail, tone };
}

function shorten(text: string, max: number): string {
  return text.length > max ? `${text.slice(0, max - 1).trim()}…` : text;
}
