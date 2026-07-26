"use client";

import { useQuery } from "@tanstack/react-query";
import { api, type MomentumWeek } from "@/lib/api";
import { Eyebrow } from "@/components/ui/metric";

/**
 * "What changed since I last looked" — the question a longitudinal tool exists
 * to answer. This was a 180px-wide widget at the very bottom of the right rail;
 * it now opens the review surface.
 */

function delta(now: number | null, prev: number | null): number | null {
  if (now == null || prev == null) return null;
  return now - prev;
}

function DeltaBadge({ d, unit }: { d: number | null; unit: string }) {
  if (d == null) return <span className="text-[11px] text-[var(--text-faint)]">—</span>;
  const neutral = Math.abs(d) < 0.05;
  const color = neutral ? "var(--text-faint)" : d > 0 ? "var(--positive)" : "var(--negative)";
  const arrow = neutral ? "→" : d > 0 ? "↑" : "↓";
  const label = neutral
    ? "unchanged"
    : `${arrow} ${d > 0 ? "+" : ""}${Math.abs(d) % 1 === 0 ? Math.round(d) : d.toFixed(1)}${unit}`;
  return (
    <span className="text-[12px] tabular-nums font-medium" style={{ color }}>
      {label}
    </span>
  );
}

function MomentumTile({
  label,
  value,
  unit,
  d,
  caption,
}: {
  label: string;
  value: string;
  unit: string;
  d: number | null;
  caption: string;
}) {
  return (
    <div
      className="rounded-[var(--r-md)] border p-4"
      style={{ borderColor: "var(--hairline)", background: "oklch(1 0 0 / 0.02)" }}
    >
      <p className="text-[10px] uppercase tracking-[0.16em] text-[var(--text-dim)]">{label}</p>
      <div className="mt-2 flex items-baseline gap-2.5 flex-wrap">
        <span className="text-[30px] font-light tabular-nums leading-none text-[var(--text-primary)]">
          {value}
        </span>
        <DeltaBadge d={d} unit={unit} />
      </div>
      <p className="mt-2 text-[11px] text-[var(--text-faint)] leading-snug">{caption}</p>
    </div>
  );
}

export function MomentumPanel() {
  const q = useQuery({ queryKey: ["momentum"], queryFn: api.momentum });
  const empty: MomentumWeek = { recovery_avg: null, sleep_avg_h: null, sessions: 0 };
  const tw: MomentumWeek = q.data?.this_week ?? empty;
  const lw: MomentumWeek = q.data?.last_week ?? empty;

  return (
    <div className="shc-card shc-enter p-5">
      <div className="flex items-baseline justify-between">
        <Eyebrow>Momentum</Eyebrow>
        <span className="text-[10.5px] text-[var(--text-dim)] uppercase tracking-wider">
          last 7 days vs the 7 before
        </span>
      </div>

      {q.isLoading ? (
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mt-4">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="shc-skeleton h-[104px]" />
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mt-4">
          <MomentumTile
            label="Recovery avg"
            value={tw.recovery_avg != null ? String(tw.recovery_avg) : "—"}
            unit=""
            d={delta(tw.recovery_avg, lw.recovery_avg)}
            caption={
              lw.recovery_avg != null ? `was ${lw.recovery_avg} the prior week` : "no prior week to compare"
            }
          />
          <MomentumTile
            label="Sleep avg"
            value={tw.sleep_avg_h != null ? `${tw.sleep_avg_h}h` : "—"}
            unit="h"
            d={delta(tw.sleep_avg_h, lw.sleep_avg_h)}
            caption={
              lw.sleep_avg_h != null ? `was ${lw.sleep_avg_h}h the prior week` : "no prior week to compare"
            }
          />
          <MomentumTile
            label="Sessions"
            value={String(tw.sessions)}
            unit=""
            d={tw.sessions - lw.sessions}
            caption={`was ${lw.sessions} the prior week`}
          />
        </div>
      )}
    </div>
  );
}
