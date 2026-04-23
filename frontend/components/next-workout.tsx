"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "@/lib/api";
import { Eyebrow } from "@/components/ui/metric";
import type { WorkoutPlan, WorkoutBlock, WarmupItem } from "@/lib/api";

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
      className="rounded-[var(--r-md)] p-4 flex gap-3 items-start"
      style={{ background: t.soft, border: `1px solid ${t.border}` }}
    >
      <div
        className="w-9 h-9 rounded-full flex items-center justify-center text-base font-bold flex-shrink-0 mt-0.5"
        style={{ background: t.color, color: "oklch(0.1 0 0)" }}
      >
        {t.icon}
      </div>
      <div className="min-w-0 space-y-1">
        <div className="flex items-baseline gap-2 flex-wrap">
          <span className="text-[12.5px] font-semibold" style={{ color: t.color }}>
            {t.label}
          </span>
          <span className="text-[11px] text-[var(--text-dim)] uppercase tracking-wide font-medium">
            {plan.recommendation.focus}
          </span>
          <span className="text-[11px] text-[var(--text-faint)] tabular-nums">
            ~{plan.recommendation.estimated_duration_min} min · RPE {plan.recommendation.target_rpe}
          </span>
        </div>
        <p className="text-[12px] text-[var(--text-muted)] leading-relaxed">
          {plan.readiness_summary}
        </p>
        <p className="text-[11px] text-[var(--text-dim)] leading-snug italic">
          {plan.recommendation.rationale}
        </p>
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

