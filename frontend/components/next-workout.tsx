"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "@/lib/api";
import { Eyebrow } from "@/components/ui/metric";
import { ObsidianMark } from "@/components/obsidian-badge";
import { CheckIcon, RefreshIcon, ArrowRightIcon, XIcon } from "@/components/ui/icons";
import type { WorkoutPlan, WorkoutBlock, WarmupItem, PlanExecution } from "@/lib/api";
import { ProgressionDrawer } from "@/components/progression-drawer";
import { CollapsibleSection } from "@/components/collapsible-section";

type PushState =
  | { kind: "idle" }
  | { kind: "pushing" }
  | { kind: "ok"; routineId: string; focus: string }
  | { kind: "err"; msg: string };

const toStringArray = (v: unknown): string[] =>
  Array.isArray(v) ? v : typeof v === "string" && v ? [v] : [];

// ── Tier config ──────────────────────────────────────────────────────────────

const TIER = {
  green: { color: "var(--positive)", soft: "var(--positive-soft)", border: "color-mix(in oklch, var(--positive) 25%, transparent)", icon: "▲", label: "Go hard" },
  yellow: { color: "var(--neutral)", soft: "var(--neutral-soft)", border: "color-mix(in oklch, var(--neutral) 25%, transparent)", icon: "◆", label: "Moderate effort" },
  red: { color: "var(--negative)", soft: "var(--negative-soft)", border: "color-mix(in oklch, var(--negative) 25%, transparent)", icon: "▼", label: "Rest / active recovery" },
} as const;

/** Local ISO date — `toISOString()` would roll over to tomorrow after 5pm PDT. */
const localToday = (): string => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};

const formatClock = (iso: string | null): string | null => {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
};

// ── Completed banner ─────────────────────────────────────────────────────────

/** Shown once a session on the plan's date has actually been logged against it.
 *  Until this existed the card kept presenting an executed plan as the day's
 *  action, and its pre-session loads read as a deload against what was lifted. */
function CompletedBanner({ ex }: { ex: PlanExecution }) {
  const start = formatClock(ex.started_at);
  const end = formatClock(ex.ended_at);
  return (
    <div
      className="rounded-[var(--r-md)] p-4 pl-5 flex gap-3 items-start"
      style={{
        background: "var(--positive-soft)",
        border: "1px solid color-mix(in oklch, var(--positive) 25%, transparent)",
      }}
    >
      <CheckIcon size={15} className="mt-0.5 flex-shrink-0" style={{ color: "var(--positive)" }} />
      <div className="min-w-0">
        <p className="text-[13px] font-semibold" style={{ color: "var(--positive)" }}>
          Session logged — this plan is done
        </p>
        <div className="flex items-center gap-2 flex-wrap text-[11px] text-[var(--text-dim)] tabular-nums mt-1">
          {start && <span>{start}{end ? `–${end}` : ""}</span>}
          {start && <span className="text-[var(--text-faint)]">·</span>}
          <span>
            {ex.sets_done} working {ex.sets_done === 1 ? "set" : "sets"}
            {ex.prescribed_sets > 0 && ` of ${ex.prescribed_sets} prescribed`}
            {ex.completion_pct != null && ` (${ex.completion_pct.toFixed(0)}%)`}
          </span>
          {ex.avg_rpe != null && <span className="text-[var(--text-faint)]">·</span>}
          {ex.avg_rpe != null && <span>avg RPE {ex.avg_rpe.toFixed(1)}</span>}
        </div>
        {ex.exercises.length > 0 && (
          <p className="text-[11.5px] text-[var(--text-muted)] leading-snug mt-1.5">
            {ex.exercises.join(" · ")}
          </p>
        )}
        <p className="text-[11px] text-[var(--text-faint)] leading-snug mt-2">
          The prescription below is what was written this morning, before the session —
          it is a record, not a target. Don&apos;t train it again off these loads.
        </p>
      </div>
    </div>
  );
}

