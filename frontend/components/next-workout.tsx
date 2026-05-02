"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "@/lib/api";
import { Eyebrow } from "@/components/ui/metric";
import type { WorkoutPlan, WorkoutBlock, WarmupItem } from "@/lib/api";
import { ProgressionDrawer } from "@/components/progression-drawer";

type PushState =
  | { kind: "idle" }
  | { kind: "pushing" }
  | { kind: "ok"; routineId: string; focus: string }
  | { kind: "err"; msg: string };

const toStringArray = (v: unknown): string[] =>
  Array.isArray(v) ? v : typeof v === "string" && v ? [v] : [];

// ── Tier config ──────────────────────────────────────────────────────────────

const TIER = {
  green: { color: "var(--positive)", soft: "var(--positive-soft)", border: "oklch(0.72 0.18 145 / 0.25)", icon: "▲", label: "Go hard" },
  yellow: { color: "var(--neutral)", soft: "var(--neutral-soft)", border: "oklch(0.75 0.18 75 / 0.25)", icon: "◆", label: "Moderate effort" },
  red: { color: "var(--negative)", soft: "var(--negative-soft)", border: "oklch(0.65 0.22 25 / 0.25)", icon: "▼", label: "Rest / active recovery" },
} as const;

// ── Readiness banner ─────────────────────────────────────────────────────────

