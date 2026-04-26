"use client";

import { useQuery } from "@tanstack/react-query";
import { api, type MomentumWeek } from "@/lib/api";
import { Eyebrow } from "@/components/ui/metric";
import { CheckinCard } from "@/components/checkin-card";

function delta(now: number | null, prev: number | null): number | null {
  if (now == null || prev == null) return null;
  return now - prev;
}

function DeltaBadge({ d, unit }: { d: number | null; unit: string }) {
  if (d == null) return <span className="text-[10px] text-[var(--text-faint)]">—</span>;
  const neutral = Math.abs(d) < 0.05;
  const color = neutral ? "var(--text-faint)" : d > 0 ? "var(--positive)" : "var(--negative)";
  const arrow = neutral ? "→" : d > 0 ? "↑" : "↓";
  const label = neutral ? "same" : `${arrow} ${d > 0 ? "+" : ""}${Math.abs(d) % 1 === 0 ? Math.round(d) : d.toFixed(1)}${unit}`;
  return <span className="text-[10.5px] tabular-nums" style={{ color }}>{label}</span>;
}

function MomentumRow({
  label,
  thisVal,
  unit,
  d,
}: {
  label: string;
  thisVal: string;
  unit: string;
  d: number | null;
}) {
  return (
    <div className="flex items-baseline justify-between gap-2">
      <span className="text-[11.5px] text-[var(--text-muted)] shrink-0">{label}</span>
      <div className="flex items-baseline gap-2 min-w-0">
        <span className="metric-md tabular-nums text-[var(--text-primary)]">{thisVal}</span>
        <DeltaBadge d={d} unit={unit} />
      </div>
    </div>
  );
}

function MomentumCard() {
  const q = useQuery({ queryKey: ["momentum"], queryFn: api.momentum });
  const tw: MomentumWeek = q.data?.this_week ?? { recovery_avg: null, sleep_avg_h: null, sessions: 0 };
  const lw: MomentumWeek = q.data?.last_week ?? { recovery_avg: null, sleep_avg_h: null, sessions: 0 };

  return (
    <div className="shc-card shc-enter p-4 space-y-3">
      <div className="flex items-baseline justify-between">
        <Eyebrow>Momentum</Eyebrow>
        <span className="text-[9.5px] text-[var(--text-faint)] uppercase tracking-wider">vs last 7d</span>
      </div>
      {q.isLoading ? (
        <div className="space-y-2">
          {Array.from({ length: 3 }).map((_, i) => <div key={i} className="shc-skeleton h-[18px]" />)}
        </div>
      ) : (
        <div className="space-y-2.5">
          <MomentumRow
            label="Recovery avg"
            thisVal={tw.recovery_avg != null ? String(tw.recovery_avg) : "—"}
            unit=""
            d={delta(tw.recovery_avg, lw.recovery_avg)}
          />
          <MomentumRow
            label="Sleep avg"
            thisVal={tw.sleep_avg_h != null ? `${tw.sleep_avg_h}h` : "—"}
            unit="h"
            d={delta(tw.sleep_avg_h, lw.sleep_avg_h)}
          />
          <MomentumRow
            label="Sessions"
            thisVal={String(tw.sessions)}
            unit=""
            d={tw.sessions - lw.sessions}
          />
        </div>
      )}
    </div>
  );
}

export function RightRail() {
  return (
    <aside className="space-y-3 w-full">
      <CheckinCard />
      <MomentumCard />
    </aside>
  );
}
