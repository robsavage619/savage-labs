"use client";

import { useQuery } from "@tanstack/react-query";
import {
  Bar,
  BarChart,
  Cell,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from "recharts";
import { api } from "@/lib/api";
import { CHART } from "@/lib/palette";
import { Eyebrow } from "@/components/ui/metric";

function tierColor(score: number) {
  if (score >= 67) return CHART.ok;
  if (score >= 34) return CHART.warn;
  return CHART.bad;
}

function DayOfWeekChart({ data }: { data: { day: string; avg_recovery: number; n: number }[] }) {
  const max = Math.max(...data.map((d) => d.avg_recovery));
  return (
    <div>
      <div className="flex items-baseline justify-between gap-x-3 gap-y-1 flex-wrap mb-2 min-w-0">
        <Eyebrow>Avg recovery by day of week</Eyebrow>
        <span className="text-[10px] text-[var(--text-faint)] whitespace-nowrap">Mon–Sun · all-time</span>
      </div>
      <div className="h-[140px] @md:h-[160px] min-w-0">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 4, right: 4, left: -24, bottom: 0 }} maxBarSize={28}>
            <XAxis dataKey="day" tick={{ fontSize: 10, fill: "var(--text-faint)" }} axisLine={false} tickLine={false} interval={0} minTickGap={0} />
            <YAxis tick={{ fontSize: 9, fill: "var(--text-faint)" }} axisLine={false} tickLine={false} domain={[0, 100]} />
            <Tooltip
              cursor={{ fill: CHART.cursor }}
              contentStyle={{ background: "var(--card-hover)", border: "1px solid var(--hairline-strong)", borderRadius: 8, fontSize: 11, color: "var(--text-primary)" }}
              labelStyle={{ color: "var(--text-muted)", fontSize: 10 }}
              itemStyle={{ color: "var(--text-primary)" }}
              formatter={(v: number) => [v.toFixed(1), "Avg recovery"]}
            />
            <Bar dataKey="avg_recovery" radius={[3, 3, 0, 0]}>
              {data.map((d, i) => (
                <Cell key={i} fill={d.avg_recovery === max ? CHART.line : CHART.lineDim} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <p className="text-[10.5px] text-[var(--text-faint)] mt-1 min-w-0">
        Best: <span className="text-[var(--text-dim)]">{data.find(d => d.avg_recovery === max)?.day}</span>
        {" · "}Worst: <span className="text-[var(--text-dim)]">{data.reduce((a, b) => a.avg_recovery < b.avg_recovery ? a : b).day}</span>
      </p>
    </div>
  );
}

function DistributionChart({ data }: { data: { bucket: string; n: number }[] }) {
  const total = data.reduce((s, d) => s + d.n, 0);
  const COLORS: Record<string, string> = {
    "Green (67–100)": "var(--positive)",
    "Yellow (34–66)": "var(--neutral)",
    "Red (0–33)": "var(--negative)",
  };
  const ordered = ["Green (67–100)", "Yellow (34–66)", "Red (0–33)"]
    .map(b => data.find(d => d.bucket === b))
    .filter(Boolean) as { bucket: string; n: number }[];

  return (
    <div>
      <div className="flex items-baseline justify-between gap-x-3 gap-y-1 flex-wrap mb-3 min-w-0">
        <Eyebrow>Recovery distribution · all-time</Eyebrow>
        <span className="text-[10px] text-[var(--text-faint)] whitespace-nowrap">{total} days</span>
      </div>
      <div className="space-y-2">
        {ordered.map((d) => {
          const pct = total ? (d.n / total) * 100 : 0;
          return (
            <div key={d.bucket}>
              <div className="flex items-center justify-between gap-2 mb-1 min-w-0">
                <span className="text-[11px] text-[var(--text-muted)] min-w-0">{d.bucket}</span>
                <span className="text-[11px] tabular-nums text-[var(--text-dim)] whitespace-nowrap shrink-0">{d.n} <span className="text-[var(--text-faint)]">({pct.toFixed(0)}%)</span></span>
              </div>
              <div className="h-[6px] rounded-full overflow-hidden" style={{ background: "var(--hairline)" }}>
                <div
                  className="h-full rounded-full transition-all"
                  style={{ width: `${pct}%`, background: COLORS[d.bucket] ?? CHART.line }}
                />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function SleepScatterChart({ data }: { data: { date: string; recovery: number; sleep_h: number | null }[] }) {
  const points = data.filter(d => d.sleep_h != null && d.sleep_h > 2 && d.sleep_h < 14);
  return (
    <div>
      <div className="flex items-baseline justify-between gap-x-3 gap-y-1 flex-wrap mb-2 min-w-0">
        <Eyebrow>Sleep hours vs recovery · 90d</Eyebrow>
        <span className="text-[10px] text-[var(--text-faint)] whitespace-nowrap">{points.length} nights</span>
      </div>
      <div className="h-[160px] @md:h-[180px] min-w-0">
        <ResponsiveContainer width="100%" height="100%">
          <ScatterChart margin={{ top: 4, right: 8, left: -16, bottom: 0 }}>
            <XAxis
              type="number" dataKey="sleep_h" name="Sleep"
              tick={{ fontSize: 9.5, fill: "var(--text-faint)" }} axisLine={false} tickLine={false}
              domain={[4, 10]} interval="preserveStartEnd" minTickGap={14}
              label={{ value: "hrs", position: "insideRight", offset: 4, fontSize: 9, fill: "var(--text-faint)" }}
            />
            <YAxis
              type="number" dataKey="recovery" name="Recovery"
              tick={{ fontSize: 9.5, fill: "var(--text-faint)" }} axisLine={false} tickLine={false}
              domain={[0, 100]}
            />
            <ZAxis range={[28, 28]} />
            <Tooltip
              cursor={{ stroke: "var(--hairline)" }}
              contentStyle={{ background: "var(--card-hover)", border: "1px solid var(--hairline-strong)", borderRadius: 8, fontSize: 11, color: "var(--text-primary)" }}
              labelStyle={{ color: "var(--text-muted)", fontSize: 10 }}
              itemStyle={{ color: "var(--text-primary)" }}
              formatter={(v: number, name: string) => [name === "Recovery" ? v.toFixed(0) : v.toFixed(1) + "h", name]}
            />
            <Scatter
              data={points}
              isAnimationActive={false}
              shape={(props: { cx?: number; cy?: number; payload?: { recovery: number } }) => {
                const { cx = 0, cy = 0, payload } = props;
                return (
                  <circle
                    cx={cx} cy={cy} r={4}
                    fill={tierColor(payload?.recovery ?? 0)}
                    fillOpacity={0.6}
                    stroke="none"
                  />
                );
              }}
            />
          </ScatterChart>
        </ResponsiveContainer>
      </div>
      <p className="text-[10.5px] text-[var(--text-faint)] mt-1">
        Dots colored green/yellow/red by recovery tier.
      </p>
    </div>
  );
}

function HrvScatterChart({ data }: { data: { date: string; recovery: number | null; hrv: number | null }[] }) {
  const points = data.filter((d): d is { date: string; recovery: number; hrv: number } => d.hrv != null && d.hrv > 0 && d.recovery != null);
  return (
    <div>
      <div className="flex items-baseline justify-between gap-x-3 gap-y-1 flex-wrap mb-2 min-w-0">
        <Eyebrow>HRV vs recovery · 90d</Eyebrow>
        <span className="text-[10px] text-[var(--text-faint)] whitespace-nowrap">{points.length} days</span>
      </div>
      <div className="h-[160px] @md:h-[180px] min-w-0">
        <ResponsiveContainer width="100%" height="100%">
          <ScatterChart margin={{ top: 4, right: 8, left: -16, bottom: 0 }}>
            <XAxis
              type="number" dataKey="hrv" name="HRV"
              tick={{ fontSize: 9.5, fill: "var(--text-faint)" }} axisLine={false} tickLine={false}
              interval="preserveStartEnd" minTickGap={14}
              label={{ value: "ms", position: "insideRight", offset: 4, fontSize: 9, fill: "var(--text-faint)" }}
            />
            <YAxis
              type="number" dataKey="recovery" name="Recovery"
              tick={{ fontSize: 9.5, fill: "var(--text-faint)" }} axisLine={false} tickLine={false}
              domain={[0, 100]}
            />
            <ZAxis range={[28, 28]} />
            <Tooltip
              cursor={{ stroke: "var(--hairline)" }}
              contentStyle={{ background: "var(--card-hover)", border: "1px solid var(--hairline-strong)", borderRadius: 8, fontSize: 11, color: "var(--text-primary)" }}
              labelStyle={{ color: "var(--text-muted)", fontSize: 10 }}
              itemStyle={{ color: "var(--text-primary)" }}
              formatter={(v: number, name: string) => [name === "Recovery" ? v.toFixed(0) : v.toFixed(1) + "ms", name]}
            />
            <Scatter
              data={points}
              isAnimationActive={false}
              shape={(props: { cx?: number; cy?: number; payload?: { recovery: number } }) => {
                const { cx = 0, cy = 0, payload } = props;
                return (
                  <circle cx={cx} cy={cy} r={4} fill={tierColor(payload?.recovery ?? 0)} fillOpacity={0.6} stroke="none" />
                );
              }}
            />
          </ScatterChart>
        </ResponsiveContainer>
      </div>
      <p className="text-[10.5px] text-[var(--text-faint)] mt-1 min-w-0">
        Higher HRV correlates with better recovery.
        <span className="ml-1.5 text-[var(--text-faint)]">β-blocker days inflate HRV artificially — use trend not absolute.</span>
      </p>
    </div>
  );
}

export function PatternsPane() {
  const { data, isLoading } = useQuery({
    queryKey: ["whoop-patterns"],
    queryFn: api.whoopPatterns,
    staleTime: 1000 * 60 * 15,
  });

  if (isLoading || !data) {
    return (
      <div className="space-y-4">
        {[140, 100, 160, 160].map((h, i) => (
          <div key={i} className="rounded-[var(--r-md)] animate-pulse" style={{ height: h, background: "var(--hairline)" }} />
        ))}
      </div>
    );
  }

  return (
    <div className="@container space-y-6">
      <p className="shc-helptext">
        <span className="text-[var(--text-muted)]">How to read this. </span>
        Patterns surface long-running tendencies — which day of week you recover best,
        how often you land green vs red, and how sleep + HRV relate to recovery.
        Use these to schedule hard sessions on your statistically-best days.
      </p>
      <DayOfWeekChart data={data.by_day_of_week} />
      <DistributionChart data={data.distribution} />
      <div className="grid grid-cols-1 @min-[680px]:grid-cols-2 gap-6 items-start">
        <div className="@container min-w-0">
          <SleepScatterChart data={data.sleep_vs_recovery} />
        </div>
        <div className="@container min-w-0">
          <HrvScatterChart data={data.sleep_vs_recovery} />
        </div>
      </div>
    </div>
  );
}