// ── Session header ───────────────────────────────────────────────────────────

/** How hard today actually is — read off the prescription, not off the body.
 *
 *  `readiness_tier` describes RECOVERY: green means the body is fresh. It does
 *  not mean the session is hard. A calendar deload, a rest gate, or a capped
 *  `target_rpe` all produce an easy day on a green body, and keying the headline
 *  off the tier had the strip printing "▲ Go hard" directly above six sets of
 *  RPE 6 — the card contradicting itself in one glance. The old override caught
 *  only `low`/`rest`, so a deload sitting at `moderate` sailed straight through.
 *
 *  RPE outranks the coarse intensity enum: it is the scale the sets themselves
 *  are written on, so when the two disagree the sets win. */
function sessionEffort(plan: WorkoutPlan) {
  const { intensity, target_rpe: rpe } = plan.recommendation;

  if (intensity === "rest") return { ...TIER.red, label: "Rest / active recovery" };
  if (intensity === "low") return { ...TIER.red, label: "Active recovery" };
  if (plan.deload_prescribed)
    return { ...TIER.yellow, label: "Deload — leave reps in the tank" };
  if (rpe != null) {
    if (rpe < 7) return { ...TIER.yellow, label: "Easy — technique and pump" };
    if (rpe < 8.5) return { ...TIER.yellow, label: "Moderate effort" };
    return { ...TIER.green, label: "Go hard" };
  }
  if (intensity === "high") return { ...TIER.green, label: "Go hard" };
  return { ...TIER.yellow, label: "Moderate effort" };
}

/** The operational facts, one strip: how hard, at what, for how long.
 *  Everything a set needs; nothing it doesn't. The reasoning moved below the
 *  exercises — it was pushing the first lift two screens down on a phone. */
function SessionStrip({ plan }: { plan: WorkoutPlan }) {
  const t = sessionEffort(plan);
  const durationMin = plan.recommendation.estimated_duration_min;
  const rpe = plan.recommendation.target_rpe;
  // The recovery read is a real, separate fact, and the headline no longer
  // carries it. Stated plainly it explains the common green-body/capped-day
  // case instead of leaving the two numbers looking like a contradiction.
  const recovery = TIER[plan.readiness_tier] ?? TIER.yellow;
  return (
    <div
      className="rounded-[var(--r-md)] px-4 py-3"
      style={{ background: t.soft, border: `1px solid ${t.border}` }}
    >
      <div className="flex items-center gap-2.5 flex-wrap">
        <span
          className="w-7 h-7 rounded-full flex items-center justify-center text-[13px] font-bold flex-shrink-0"
          style={{ background: t.color, color: "var(--bg)" }}
        >
          {t.icon}
        </span>
        <span className="text-[15px] font-semibold leading-none" style={{ color: t.color }}>
          {t.label}
        </span>
        <div className="flex items-center gap-2.5 text-[11px] text-[var(--text-dim)] tabular-nums w-full sm:w-auto sm:ml-auto">
          {durationMin != null && (
            <>
              <span>~{durationMin} min</span>
              <span className="text-[var(--text-faint)]">•</span>
            </>
          )}
          {rpe != null && (
            <>
              <span>RPE {rpe}</span>
              <span className="text-[var(--text-faint)]">•</span>
            </>
          )}
          <span className="capitalize">{plan.recommendation.intensity}</span>
          <span className="text-[var(--text-faint)]">•</span>
          <span>
            recovery <span style={{ color: recovery.color }}>{plan.readiness_tier}</span>
          </span>
        </div>
      </div>
      {/* Focus gets its own line — as a flex sibling it collapsed to a ~90px
          column on a phone and wrapped to nine lines. */}
      <p className="mt-2 text-[12.5px] text-[var(--text-primary)] leading-snug">
        {plan.recommendation.focus}
      </p>
    </div>
  );
}

