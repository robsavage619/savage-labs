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
import { Eyebrow } from "@/components/ui/metric";

function tierColor(score: number) {
  if (score >= 67) return "var(--positive)";
  if (score >= 34) return "var(--neutral)";
  return "var(--negative)";
}

function DayOfWeekChart({ data }: { data: { day: string; avg_recovery: number; n: number }[] }) {
  const max = Math.max(...data.map((d) => d.avg_recovery));
  return (
    <div>
      <div className="flex items-baseline justify-between mb-2">
        <Eyebrow>Avg recovery by day of week</Eyebrow>
        <span className="text-[10px] text-[var(--text-faint)]">Mon–Sun · all-time</span>
      </div>
      <div className="h-[160px]">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 4, right: 4, left: -24, bottom: 0 }} barSize={28}>
            <XAxis dataKey="day" tick={{ fontSize: 10, fill: "var(--text-faint)" }} axisLine={false} tickLine={false} />
            <YAxis tick={{ fontSize: 9, fill: "var(--text-faint)" }} axisLine={false} tickLine={false} domain={[0, 100]} />
            <Tooltip
              cursor={{ fill: "oklch(1 0 0 / 0.03)" }}
              contentStyle={{ background: "var(--card-hover)", border: "1px solid var(--hairline-strong)", borderRadius: 8, fontSize: 11 }}
              formatter={(v: number) => [v.toFixed(1), "Avg recovery"]}
            />
            <Bar dataKey="avg_recovery" radius={[3, 3, 0, 0]}>
              {data.map((d, i) => (
                <Cell key={i} fill={d.avg_recovery === max ? "var(--chart-line)" : "oklch(0.72 0.12 250 / 0.25)"} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <p className="text-[10.5px] text-[var(--text-faint)] mt-1">
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
      <div className="flex items-baseline justify-between mb-3">
        <Eyebrow>Recovery distribution · all-time</Eyebrow>
        <span className="text-[10px] text-[var(--text-faint)]">{total} days</span>
      </div>
      <div className="space-y-2">
        {ordered.map((d) => {
          const pct = total ? (d.n / total) * 100 : 0;
          return (
            <div key={d.bucket}>
              <div className="flex items-center justify-between mb-1">
                <span className="text-[11px] text-[var(--text-muted)]">{d.bucket}</span>
                <span className="text-[11px] tabular-nums text-[var(--text-dim)]">{d.n} <span className="text-[var(--text-faint)]">({pct.toFixed(0)}%)</span></span>
              </div>
              <div className="h-[6px] rounded-full overflow-hidden" style={{ background: "oklch(1 0 0 / 0.06)" }}>
                <div
                  className="h-full rounded-full transition-all"
                  style={{ width: `${pct}%`, background: COLORS[d.bucket] ?? "var(--chart-line)" }}
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
      <div className="flex items-baseline justify-between mb-2">
        <Eyebrow>Sleep hours vs recovery · 90d</Eyebrow>
        <span className="text-[10px] text-[var(--text-faint)]">{points.length} nights</span>
      </div>
      <div className="h-[180px]">
        <ResponsiveContainer width="100%" height="100%">
          <ScatterChart margin={{ top: 4, right: 8, left: -16, bottom: 0 }}>
            <XAxis
              type="number" dataKey="sleep_h" name="Sleep"
              tick={{ fontSize: 9.5, fill: "var(--text-faint)" }} axisLine={false} tickLine={false}
              domain={[4, 10]} label={{ value: "hrs", position: "insideRight", offset: 4, fontSize: 9, fill: "var(--text-faint)" }}
            />
            <YAxis
              type="number" dataKey="recovery" name="Recovery"
              tick={{ fontSize: 9.5, fill: "var(--text-faint)" }} axisLine={false} tickLine={false}
              domain={[0, 100]}
            />
            <ZAxis range={[28, 28]} />
            <Tooltip
              cursor={{ stroke: "var(--hairline)" }}
              contentStyle={{ background: "var(--card-hover)", border: "1px solid var(--hairline-strong)", borderRadius: 8, fontSize: 11 }}
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

function HrvScatterChart({ data }: { data: { date: string; recovery: number; hrv: number | null }[] }) {
  const points = data.filter(d => d.hrv != null && d.hrv > 0);
  return (
    <div>
      <div className="flex items-baseline justify-between mb-2">
        <Eyebrow>HRV vs recovery · 90d</Eyebrow>
        <span className="text-[10px] text-[var(--text-faint)]">{points.length} days</span>
      </div>
      <div className="h-[180px]">
        <ResponsiveContainer width="100%" height="100%">
          <ScatterChart margin={{ top: 4, right: 8, left: -16, bottom: 0 }}>
            <XAxis
              type="number" dataKey="hrv" name="HRV"
              tick={{ fontSize: 9.5, fill: "var(--text-faint)" }} axisLine={false} tickLine={false}
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
              contentStyle={{ background: "var(--card-hover)", border: "1px solid var(--hairline-strong)", borderRadius: 8, fontSize: 11 }}
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
      <p className="text-[10.5px] text-[var(--text-faint)] mt-1">
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
        {[160, 100, 180, 180].map((h, i) => (
          <div key={i} className="rounded-[var(--r-md)] animate-pulse" style={{ height: h, background: "oklch(1 0 0 / 0.04)" }} />
        ))}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <DayOfWeekChart data={data.by_day_of_week} />
      <DistributionChart data={data.distribution} />
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <SleepScatterChart data={data.sleep_vs_recovery} />
        <HrvScatterChart data={data.sleep_vs_recovery} />
      </div>
    </div>
  );
}
