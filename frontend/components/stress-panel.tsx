"use client";

import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  Cell,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api, type WhoopStressSample } from "@/lib/api";
import { Eyebrow } from "@/components/ui/metric";

// WHOOP's gauge runs 0-3. These are its own level bands, not ours.
const LEVEL_COLOR: Record<string, string> = {
  LOW: "oklch(0.62 0.18 145 / 0.85)",
  MEDIUM: "oklch(0.65 0.16 80 / 0.85)",
  HIGH: "oklch(0.55 0.22 25 / 0.85)",
};

function hourLabel(iso: string): string {
  const d = new Date(iso);
  return `${d.getHours()}`.padStart(2, "0");
}

function DayTooltip({ active, payload }: { active?: boolean; payload?: { payload: Record<string, unknown> }[] }) {
  if (!active || !payload?.length) return null;
  const row = payload[0].payload as { date: string; high_pct: number | null; score: number | null };
  return (
    <div className="rounded-md px-2 py-1.5 text-[10px]" style={{ background: "var(--surface-raised)", border: "1px solid var(--hairline)" }}>
      <div className="font-mono">{row.date}</div>
      <div className="text-[var(--text-faint)]">
        {row.high_pct == null ? "no data" : `${(row.high_pct * 100).toFixed(0)}% of day high`}
      </div>
      {row.score != null && <div className="text-[var(--text-faint)]">gauge {row.score.toFixed(1)} / 3.0</div>}
    </div>
  );
}