function ExerciseTable({ block }: { block: WorkoutBlock }) {
  return (
    <div>
      <Eyebrow>{block.label}</Eyebrow>
      <div className="mt-2 rounded-[var(--r-md)] overflow-hidden" style={{ border: "1px solid var(--hairline)" }}>
        <table className="w-full text-[12px]">
          <thead>
            <tr className="text-[10px] text-[var(--text-faint)] uppercase tracking-wider" style={{ borderBottom: "1px solid var(--hairline)" }}>
              <th className="px-3 py-2 text-left font-normal">Exercise</th>
              <th className="px-3 py-2 text-center font-normal w-12">Sets</th>
              <th className="px-3 py-2 text-center font-normal w-14">Reps</th>
              <th className="px-3 py-2 text-right font-normal w-20">Weight</th>
              <th className="px-3 py-2 text-center font-normal w-14">RPE</th>
              <th className="px-3 py-2 text-left font-normal hidden md:table-cell">Notes</th>
            </tr>
          </thead>
          <tbody>
            {block.exercises.map((ex, i) => (
              <tr
                key={i}
                className="hover:bg-[var(--card-hover)] transition-colors"
                style={{ borderBottom: i < block.exercises.length - 1 ? "1px solid var(--hairline)" : "none" }}
              >
                <td className="px-3 py-2.5 font-medium text-[var(--text-primary)]">{ex.name}</td>
                <td className="px-3 py-2.5 text-center tabular-nums text-[var(--text-muted)]">{ex.sets}</td>
                <td className="px-3 py-2.5 text-center tabular-nums text-[var(--text-muted)]">{ex.reps}</td>
                <td className="px-3 py-2.5 text-right tabular-nums">
                  {ex.weight_lbs ? (
                    <span className="text-[var(--text-primary)] font-semibold">
                      {ex.weight_lbs}
                      <span className="text-[var(--text-faint)] font-normal ml-0.5 text-[10.5px]">lbs</span>
                    </span>
                  ) : (
                    <span className="text-[var(--text-faint)]">BW</span>
                  )}
                </td>
                <td className="px-3 py-2.5 text-center">
                  <RPEBadge rpe={ex.rpe_target} />
                </td>
                <td className="px-3 py-2.5 text-[10.5px] text-[var(--text-dim)] hidden md:table-cell max-w-[200px]">
                  {ex.notes}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── Clinical callout ─────────────────────────────────────────────────────────

function ClinicalCallout({ notes }: { notes: string[] }) {
  if (!notes.length) return null;
  return (
    <div
      className="rounded-[var(--r-md)] p-4"
      style={{ background: "var(--neutral-soft)", border: "1px solid oklch(0.75 0.18 75 / 0.2)" }}
    >
      <div className="flex items-center gap-2 mb-2.5">
        <span className="text-[var(--neutral)] text-sm">⚕</span>
        <Eyebrow>Clinical considerations</Eyebrow>
      </div>
      <ul className="space-y-1.5">
        {notes.map((n, i) => (
          <li key={i} className="text-[12px] text-[var(--text-muted)] leading-snug flex gap-2">
            <span className="text-[var(--neutral)] mt-0.5 flex-shrink-0">•</span>
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
      className="rounded-[var(--r-md)] p-4"
      style={{ background: "oklch(0.72 0.12 250 / 0.06)", border: "1px solid oklch(0.72 0.12 250 / 0.18)" }}
    >
      <div className="flex items-center gap-2 mb-2.5">
        <span className="text-[var(--chart-line)] text-sm">◎</span>
        <Eyebrow>Evidence base</Eyebrow>
      </div>
      <ul className="space-y-1.5">
        {insights.map((n, i) => (
          <li key={i} className="text-[12px] text-[var(--text-dim)] leading-snug flex gap-2">
            <span className="text-[var(--chart-line)] mt-0.5 flex-shrink-0">–</span>
            {n}
          </li>
        ))}
      </ul>
    </div>
  );
}

// ── Cooldown ─────────────────────────────────────────────────────────────────

function CooldownRow({ text }: { text: string }) {
  if (!text) return null;
  return (
    <div
      className="flex gap-3 px-4 py-3 rounded-[var(--r-md)]"
      style={{ background: "oklch(1 0 0 / 0.02)", border: "1px solid var(--hairline)" }}
    >
      <span className="text-[var(--text-faint)] text-sm mt-0.5">↓</span>
      <div>
        <Eyebrow>Cool-down</Eyebrow>
        <p className="text-[12px] text-[var(--text-dim)] mt-1 leading-snug">{text}</p>
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

  const { data, isLoading, isError, isFetching } = useQuery({
    queryKey: ["workout-next", regenKey],
    queryFn: () => api.workoutNext(regenKey > 0),
    staleTime: 1000 * 60 * 60,
    retry: 1,
  });

  function handleRegen() {
    setRegenKey((k) => k + 1);
    queryClient.removeQueries({ queryKey: ["workout-next"] });
  }

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <Eyebrow>Next workout</Eyebrow>
          {data && (
            <p className="text-[10.5px] text-[var(--text-faint)] mt-0.5">
              {new Date(data.generated_at).toLocaleDateString("en-US", {
                weekday: "short", month: "short", day: "numeric",
              })}
              {data.source === "claude" && " · AI coach"}
              {data.source === "fallback" && " · fallback (add Anthropic API key for full plan)"}
            </p>
          )}
        </div>
        <button
          onClick={handleRegen}
          disabled={isFetching}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-[var(--r-sm)] text-[11px] font-medium transition-all disabled:opacity-40 disabled:cursor-not-allowed"
          style={{
            background: "oklch(1 0 0 / 0.05)",
            border: "1px solid var(--hairline)",
            color: "var(--text-dim)",
          }}
          onMouseEnter={(e) => { (e.target as HTMLElement).style.color = "var(--text-muted)"; }}
          onMouseLeave={(e) => { (e.target as HTMLElement).style.color = "var(--text-dim)"; }}
        >
          <span className={isFetching ? "animate-spin inline-block" : ""}>⟳</span>
          {isFetching ? "Generating…" : "Regenerate"}
        </button>
      </div>

      {isLoading && <Skeleton />}

      {isError && (
        <div
          className="rounded-[var(--r-md)] p-6 text-center"
          style={{ background: "var(--negative-soft)", border: "1px solid oklch(0.65 0.22 25 / 0.2)" }}
        >
          <p className="text-sm text-[var(--negative)]">Could not generate workout plan</p>
          <p className="text-[11px] text-[var(--text-dim)] mt-1">
            Ensure backend is running and Anthropic API key is set
          </p>
        </div>
      )}

      {data && (
        <div className="space-y-5">
          <ReadinessBanner plan={data} />
          <WarmupSection items={data.warmup} />
          {data.blocks.map((block, i) => (
            <ExerciseTable key={i} block={block} />
          ))}
          <CooldownRow text={data.cooldown} />
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <ClinicalCallout notes={data.clinical_notes} />
            <VaultInsights insights={data.vault_insights} />
          </div>
        </div>
      )}
    </div>
  );
}