function ReadinessBanner({ plan }: { plan: WorkoutPlan }) {
  const t = TIER[plan.readiness_tier] ?? TIER.yellow;
  return (
    <div
      className="rounded-[var(--r-md)] overflow-hidden"
      style={{ background: t.soft, border: `1px solid ${t.border}` }}
    >
      <div className="p-5 flex gap-4 items-start">
        <div
          className="w-12 h-12 rounded-full flex items-center justify-center text-lg font-bold flex-shrink-0"
          style={{ background: t.color, color: "oklch(0.1 0 0)", boxShadow: "0 0 0 4px oklch(1 0 0 / 0.04)" }}
        >
          {t.icon}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline gap-2 flex-wrap mb-1">
            <span className="text-[18px] font-semibold leading-none" style={{ color: t.color }}>
              {t.label}
            </span>
            <span
              className="text-[10px] font-semibold uppercase tracking-[0.18em] px-2 py-0.5 rounded-full"
              style={{ background: "oklch(1 0 0 / 0.06)", color: "var(--text-primary)", border: "1px solid var(--hairline)" }}
            >
              {plan.recommendation.focus}
            </span>
          </div>
          <div className="flex items-center gap-3 text-[11px] text-[var(--text-dim)] tabular-nums mb-3">
            <span>~{plan.recommendation.estimated_duration_min} min</span>
            <span className="text-[var(--text-faint)]">•</span>
            <span>Target RPE {plan.recommendation.target_rpe}</span>
            <span className="text-[var(--text-faint)]">•</span>
            <span className="capitalize">{plan.recommendation.intensity} intensity</span>
          </div>
          <p className="text-[12.5px] text-[var(--text-muted)] leading-relaxed">
            {plan.readiness_summary}
          </p>
          <p className="text-[11.5px] text-[var(--text-dim)] leading-snug italic mt-2">
            <span className="text-[var(--text-faint)] not-italic font-semibold uppercase tracking-wider text-[9.5px] mr-1.5">Why</span>
            {plan.recommendation.rationale}
          </p>
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
            style={{ background: "oklch(1 0 0 / 0.025)", border: "1px solid var(--hairline)" }}
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
  const color = rpe >= 9 ? "var(--negative)" : rpe >= 7.5 ? "var(--neutral)" : "var(--chart-line)";
  const soft = rpe >= 9 ? "var(--negative-soft)" : rpe >= 7.5 ? "var(--neutral-soft)" : "oklch(0.72 0.12 250 / 0.12)";
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

function ExerciseHistoryStamp({ name, prescribedLbs }: { name: string; prescribedLbs?: number }) {
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
  const delta = prescribedLbs != null ? prescribedLbs - data.weight_lbs : null;
  const deltaColor =
    delta == null ? "var(--text-faint)"
    : delta >= 5 ? "var(--positive)"
    : delta <= -5 ? "var(--negative)"
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
  accessory: { bar: "var(--chart-line)", pill: "var(--chart-line)", pillBg: "oklch(0.72 0.12 250 / 0.12)" },
  finisher: { bar: "var(--neutral)", pill: "var(--neutral)", pillBg: "var(--neutral-soft)" },
  metabolic: { bar: "var(--neutral)", pill: "var(--neutral)", pillBg: "var(--neutral-soft)" },
  conditioning: { bar: "oklch(0.78 0.18 75)", pill: "oklch(0.78 0.18 75)", pillBg: "var(--neutral-soft)" },
  default: { bar: "var(--hairline-strong)", pill: "var(--text-muted)", pillBg: "oklch(1 0 0 / 0.04)" },
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
}: {
  ex: WorkoutBlock["exercises"][number];
  index: number;
  onPick: (n: string) => void;
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
            border: "1px solid oklch(0.75 0.18 75 / 0.3)",
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
            <h4 className="text-[14px] font-semibold text-[var(--text-primary)] truncate">{ex.name}</h4>
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
            <ExerciseHistoryStamp name={ex.name} prescribedLbs={ex.weight_lbs} />
          </div>

          {ex.notes && !isSuperset && (
            <p className="ml-7 mt-2 text-[11px] text-[var(--text-dim)] leading-snug">
              <span className="text-[var(--text-faint)] uppercase tracking-wider text-[9.5px] mr-1.5">Cue</span>
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

function ExerciseBlock({ block, onPick }: { block: WorkoutBlock; onPick: (ex: string) => void }) {
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
          <ExerciseCard key={i} ex={ex} index={i} onPick={onPick} />
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
        background: "oklch(1 0 0 / 0.015)",
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
        background: "oklch(1 0 0 / 0.015)",
        border: "1px solid var(--hairline)",
        borderLeft: "2px solid var(--chart-line)",
      }}
    >
      <div className="flex items-center gap-2 mb-2.5">
        <Eyebrow>Evidence base</Eyebrow>
      </div>
      <ul className="space-y-1.5">
        {insights.map((n, i) => (
          <li key={i} className="text-[12px] text-[var(--text-dim)] leading-snug flex gap-2">
            <span className="text-[var(--chart-line)] mt-0.5 flex-shrink-0 opacity-60">·</span>
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
      style={{ background: "oklch(1 0 0 / 0.02)", border: "1px solid var(--hairline)" }}
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
          style={{ height: `${h * 4}px`, background: "oklch(1 0 0 / 0.04)" }}
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


  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-end justify-between flex-wrap gap-3 pb-1">
        <div>
          <h2 className="text-[20px] font-semibold tracking-tight text-[var(--text-primary)] leading-none">
            Today&apos;s Plan
          </h2>
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
                        ? "var(--chart-line)"
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
                Goal: <span className="text-[var(--text-muted)] font-medium">strength + fat loss</span>
              </span>
            </div>
          )}
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          {/* Push plan to Hevy */}
          <button
            onClick={handlePushHevy}
            disabled={push.kind === "pushing" || !data}
            className={push.kind === "ok" ? "btn btn-primary" : "btn btn-secondary"}
            title="Push today's plan to Hevy as a routine"
          >
            <span className={push.kind === "pushing" ? "animate-spin inline-block" : ""}>
              {push.kind === "pushing" ? "⟳" : push.kind === "ok" ? "✓" : "→"}
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
            ✕
          </button>
        </div>
      </div>

      {push.kind === "err" && (
        <div
          className="rounded-[var(--r-sm)] px-3 py-2 text-[11px]"
          style={{ background: "var(--negative-soft)", border: "1px solid oklch(0.65 0.22 25 / 0.25)", color: "var(--negative)" }}
        >
          Hevy push failed: {push.msg}
        </div>
      )}
      {push.kind === "ok" && (
        <div
          className="rounded-[var(--r-sm)] px-3 py-2 text-[11px]"
          style={{ background: "var(--positive-soft)", border: "1px solid oklch(0.72 0.18 145 / 0.25)", color: "var(--positive)" }}
        >
          ✓ {push.focus} routine ready in Hevy (id {push.routineId.slice(0, 8)}…). Open the app to start.
        </div>
      )}

      {isLoading && <Skeleton />}

      {isError && (
        <div
          className="rounded-[var(--r-md)] p-6 text-center"
          style={{ background: "var(--negative-soft)", border: "1px solid oklch(0.65 0.22 25 / 0.2)" }}
        >
          <p className="text-sm text-[var(--negative)]">Could not generate workout plan</p>
          <p className="text-[11px] text-[var(--text-dim)] mt-1">
            Ensure backend and Ollama are running
          </p>
        </div>
      )}

      {data && (
        <div className="space-y-5">
          <ReadinessBanner plan={data} />
          <WarmupSection items={data.warmup ?? []} />
          {(data.blocks ?? []).map((block, i) => (
            <ExerciseBlock key={i} block={block} onPick={setPicked} />
          ))}
          <CooldownRow text={data.cooldown ?? ""} />
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <ClinicalCallout notes={toStringArray(data.clinical_notes)} />
            <VaultInsights insights={toStringArray(data.vault_insights)} />
          </div>
        </div>
      )}

      <ProgressionDrawer exercise={picked} onClose={() => setPicked(null)} />
    </div>
  );
}