export function StressPanel() {
  const q = useQuery({ queryKey: ["whoop-stress", 7], queryFn: () => api.whoopStress(7) });

  const threshold = q.data?.high_day_threshold ?? 0.15;
  const daily = useMemo(() => q.data?.daily ?? [], [q.data]);

  // Chart only the most recent day's curve — ~1,400 samples/day, so plotting a
  // week at once is unreadable and slow.
  const lastDay = daily.length ? daily[daily.length - 1].date : null;
  const curve = useMemo(() => {
    const samples: WhoopStressSample[] = q.data?.samples ?? [];
    if (!lastDay) return [];
    return samples
      .filter((s) => s.t.slice(0, 10) === lastDay)
      .map((s) => ({ t: s.t, hour: hourLabel(s.t), value: s.value, level: s.level }));
  }, [q.data, lastDay]);

  const overDays = daily.filter((d) => d.high_pct != null && d.high_pct >= threshold).length;
  const withData = daily.filter((d) => d.high_pct != null).length;

  if (q.isLoading) {
    return <div className="text-[11px] text-[var(--text-faint)]">Loading stress…</div>;
  }

  // Distinguish "never synced" from "synced, no data" — a blank chart otherwise
  // reads as calm when it actually means the ingest has not run.
  if (!daily.length) {
    return (
      <div>
        <Eyebrow>Stress</Eyebrow>
        <p className="text-[11px] text-[var(--text-faint)] mt-1">
          No stress data. Run <code className="font-mono">shc whoop-private sync-metrics</code> to pull it.
        </p>
      </div>
    );
  }

  return (
    <div>
      <div className="flex items-baseline justify-between">
        <Eyebrow>Stress</Eyebrow>
        <span className="text-[10px] tabular-nums text-[var(--text-faint)]">
          <span style={{ color: overDays > withData / 2 ? "var(--negative)" : "var(--text-faint)" }}>
            {overDays}/{withData}
          </span>{" "}
          days ≥{(threshold * 100).toFixed(0)}% high
        </span>
      </div>

      {/* Per-day burden. The rate across days is the signal; a single day sits
          inside the ~11pp day-to-day spread and is not interpretable alone. */}
      <div className="h-[104px] mt-2">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={daily} margin={{ top: 4, right: 4, bottom: 0, left: -28 }}>
            <XAxis dataKey="date" tickFormatter={(d: string) => d.slice(5)} tick={{ fontSize: 9, fill: "var(--text-faint)" }} axisLine={false} tickLine={false} />
            <YAxis tickFormatter={(v: number) => `${Math.round(v * 100)}`} tick={{ fontSize: 9, fill: "var(--text-faint)" }} axisLine={false} tickLine={false} domain={[0, "auto"]} />
            <ReferenceLine y={threshold} stroke="var(--negative)" strokeDasharray="3 3" strokeOpacity={0.7} />
            <Tooltip content={<DayTooltip />} cursor={{ fill: "oklch(1 0 0 / 0.04)" }} />
            <Bar dataKey="high_pct" radius={[2, 2, 0, 0]} isAnimationActive={false}>
              {daily.map((d) => (
                <Cell
                  key={d.date}
                  fill={d.high_pct != null && d.high_pct >= threshold ? LEVEL_COLOR.HIGH : LEVEL_COLOR.LOW}
                />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <p className="text-[9px] text-[var(--text-faint)] mt-0.5">
        % of day in the high-stress zone · dashed line = WHOOP&apos;s −5% recovery threshold
      </p>

      {curve.length > 0 && (
        <>
          <div className="h-[96px] mt-3">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={curve} margin={{ top: 4, right: 4, bottom: 0, left: -28 }}>
                <defs>
                  <linearGradient id="stressFill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor={LEVEL_COLOR.HIGH} stopOpacity={0.5} />
                    <stop offset="100%" stopColor={LEVEL_COLOR.LOW} stopOpacity={0.05} />
                  </linearGradient>
                </defs>
                <XAxis dataKey="hour" interval={Math.max(1, Math.floor(curve.length / 8))} tick={{ fontSize: 9, fill: "var(--text-faint)" }} axisLine={false} tickLine={false} />
                <YAxis domain={[0, 3]} ticks={[0, 1, 2, 3]} tick={{ fontSize: 9, fill: "var(--text-faint)" }} axisLine={false} tickLine={false} />
                <Area type="monotone" dataKey="value" stroke={LEVEL_COLOR.MEDIUM} strokeWidth={1} fill="url(#stressFill)" isAnimationActive={false} dot={false} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
          <p className="text-[9px] text-[var(--text-faint)] mt-0.5">
            {lastDay} · {curve.length} samples · gauge 0–3 by hour
          </p>
        </>
      )}
    </div>
  );
}

export function BehaviorImpactPanel() {
  const q = useQuery({ queryKey: ["whoop-impact"], queryFn: () => api.whoopBehaviorImpact() });
  const items = (q.data?.items ?? []).filter((i) => i.impact_pct != null);
  const max = Math.max(1, ...items.map((i) => Math.abs(i.impact_pct ?? 0)));

  if (q.isLoading) return <div className="text-[11px] text-[var(--text-faint)]">Loading impact…</div>;
  if (!items.length) {
    return (
      <div>
        <Eyebrow>WHOOP impact</Eyebrow>
        <p className="text-[11px] text-[var(--text-faint)] mt-1">
          No impact analysis yet. Run <code className="font-mono">shc whoop-private sync-metrics</code>.
        </p>
      </div>
    );
  }

  return (
    <div>
      <div className="flex items-baseline justify-between">
        <Eyebrow>WHOOP impact</Eyebrow>
        <span className="text-[9px] text-[var(--text-faint)]">computed by WHOOP over full history</span>
      </div>
      <div className="mt-2 space-y-1.5">
        {items.map((item) => {
          const pct = item.impact_pct ?? 0;
          const positive = pct >= 0;
          const width = (Math.abs(pct) / max) * 50; // 50% = half-width, diverging from centre
          return (
            <div key={item.title} className="flex items-center gap-2">
              <span className="text-[10px] flex-1 truncate" title={item.title}>
                {item.title}
              </span>
              {/* Diverging bar: HURTS left, HELPS right, matching WHOOP's own layout. */}
              <div className="w-[92px] h-1.5 relative shrink-0">
                <div className="absolute left-1/2 top-0 bottom-0 w-px" style={{ background: "var(--hairline-strong)" }} />
                <div
                  className="absolute top-0 bottom-0 rounded-full"
                  style={{
                    width: `${width}%`,
                    [positive ? "left" : "right"]: "50%",
                    background: positive ? "var(--positive)" : "var(--negative)",
                  }}
                />
              </div>
              <span
                className="text-[10px] font-mono tabular-nums w-9 text-right shrink-0"
                style={{ color: positive ? "var(--positive)" : "var(--negative)" }}
              >
                {positive ? "+" : ""}
                {pct.toFixed(0)}%
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
