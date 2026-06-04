"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Eyebrow } from "@/components/ui/metric";

const MUSCLE_LABELS: Record<string, string> = {
  chest: "Chest",
  lats: "Lats",
  mid_back: "Mid Back",
  quads: "Quads",
  hamstrings: "Hamstrings",
  glutes: "Glutes",
  front_delts: "Front Delts",
  side_delts: "Side Delts",
  rear_delts: "Rear Delts",
  biceps: "Biceps",
  triceps: "Triceps",
  forearms: "Forearms",
  traps: "Traps",
  lower_back: "Lower Back",
  calves: "Calves",
  adductors: "Adductors",
  abs: "Abs",
};

type Action = "add" | "hold" | "cut" | "deload";

const ACTION_STYLE: Record<Action, { color: string; bg: string }> = {
  add: { color: "var(--positive)", bg: "oklch(0.62 0.16 145 / 0.12)" },
  hold: { color: "var(--text-faint)", bg: "transparent" },
  cut: { color: "var(--warn)", bg: "oklch(0.65 0.16 80 / 0.12)" },
  deload: { color: "var(--negative)", bg: "oklch(0.55 0.22 25 / 0.12)" },
};

function label(muscle: string): string {
  return MUSCLE_LABELS[muscle] ?? muscle.replace(/_/g, " ");
}

export function PrescriptionPanel() {
  const rx = useQuery({
    queryKey: ["prescription"],
    queryFn: api.prescription,
    refetchInterval: 10 * 60_000,
  });

  if (rx.isLoading || rx.isError) return null;
  const data = rx.data;
  if (!data || data.muscles.length === 0) return null;

  // Surface the muscles the engine wants to move first (add/cut), then holds.
  const ordered = [...data.muscles].sort((a, b) => {
    if (a.emphasis !== b.emphasis) return a.emphasis ? -1 : 1;
    const moved = (m: { delta: number }) => (m.delta === 0 ? 1 : 0);
    if (moved(a) !== moved(b)) return moved(a) - moved(b);
    return Math.abs(b.delta) - Math.abs(a.delta);
  });

  const weekLabel = new Date(data.week_start + "T12:00:00").toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
  });

  return (
    <div className="rounded-lg border border-[var(--hairline)] p-4 space-y-3">
      <div className="flex items-baseline justify-between">
        <Eyebrow>This week&apos;s prescription · wk of {weekLabel}</Eyebrow>
        <span className="text-[10px] text-[var(--text-faint)]">auto-regulated</span>
      </div>

      <div className="space-y-2.5">
        {ordered.map((m) => {
          const style = ACTION_STYLE[m.action];
          return (
            <div key={m.muscle} className="space-y-0.5">
              <div className="flex items-baseline justify-between text-[11.5px]">
                <span className="text-[var(--text-muted)]">
                  {label(m.muscle)}
                  {m.emphasis && (
                    <span className="ml-1 text-[var(--accent)]" title="Emphasis muscle">
                      ★
                    </span>
                  )}
                </span>
                <div className="flex items-center gap-2">
                  <span className="tabular-nums text-[var(--text-faint)]">
                    {m.current_sets.toFixed(0)}
                  </span>
                  <span className="text-[var(--text-faint)] text-[10px]">→</span>
                  <span className="tabular-nums text-[var(--text-primary)]">{m.target_sets}</span>
                  {m.delta !== 0 && (
                    <span className="tabular-nums text-[10px] text-[var(--text-faint)]">
                      ({m.delta > 0 ? "+" : ""}
                      {m.delta})
                    </span>
                  )}
                  <span
                    className="text-[10px] px-1.5 py-[1px] rounded-sm uppercase tracking-wide"
                    style={{ color: style.color, border: `1px solid ${style.color}`, background: style.bg }}
                  >
                    {m.action}
                  </span>
                </div>
              </div>
              <p className="text-[10px] text-[var(--text-faint)] leading-snug">{m.reason}</p>
            </div>
          );
        })}
      </div>

      <p className="text-[10px] text-[var(--text-faint)] leading-relaxed pt-1 border-t border-[var(--hairline)]">
        Set targets the engine adapted from your e1RM performance, soreness, and court/cardio load.
        ★ = emphasis muscle (prioritized). The chat builds today&apos;s session from these.
      </p>
    </div>
  );
}
