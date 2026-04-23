"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import {
  Area,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "@/lib/api";
import { Eyebrow, Metric } from "@/components/ui/metric";
import { TrainingHeatmap } from "@/components/training-heatmap";
import { VolumeChart } from "@/components/volume-chart";
import { PRTable } from "@/components/pr-table";
import { CorrelationCards } from "@/components/correlation-cards";
import { ClinicalOverview } from "@/components/clinical-overview";
import { BodyPane } from "@/components/body-panel";
import { NextWorkoutPane } from "@/components/next-workout";

const TABS = ["Workout", "Recovery", "Training", "Body", "Insights", "Clinical"] as const;
type Tab = (typeof TABS)[number];

function RecoveryTrendPane() {
  const trend = useQuery({ queryKey: ["recovery-trend-90"], queryFn: () => api.recoveryTrend(90) });
  const hrv = useQuery({ queryKey: ["hrv-90"], queryFn: () => api.hrvTrend(90) });
  const stats = useQuery({ queryKey: ["stats-summary"], queryFn: api.statsSummary });

  const recData = trend.data?.map((p) => ({ date: p.date.slice(5), score: p.score })) ?? [];
  const hrvData =
    hrv.data?.map((p) => ({
      date: p.date.slice(5),
      hrv: p.hrv ? +p.hrv.toFixed(1) : null,
      bandHigh: p.avg && p.sd ? +(p.avg + p.sd).toFixed(1) : null,
      bandLow: p.avg && p.sd ? +(p.avg - p.sd).toFixed(1) : null,
      avg: p.avg ? +p.avg.toFixed(1) : null,
    })) ?? [];

  const baselineHrv = stats.data?.hrv.baseline_28d;

  const byMonth: Record<string, { scores: number[]; hrvs: number[]; sleeps: number[] }> = {};
  (trend.data ?? []).forEach((p) => {
    const k = p.date.slice(0, 7);
    if (!byMonth[k]) byMonth[k] = { scores: [], hrvs: [], sleeps: [] };
    if (p.score != null) byMonth[k].scores.push(p.score);
    if (p.hrv != null) byMonth[k].hrvs.push(p.hrv);
  });

  return (
    <div className="space-y-5">
      <div>
        <div className="flex items-baseline justify-between mb-2">
          <Eyebrow>Recovery · 90d</Eyebrow>
          <span className="text-[10.5px] text-[var(--text-dim)]">annotated below 34 threshold</span>
        </div>
        <div className="h-[180px]">
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={recData} margin={{ top: 4, right: 8, left: -22, bottom: 0 }}>
              <defs>
                <linearGradient id="rec90" x1="0" x2="0" y1="0" y2="1">
                  <stop offset="0%" stopColor="var(--chart-line)" stopOpacity="0.3" />
                  <stop offset="100%" stopColor="var(--chart-line)" stopOpacity="0" />
                </linearGradient>
              </defs>
              <ReferenceLine y={67} stroke="var(--chart-grid)" strokeDasharray="3 3" />
              <ReferenceLine y={34} stroke="var(--chart-grid)" strokeDasharray="3 3" />
              <Area dataKey="score" stroke="var(--chart-line)" strokeWidth={1.5} fill="url(#rec90)" dot={false} isAnimationActive={false} />
              <XAxis dataKey="date" tick={{ fontSize: 9.5, fill: "var(--text-faint)" }} axisLine={false} tickLine={false} interval={Math.floor(recData.length / 6) || 1} />
              <YAxis tick={{ fontSize: 9.5, fill: "var(--text-faint)" }} axisLine={false} tickLine={false} width={30} domain={[0, 100]} />
              <Tooltip
                contentStyle={{ background: "var(--card-hover)", border: "1px solid var(--hairline-strong)", borderRadius: 8, fontSize: 11 }}
                cursor={{ stroke: "var(--hairline-strong)" }}
              />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div>
        <div className="flex items-baseline justify-between mb-2">
          <Eyebrow>HRV · 90d with ±1σ band</Eyebrow>
          {baselineHrv && (
            <span className="text-[10.5px] text-[var(--text-dim)] tabular-nums">baseline {baselineHrv.toFixed(1)}ms</span>
          )}
        </div>
        <div className="h-[180px]">
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={hrvData} margin={{ top: 4, right: 8, left: -22, bottom: 0 }}>
              <Area dataKey="bandHigh" fill="var(--chart-band)" stroke="none" isAnimationActive={false} />
              <Area dataKey="bandLow" fill="var(--bg)" stroke="none" isAnimationActive={false} />
              <Line dataKey="avg" stroke="var(--chart-baseline)" strokeWidth={1} strokeDasharray="4 3" dot={false} isAnimationActive={false} />
              <Line dataKey="hrv" stroke="var(--chart-line)" strokeWidth={1.8} dot={false} isAnimationActive={false} activeDot={{ r: 3 }} />
              <XAxis dataKey="date" tick={{ fontSize: 9.5, fill: "var(--text-faint)" }} axisLine={false} tickLine={false} interval={Math.floor(hrvData.length / 6) || 1} />
              <YAxis tick={{ fontSize: 9.5, fill: "var(--text-faint)" }} axisLine={false} tickLine={false} width={30} />
              <Tooltip contentStyle={{ background: "var(--card-hover)", border: "1px solid var(--hairline-strong)", borderRadius: 8, fontSize: 11 }} cursor={{ stroke: "var(--hairline-strong)" }} />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div>
        <Eyebrow>Monthly averages</Eyebrow>
        <div className="mt-2 rounded-lg border border-[var(--hairline)] overflow-hidden">
          <table className="w-full text-[12px] tabular-nums">
            <thead className="text-[10px] text-[var(--text-dim)] uppercase tracking-wider">
              <tr className="border-b border-[var(--hairline)]">
                <th className="px-3 py-2 text-left font-normal">Month</th>
                <th className="px-3 py-2 text-right font-normal">Recovery</th>
                <th className="px-3 py-2 text-right font-normal">HRV</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(byMonth)
                .sort(([a], [b]) => b.localeCompare(a))
                .slice(0, 4)
                .map(([k, v]) => {
                  const avgRec = v.scores.length ? v.scores.reduce((a, b) => a + b, 0) / v.scores.length : null;
                  const avgHrv = v.hrvs.length ? v.hrvs.reduce((a, b) => a + b, 0) / v.hrvs.length : null;
                  const label = new Date(k + "-01T12:00:00").toLocaleDateString("en-US", { month: "long", year: "numeric" });
                  return (
                    <tr key={k} className="border-b border-[var(--hairline)] last:border-b-0 hover:bg-[oklch(1_0_0/0.02)]">
                      <td className="px-3 py-2 text-[var(--text-muted)]">{label}</td>
                      <td className="px-3 py-2 text-right">{avgRec ? avgRec.toFixed(0) : "—"}</td>
                      <td className="px-3 py-2 text-right">{avgHrv ? avgHrv.toFixed(1) : "—"}<span className="text-[var(--text-faint)] ml-1">ms</span></td>
                    </tr>
                  );
                })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function TrainingPane() {
  return (
    <div className="space-y-6">
      <TrainingHeatmap />
      <VolumeChart />
      <PRTable />
    </div>
  );
}

function InsightsPane() {
  return <CorrelationCards />;
}

function ClinicalPane() {
  return <ClinicalOverview />;
}



export function TrendIntelligence() {
  const [tab, setTab] = useState<Tab>("Workout");

  return (
    <div className="shc-card shc-enter p-5">
      <div className="flex items-baseline justify-between mb-4">
        <Eyebrow>Trend intelligence</Eyebrow>
        <div className="flex gap-1">
          {TABS.map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`px-3 py-1 text-[11px] rounded-md transition-colors tabular-nums ${
                tab === t
                  ? "bg-[oklch(1_0_0/0.08)] text-[var(--text-primary)]"
                  : "text-[var(--text-dim)] hover:text-[var(--text-muted)]"
              }`}
            >
              {t}
            </button>
          ))}
        </div>
      </div>
      <div className="mt-2">
        {tab === "Workout" && <NextWorkoutPane />}
        {tab === "Recovery" && <RecoveryTrendPane />}
        {tab === "Training" && <TrainingPane />}
        {tab === "Body" && <BodyPane />}
        {tab === "Insights" && <InsightsPane />}
        {tab === "Clinical" && <ClinicalPane />}
      </div>
    </div>
  );
}

