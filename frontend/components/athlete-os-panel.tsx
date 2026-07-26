"use client";

import { useQuery } from "@tanstack/react-query";
import { api, type DailyState, type Experiment, type WorkoutPlan } from "@/lib/api";
import { reconciledVerdict, type VerdictTone } from "@/lib/readiness";
import { Eyebrow } from "@/components/ui/metric";

function toneColor(tone: VerdictTone): string {
  if (tone === "positive") return "var(--positive)";
  if (tone === "negative") return "var(--negative)";
  return "var(--neutral)";
}

function readinessCommand(state: DailyState | undefined, plan: WorkoutPlan | undefined): {
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

function goalPressure(state: DailyState | undefined): { label: string; detail: string; tone: VerdictTone } {
  if (!state) return { label: "Goal pressure", detail: "Waiting for training load.", tone: "neutral" };
  const load = state.training_load;
  if (load.pickleball_min_7d >= 150) {
    return {
      label: "Court load is high",
      detail: `${Math.round(load.pickleball_min_7d)} pickleball minutes this week; preserve lower-body power.`,
      tone: "neutral",
    };
  }
  if ((load.push_pull_ratio_28d ?? 1) < 0.8) {
    return {
      label: "Pull volume lagging",
      detail: `Push:pull is ${load.push_pull_ratio_28d?.toFixed(2)}; bias back, lats, rear delts.`,
      tone: "neutral",
    };
  }
  if ((load.push_pull_ratio_28d ?? 1) > 1.2) {
    return {
      label: "Push volume dominant",
      detail: `Push:pull is ${load.push_pull_ratio_28d?.toFixed(2)}; protect shoulders with pulling volume.`,
      tone: "neutral",
    };
  }
  return {
    label: "Build window open",
    detail: `${load.push_sets_28d}/${load.pull_sets_28d}/${load.legs_sets_28d} push/pull/legs sets over 28d.`,
    tone: "positive",
  };
}

function activeExperiment(experiments: Experiment[] | undefined): { label: string; detail: string; tone: VerdictTone } {
  const active = experiments?.find((e) => e.status === "active") ?? experiments?.[0];
  if (!active) {
    return {
      label: "No active intervention",
      detail: "Register one small behavior change and let the system measure it.",
      tone: "neutral",
    };
  }
  const a = active.arms.A?.adhered ?? 0;
  const b = active.arms.B?.adhered ?? 0;
  const done = Math.min(a, b);
  const pct = Math.min(100, Math.round((done / Math.max(1, active.min_per_arm)) * 100));
  return {
    label: active.result?.verdict ?? "Experiment running",
    detail: `${active.manipulated}: ${pct}% to minimum balanced N for ${shorten(active.outcome_metric, 40)}.`,
    tone: active.result?.verdict === "CONFIRMED" ? "positive" : "neutral",
  };
}

function findingSignal(
  findings: Awaited<ReturnType<typeof api.labFindings>> | undefined,
): { label: string; detail: string; tone: VerdictTone } {
  const confirmed = findings?.find((f) => f.verdict === "confirmed");
  const suggestive = findings?.find((f) => f.verdict === "inconclusive" && (f.n ?? 0) >= 50);
  const f = confirmed ?? suggestive;
  if (!f) {
    return {
      label: "Evidence still accumulating",
      detail: "Personal hypotheses are being tracked, but none are decisive today.",
      tone: "neutral",
    };
  }
  return {
    label: confirmed ? "Personal effect confirmed" : "Signal worth watching",
    detail: shorten(f.summary ?? f.hypothesis, 150),
    tone: confirmed ? "positive" : "neutral",
  };
}

function freshnessLabel(days: number | null | undefined): string {
  if (days == null) return "missing";
  if (days === 0) return "fresh";
  if (days === 1) return "1d";
  return `${days}d`;
}

/** Source freshness — status, not a decision, so it reads as one quiet line
 *  rather than the 2×2 grid of boxes that used to sit above today's call. */
function SignalPill({ label, value }: { label: string; value: string }) {
  const stale = value !== "fresh" && value !== "1d";
  return (
    <span className="inline-flex items-baseline gap-1 whitespace-nowrap">
      <span className="text-[9px] uppercase tracking-[0.14em] text-[var(--text-faint)]">{label}</span>
      <span
        className="text-[11px] tabular-nums"
        style={{ color: stale ? "var(--neutral)" : "var(--text-muted)" }}
      >
        {value}
      </span>
    </span>
  );
}

function DecisionCard({
  eyebrow,
  label,
  detail,
  tone,
}: {
  eyebrow: string;
  label: string;
  detail: string;
  tone: VerdictTone;
}) {
  const color = toneColor(tone);
  return (
    <div
      className="rounded-lg border p-3 h-full"
      style={{ borderColor: "var(--hairline)", background: "oklch(1 0 0 / 0.025)" }}
    >
      <p className="text-[9.5px] uppercase tracking-[0.16em] text-[var(--text-faint)]">{eyebrow}</p>
      <p className="mt-1 text-[14.5px] font-semibold leading-tight" style={{ color }}>
        {label}
      </p>
      <p className="mt-1.5 text-[11.5px] leading-snug text-[var(--text-muted)]">{detail}</p>
    </div>
  );
}

export function AthleteOSPanel() {
  const state = useQuery({ queryKey: ["daily-state"], queryFn: api.dailyState, staleTime: 5 * 60_000 });
  const plan = useQuery({ queryKey: ["workout-next"], queryFn: () => api.workoutNext(false), staleTime: 5 * 60_000 });
  const findings = useQuery({ queryKey: ["lab-findings"], queryFn: api.labFindings, staleTime: 60_000 });
  const experiments = useQuery({ queryKey: ["experiments"], queryFn: api.experiments, staleTime: 60_000 });

  const command = readinessCommand(state.data, plan.data);
  const pressure = goalPressure(state.data);
  const experiment = activeExperiment(experiments.data);
  const finding = findingSignal(findings.data);
  const freshness = state.data?.freshness;

  return (
    <section
      className="shc-card shc-enter p-5 border-l-[3px]"
      style={{ borderLeftColor: "var(--sl-accent)" }}
    >
      {/* The product manifesto that used to sit here ("Lab thinking, consumer
          sensors, daily action" + the NSRL-loop paragraph) is written for a
          first-time visitor and lives in the README. On the daily surface it
          cost the top of every screen — on a phone it pushed today's command
          ~1,300px down — to tell the only user something he already knows. */}
      <div className="flex items-baseline justify-between gap-4 flex-wrap">
        <Eyebrow>Today</Eyebrow>
        <div className="flex items-baseline gap-3 flex-wrap">
          <SignalPill label="WHOOP" value={freshnessLabel(freshness?.whoop_age_days)} />
          <SignalPill label="Sleep" value={freshnessLabel(freshness?.sleep_age_days)} />
          <SignalPill label="Hevy" value={freshnessLabel(freshness?.hevy_age_days)} />
          <SignalPill label="Cardio" value={freshnessLabel(freshness?.cardio_age_days)} />
        </div>
      </div>

      {/* The command spans the row on phones; the three context cards pair up
          beneath it. Four equal full-width cards put the session ~1,100px down. */}
      <div className="mt-3 grid grid-cols-2 xl:grid-cols-4 gap-3">
        <div className="col-span-2 xl:col-span-1">
          <DecisionCard eyebrow="today's command" {...command} />
        </div>
        <DecisionCard eyebrow="goal pressure" {...pressure} />
        <DecisionCard eyebrow="intervention loop" {...experiment} />
        <div className="col-span-2 xl:col-span-1">
          <DecisionCard eyebrow="personal evidence" {...finding} />
        </div>
      </div>
    </section>
  );
}