/** The readiness narrative and the WHY, below the work. */
function SessionRationale({ plan }: { plan: WorkoutPlan }) {
  const t = sessionEffort(plan);
  const snapshotAt = formatClock(plan.execution?.plan_created_at ?? null);
  if (!plan.readiness_summary && !plan.recommendation.rationale) return null;
  return (
    <div
      className="rounded-[var(--r-md)] overflow-hidden"
      style={{ background: t.soft, border: `1px solid ${t.border}` }}
    >
      <div className="p-5 flex gap-4 items-start">
        <div className="min-w-0 flex-1">
          {/* Both of these are omitted on some plans, which rendered an empty
              box and a bare "WHY" label with nothing after it. */}
          {plan.readiness_summary && (
          <p className="text-[12.5px] text-[var(--text-muted)] leading-relaxed">
            {plan.readiness_summary}
            {/* The narrative is a snapshot taken when the plan was written, and it
                sits a scroll away from the live readiness gauge. Without this stamp
                the two numbers read as a contradiction rather than as two times. */}
            {snapshotAt && (
              <span className="text-[10.5px] text-[var(--text-faint)] tabular-nums ml-1.5 whitespace-nowrap">
                (as of {snapshotAt})
              </span>
            )}
          </p>
          )}
          {plan.recommendation.rationale && (
            <p className="text-[11.5px] text-[var(--text-dim)] leading-snug italic mt-2">
              <span className="text-[var(--text-faint)] not-italic font-semibold uppercase tracking-wider text-[9.5px] mr-1.5">Why</span>
              {plan.recommendation.rationale}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Warmup ───────────────────────────────────────────────────────────────────

function WarmupSection({ items }: { items: WarmupItem[] }) {
  if (!items.length) return null;
  return (
    <div>
      <Eyebrow>Warm-up</Eyebrow>
      <div className="mt-2 space-y-1">
        {items.map((item, i) => (
          <div
            key={i}
            className="flex items-center gap-3 px-3 py-2 rounded-[var(--r-sm)]"
            style={{ background: "var(--card-hover)", border: "1px solid var(--hairline)" }}
          >
            <span className="text-[10.5px] text-[var(--text-faint)] w-5 text-center tabular-nums">{i + 1}</span>
            <span className="text-[12.5px] text-[var(--text-muted)] flex-1">{item.name}</span>
            <span className="text-[11px] text-[var(--text-dim)] tabular-nums">
              {item.sets && item.reps ? `${item.sets}×${item.reps}` : item.duration_sec ? `${item.duration_sec}s` : ""}
            </span>
            {item.notes && (
              <span className="text-[10.5px] text-[var(--text-faint)] max-w-[140px] text-right hidden sm:block">
                {item.notes}
              </span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

// ── RPE badge ────────────────────────────────────────────────────────────────

function RPEBadge({ rpe }: { rpe: number }) {
  const color = rpe >= 9 ? "var(--negative)" : rpe >= 7.5 ? "var(--neutral)" : "var(--sl-accent)";
  const soft = rpe >= 9 ? "var(--negative-soft)" : rpe >= 7.5 ? "var(--neutral-soft)" : "var(--sl-accent-soft)";
  return (
    <span
      className="inline-flex items-center px-1.5 py-0.5 rounded text-[10.5px] font-semibold tabular-nums"
      style={{ color, background: soft }}
    >
      {rpe}
    </span>
  );
}

// ── Exercise block ───────────────────────────────────────────────────────────

function ExerciseHistoryStamp({ name, prescribedLbs, modulated, executed }: { name: string; prescribedLbs?: number; modulated?: boolean; executed?: boolean }) {
  const { data, isLoading } = useQuery({
    queryKey: ["exercise-last", name],
    queryFn: () => api.trainingExerciseLast(name),
    staleTime: 10 * 60 * 1000,
    retry: 0,
  });
  if (isLoading) {
    return <span className="text-[10px] text-[var(--text-faint)]">history loading…</span>;
  }
  if (!data?.found || !data.weight_lbs) {
    return <span className="text-[10px] text-[var(--text-faint)]">first time</span>;
  }
  const days = Math.floor((Date.now() - new Date(data.date! + "T00:00:00").getTime()) / 86_400_000);
  const ago = days === 0 ? "today" : days === 1 ? "yesterday" : days < 14 ? `${days}d ago` : days < 60 ? `${Math.round(days / 7)}w ago` : `${Math.round(days / 30)}mo ago`;
  // Once the session has executed, "history" IS this session — differencing a
  // pre-session prescription against it renders a deload that was never
  // prescribed (the live case: 205 vs the 220 actually lifted, shown as −15).
  const delta = !executed && prescribedLbs != null ? prescribedLbs - data.weight_lbs : null;
  // On modulated-intensity days, a prescribed drop is intentional — use neutral not red.
  const deltaColor =
    delta == null ? "var(--text-faint)"
    : delta >= 5 ? "var(--positive)"
    : delta <= -5 ? (modulated ? "var(--neutral)" : "var(--negative)")
    : "var(--text-dim)";
  return (
    <div className="flex items-center gap-1.5 text-[10.5px] tabular-nums">
      <span className="text-[var(--text-faint)]">last</span>
      <span className="text-[var(--text-muted)] font-medium">{data.weight_lbs.toFixed(0)}<span className="text-[var(--text-faint)] font-normal ml-0.5">×{data.reps}</span></span>
      {data.rpe != null && <span className="text-[var(--text-faint)]">@ {data.rpe.toFixed(1)}</span>}
      <span className="text-[var(--text-faint)]">·</span>
      <span className="text-[var(--text-faint)]">{ago}</span>
      {delta != null && Math.abs(delta) >= 5 && (
        <span className="font-medium" style={{ color: deltaColor }}>
          ({delta > 0 ? "+" : ""}{delta.toFixed(0)} lbs)
        </span>
      )}
    </div>
  );
}

const BLOCK_ACCENT: Record<string, { bar: string; pill: string; pillBg: string }> = {
  primary: { bar: "var(--positive)", pill: "var(--positive)", pillBg: "var(--positive-soft)" },
  accessory: { bar: "var(--sl-accent)", pill: "var(--sl-accent)", pillBg: "var(--sl-accent-soft)" },
  finisher: { bar: "var(--neutral)", pill: "var(--neutral)", pillBg: "var(--neutral-soft)" },
  metabolic: { bar: "var(--neutral)", pill: "var(--neutral)", pillBg: "var(--neutral-soft)" },
  conditioning: { bar: "var(--neutral)", pill: "var(--neutral)", pillBg: "var(--neutral-soft)" },
  default: { bar: "var(--hairline-strong)", pill: "var(--text-muted)", pillBg: "var(--card-hover)" },
};

function blockAccent(label: string | undefined) {
  const k = (label ?? "").toLowerCase();
  if (k.includes("primary") || k.includes("compound") || k.includes("strength")) return BLOCK_ACCENT.primary;
  if (k.includes("accessory") || k.includes("hypertrophy")) return BLOCK_ACCENT.accessory;
  if (k.includes("finisher") || k.includes("metabolic")) return BLOCK_ACCENT.finisher;
  if (k.includes("conditioning") || k.includes("cardio") || k.includes("zone")) return BLOCK_ACCENT.conditioning;
  return BLOCK_ACCENT.default;
}

function ExerciseCard({
  ex,
  index,
  onPick,
  modulated,
  executed,
}: {
  ex: WorkoutBlock["exercises"][number];
  index: number;
  onPick: (n: string) => void;
  modulated?: boolean;
  executed?: boolean;
}) {
  const isSuperset = (ex.notes ?? "").toLowerCase().includes("superset");
  return (
    <button
      onClick={() => onPick(ex.name)}
      className="group relative w-full text-left rounded-[var(--r-md)] p-4 transition-all hover:translate-y-[-1px] focus:outline-none"
      style={{
        background: "var(--card-hover)",
        border: "1px solid var(--hairline)",
        boxShadow: "var(--shadow-flat)",
      }}
    >
      {isSuperset && index > 0 && (
        <div
          className="absolute -top-3 left-6 px-2 py-0.5 rounded-full text-[9px] font-semibold tracking-wider uppercase"
          style={{
            background: "var(--neutral-soft)",
            border: "1px solid color-mix(in oklch, var(--neutral) 30%, transparent)",
            color: "var(--neutral)",
          }}
        >
          + Superset
        </div>
      )}

      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 mb-2">
            <span className="text-[10px] tabular-nums w-5 text-center font-mono text-[var(--text-faint)]">
              {String(index + 1).padStart(2, "0")}
            </span>
            {/* Wraps rather than truncates: the exercise name is the thing you
                match against the machine in front of you, and "Hammerstrength
                Incline Che…" is not that. */}
            <h4 className="text-[14px] font-semibold text-[var(--text-primary)] leading-snug">{ex.name}</h4>
          </div>

          <div className="ml-7 flex items-baseline gap-3 flex-wrap mb-2">
            <div className="flex items-baseline gap-1.5">
              <span className="text-[24px] font-light tabular-nums leading-none text-[var(--text-primary)]">
                {ex.sets}
              </span>
              <span className="text-[12px] text-[var(--text-faint)]">×</span>
              <span className="text-[24px] font-light tabular-nums leading-none text-[var(--text-primary)]">
                {ex.reps}
              </span>
              <span className="text-[10px] text-[var(--text-faint)] uppercase tracking-wider ml-0.5">sets×reps</span>
            </div>

            {ex.weight_lbs ? (
              <div className="flex items-baseline gap-1.5">
                <span className="text-[24px] font-light tabular-nums leading-none text-[var(--text-primary)]">
                  {ex.weight_lbs}
                </span>
                <span className="text-[10px] text-[var(--text-faint)] uppercase tracking-wider">lbs</span>
              </div>
            ) : (
              <span className="text-[14px] text-[var(--text-faint)]">bodyweight</span>
            )}

            <div className="flex items-baseline gap-1">
              <span className="text-[10px] text-[var(--text-faint)] uppercase tracking-wider">RPE</span>
              <RPEBadge rpe={ex.rpe_target} />
            </div>

            {ex.rest_seconds != null && (
              <div className="flex items-baseline gap-1">
                <span className="text-[10px] text-[var(--text-faint)] uppercase tracking-wider">rest</span>
                <span className="text-[14px] font-light tabular-nums text-[var(--text-dim)]">
                  {ex.rest_seconds >= 60
                    ? `${Math.round(ex.rest_seconds / 60)}m`
                    : `${ex.rest_seconds}s`}
                </span>
              </div>
            )}
          </div>

          <div className="ml-7">
            <ExerciseHistoryStamp name={ex.name} prescribedLbs={ex.weight_lbs} modulated={modulated} executed={executed} />
          </div>

          {ex.notes && !isSuperset && (
            <p className="ml-7 mt-2 text-[12px] text-[var(--text-muted)] leading-snug">
              <span className="text-[var(--text-dim)] uppercase tracking-wider text-[9.5px] mr-1.5">Cue</span>
              {ex.notes}
            </p>
          )}
        </div>

        <span className="text-[var(--text-faint)] text-[14px] mt-1 opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0">
          ↗
        </span>
      </div>
    </button>
  );
}

function ExerciseBlock({ block, onPick, modulated, executed }: { block: WorkoutBlock; onPick: (ex: string) => void; modulated?: boolean; executed?: boolean }) {
  const accent = blockAccent(block.label);
  return (
    <section className="space-y-2.5">
      <div className="flex items-center gap-2.5">
        <div className="h-3 w-1 rounded-full" style={{ background: accent.bar }} />
        <h3 className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[var(--text-primary)]">
          {block.label}
        </h3>
        <span className="text-[10.5px] text-[var(--text-faint)] tabular-nums">
          {(block.exercises ?? []).length} {block.exercises?.length === 1 ? "exercise" : "exercises"}
        </span>
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        {(block.exercises ?? []).map((ex, i) => (
          <ExerciseCard key={i} ex={ex} index={i} onPick={onPick} modulated={modulated} executed={executed} />
        ))}
      </div>
    </section>
  );
}

// ── Clinical callout ─────────────────────────────────────────────────────────

function ClinicalCallout({ notes }: { notes: string[] }) {
  if (!notes.length) return null;
  return (
    <div
      className="rounded-[var(--r-md)] p-4 pl-5"
      style={{
        background: "var(--card-hover)",
        border: "1px solid var(--hairline)",
        borderLeft: "2px solid var(--neutral)",
      }}
    >
      <div className="flex items-center gap-2 mb-2.5">
        <Eyebrow>Clinical considerations</Eyebrow>
      </div>
      <ul className="space-y-1.5">
        {notes.map((n, i) => (
          <li key={i} className="text-[12px] text-[var(--text-muted)] leading-snug flex gap-2">
            <span className="text-[var(--neutral)] mt-0.5 flex-shrink-0 opacity-60">·</span>
            {n}
          </li>
        ))}
      </ul>
    </div>
  );
}

// ── Evidence base ─────────────────────────────────────────────────────────────

function VaultInsights({ insights }: { insights: string[] }) {
  if (!insights.length) return null;
  return (
    <div
      className="rounded-[var(--r-md)] p-4 pl-5"
      style={{
        background: "var(--card-hover)",
        border: "1px solid var(--hairline)",
        borderLeft: "2px solid var(--sl-accent)",
      }}
    >
      <div className="flex items-center gap-2 mb-2.5">
        <ObsidianMark size={13} />
        <Eyebrow>From your vault</Eyebrow>
      </div>
      <ul className="space-y-1.5">
        {insights.map((n, i) => (
          <li key={i} className="text-[12px] text-[var(--text-dim)] leading-snug flex gap-2">
            <span className="mt-0.5 flex-shrink-0 opacity-60" style={{ color: "var(--sl-accent)" }}>·</span>
            {n}
          </li>
        ))}
      </ul>
    </div>
  );
}

// ── Cooldown ─────────────────────────────────────────────────────────────────

function CooldownRow({ text }: { text: string | unknown }) {
  const str = typeof text === "string" ? text : Array.isArray(text) ? (text as {name?:string}[]).map(i => i.name ?? "").filter(Boolean).join(" · ") : "";
  if (!str) return null;
  // rebind for JSX below
  const text2 = str;
  return (
    <div
      className="flex gap-3 px-4 py-3 rounded-[var(--r-md)]"
      style={{ background: "var(--card-hover)", border: "1px solid var(--hairline)" }}
    >
      <span className="text-[var(--text-faint)] text-sm mt-0.5">↓</span>
      <div>
        <Eyebrow>Cool-down</Eyebrow>
        <p className="text-[12px] text-[var(--text-dim)] mt-1 leading-snug">{text2}</p>
      </div>
    </div>
  );
}

// ── Skeleton ─────────────────────────────────────────────────────────────────

function Skeleton() {
  return (
    <div className="space-y-4">
      {[20, 32, 48, 48, 20].map((h, i) => (
        <div
          key={i}
          className="rounded-[var(--r-md)] animate-pulse"
          style={{ height: `${h * 4}px`, background: "var(--card-hover)" }}
        />
      ))}
    </div>
  );
}

// ── Main ─────────────────────────────────────────────────────────────────────

export function NextWorkoutPane() {
  const queryClient = useQueryClient();
  const [regenKey, setRegenKey] = useState(0);
  const [push, setPush] = useState<PushState>({ kind: "idle" });
  const [picked, setPicked] = useState<string | null>(null);

  const { data, isLoading, isError, isFetching } = useQuery({
    queryKey: ["workout-next", regenKey],
    queryFn: () => api.workoutNext(regenKey > 0),
    staleTime: 1000 * 60 * 60,
    retry: 1,
  });

  function handleRegen() {
    setRegenKey((k) => k + 1);
    queryClient.removeQueries({ queryKey: ["workout-next"] });
    setPush({ kind: "idle" });
  }

  async function handlePushHevy() {
    setPush({ kind: "pushing" });
    try {
      const r = await api.hevyPushRoutine(false);
      setPush({ kind: "ok", routineId: r.routine_id, focus: r.plan_focus });
    } catch (e) {
      setPush({ kind: "err", msg: e instanceof Error ? e.message : "push failed" });
    }
  }

  async function handleDiscard() {
    if (!confirm("Discard today's plan and regenerate from current readiness?")) return;
    try {
      await api.workoutDelete();
    } catch {
      /* even if 404, force a refetch */
    }
    handleRegen();
  }

  // A plan is only "today's" while it is still the day's action. Once a session
  // has executed it — or once it has been carried over from an earlier date —
  // it is history, and its pre-session loads must not read as a prescription.
  const execution = data?.execution;
  const executed = execution?.executed === true;
  const planDate = execution?.plan_date ?? data?.generated_at ?? null;
  const carried = planDate != null && planDate < localToday();
  const title = executed ? "Completed" : carried ? "Last Plan" : "Today's Plan";

  const planBody = data ? (
    <>
      <SessionStrip plan={data} />
      <WarmupSection items={data.warmup ?? []} />
      {(data.blocks ?? []).map((block, i) => (
        <ExerciseBlock
          key={i}
          block={block}
          onPick={setPicked}
          modulated={data.recommendation?.intensity === "low" || data.recommendation?.intensity === "rest"}
          executed={executed}
        />
      ))}
      <CooldownRow text={data.cooldown ?? ""} />
      <CollapsibleSection id="why" title="Why this session">
        <div className="space-y-4">
          <SessionRationale plan={data} />
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <ClinicalCallout notes={toStringArray(data.clinical_notes)} />
            <VaultInsights insights={toStringArray(data.vault_insights)} />
          </div>
        </div>
      </CollapsibleSection>
    </>
  ) : null;

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-end justify-between flex-wrap gap-3 pb-1">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-[20px] font-semibold tracking-tight text-[var(--text-primary)] leading-none">
              {title}
            </h2>
            {(executed || carried) && (
              <span
                className="text-[9.5px] font-semibold uppercase tracking-[0.16em] px-2 py-0.5 rounded-full"
                style={
                  executed
                    ? { background: "var(--positive-soft)", color: "var(--positive)", border: "1px solid color-mix(in oklch, var(--positive) 25%, transparent)" }
                    : { background: "var(--neutral-soft)", color: "var(--neutral)", border: "1px solid color-mix(in oklch, var(--neutral) 25%, transparent)" }
                }
              >
                {executed ? "Trained" : "Not today's"}
              </span>
            )}
          </div>
          {data && (
            <div className="flex items-center gap-2 mt-2">
              <span className="text-[11px] text-[var(--text-dim)] tabular-nums">
                {new Date(data.generated_at + "T00:00:00").toLocaleDateString("en-US", {
                  weekday: "long", month: "short", day: "numeric",
                })}
              </span>
              <span className="text-[var(--text-faint)]">·</span>
              <span
                className="inline-flex items-center gap-1.5 text-[10px] tracking-wide"
                style={{ color: "var(--text-dim)" }}
                title={
                  data.source === "claude_code" || data.source === "claude"
                    ? "Plan generated by AI"
                    : data.source === "fallback"
                      ? "Auto-generated fallback plan"
                      : `Source: ${data.source}`
                }
              >
                <span
                  className="inline-block w-1 h-1 rounded-full"
                  style={{
                    background:
                      data.source === "claude" || data.source === "claude_code"
                        ? "var(--sl-accent)"
                        : data.source === "fallback"
                          ? "var(--text-faint)"
                          : "var(--neutral)",
                  }}
                />
                {data.source === "claude_code" || data.source === "claude"
                  ? "AI"
                  : data.source === "fallback"
                    ? "Fallback"
                    : data.source}
              </span>
              <span className="text-[10px] text-[var(--text-faint)]">
                Goal: <span className="text-[var(--text-muted)] font-medium">build muscle · recomp</span>
              </span>
            </div>
          )}
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          {/* Push plan to Hevy */}
          <button
            onClick={handlePushHevy}
            disabled={push.kind === "pushing" || !data || executed}
            className={push.kind === "ok" ? "btn btn-primary" : "btn btn-secondary"}
            title={
              executed
                ? "Already trained — pushing this plan would re-prescribe pre-session loads"
                : "Push today's plan to Hevy as a routine"
            }
          >
            <span className={push.kind === "pushing" ? "animate-spin inline-block" : ""}>
              {push.kind === "pushing" ? <RefreshIcon size={13} /> : push.kind === "ok" ? <CheckIcon size={13} /> : <ArrowRightIcon size={13} />}
            </span>
            {push.kind === "pushing" ? "Pushing…" : push.kind === "ok" ? "In Hevy" : "Hevy"}
          </button>

          {/* Discard */}
          <button
            onClick={handleDiscard}
            disabled={isFetching || !data}
            className="btn btn-ghost"
            style={{ padding: "8px 10px" }}
            title="Delete today's plan"
          >
            <XIcon size={13} />
          </button>
        </div>
      </div>

      {push.kind === "err" && (
        <div
          className="rounded-[var(--r-sm)] px-3 py-2 text-[11px]"
          style={{ background: "var(--negative-soft)", border: "1px solid color-mix(in oklch, var(--negative) 25%, transparent)", color: "var(--negative)" }}
        >
          Hevy push failed: {push.msg}
        </div>
      )}
      {push.kind === "ok" && (
        <div
          className="rounded-[var(--r-sm)] px-3 py-2 text-[11px]"
          style={{ background: "var(--positive-soft)", border: "1px solid color-mix(in oklch, var(--positive) 25%, transparent)", color: "var(--positive)" }}
        >
          <CheckIcon size={11} className="inline mr-1 align-middle" />{push.focus} routine ready in Hevy (id {push.routineId.slice(0, 8)}…). Open the app to start.
        </div>
      )}

      {isLoading && <Skeleton />}

      {isError && (
        <div
          className="rounded-[var(--r-md)] p-6 text-center"
          style={{ background: "var(--negative-soft)", border: "1px solid color-mix(in oklch, var(--negative) 20%, transparent)" }}
        >
          <p className="text-sm text-[var(--negative)]">Could not generate workout plan</p>
          <p className="text-[11px] text-[var(--text-dim)] mt-1">
            Ensure backend and Ollama are running
          </p>
        </div>
      )}

      {data && (
        <div className="space-y-5">
          {executed && execution && <CompletedBanner ex={execution} />}
          {/* Work first, reasoning after. Mid-set the useful payload is the load
              and the rep target; the readiness narrative and the WHY are a
              before-or-after read, and putting them on top meant scrolling past
              ~15 lines of prose to reach the first lift on a phone.

              Once the session is EXECUTED this whole stack is a record, not an
              action — and rendering it in full cost ~3,300px of the page on any
              day already trained, with the banner above it explicitly saying not
              to train off these loads. It now collapses to the banner plus a
              disclosure. */}
          {executed ? (
            <CollapsibleSection
              id="executed-plan"
              title="What was prescribed this morning"
              hint="record — not a target"
            >
              <div className="space-y-5" style={{ opacity: 0.7 }}>
                {planBody}
              </div>
            </CollapsibleSection>
          ) : (
            <div className="space-y-5">{planBody}</div>
          )}
        </div>
      )}

      <ProgressionDrawer exercise={picked} onClose={() => setPicked(null)} />
    </div>
  );
}
