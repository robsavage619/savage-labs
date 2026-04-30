"use client";

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Area, AreaChart, ResponsiveContainer } from "recharts";
import { api } from "@/lib/api";
import { Eyebrow, Metric } from "@/components/ui/metric";

function acwrZone(ratio: number | null | undefined): { label: string; tone: "positive" | "neutral" | "negative"; color: string } {
  if (ratio == null) return { label: "Awaiting load data", tone: "neutral", color: "var(--neutral)" };
  if (ratio >= 0.8 && ratio <= 1.3) return { label: "Optimal adaptation", tone: "positive", color: "var(--positive)" };
  if (ratio > 1.3 && ratio <= 1.5) return { label: "Overreach risk", tone: "neutral", color: "var(--neutral)" };
  if (ratio > 1.5) return { label: "Injury risk zone", tone: "negative", color: "var(--negative)" };
  return { label: "Undertraining", tone: "negative", color: "var(--negative)" };
}

function readinessSignal(
  sigma: number | null,
  ratio: number | null,
): { label: string; tone: "positive" | "neutral" | "negative"; detail: string } {
  if (sigma == null && ratio == null) return { label: "—", tone: "neutral", detail: "Awaiting biometric data" };
  if (ratio != null && ratio > 1.5) return { label: "Rest", tone: "negative", detail: "Load ratio critical — deload or rest" };
  if (ratio != null && ratio > 1.3) return { label: "Easy", tone: "neutral", detail: "Overreach zone · avoid hard efforts" };
  if (sigma != null && sigma >= 1.0) return { label: "Push", tone: "positive", detail: `HRV +${sigma.toFixed(1)}σ · prime for intensity` };
  if (sigma != null && sigma >= 0.0) return { label: "Train", tone: "positive", detail: "HRV neutral · normal session" };
  if (sigma != null && sigma < -1.5) return { label: "Easy", tone: "negative", detail: `HRV −${Math.abs(sigma).toFixed(1)}σ · nervous system suppressed` };
  if (sigma != null && sigma < -0.5) return { label: "Maintain", tone: "neutral", detail: `HRV −${Math.abs(sigma).toFixed(1)}σ · keep intensity moderate` };
  return { label: "Train", tone: "positive", detail: "Conditions nominal" };
}

function Gauge({ ratio, color }: { ratio: number; color: string }) {
  const clamped = Math.max(0, Math.min(2, ratio));
  const pct = (clamped / 2) * 100;
  return (
    <div className="relative h-[14px] rounded-full overflow-hidden bg-[oklch(1_0_0/0.05)]">
      <div
        className="absolute inset-0"
        style={{ background: "linear-gradient(90deg, var(--negative-soft) 0%, var(--neutral-soft) 40%, var(--positive-soft) 50%, var(--positive-soft) 65%, var(--neutral-soft) 75%, var(--negative-soft) 100%)" }}
      />
      {[0.8, 1.3, 1.5].map((v) => (
        <div key={v} className="absolute top-0 bottom-0 border-l border-[oklch(1_0_0/0.08)]" style={{ left: `${(v / 2) * 100}%` }} />
      ))}
      <div
        className="absolute top-1/2 -translate-y-1/2 w-[3px] h-[22px] rounded-full shadow-md"
        style={{ left: `calc(${pct}% - 1.5px)`, background: color, transition: "left 560ms cubic-bezier(0.2, 0.8, 0.2, 1)" }}
      />
    </div>
  );
}

export function PillarTrainingLoad() {
  const stats = useQuery({ queryKey: ["stats-summary"], queryFn: api.statsSummary });
  const trend = useQuery({ queryKey: ["recovery-trend-90"], queryFn: () => api.recoveryTrend(90) });
  const heatmap = useQuery({
    queryKey: ["heatmap-6w"],
    queryFn: () => api.trainingHeatmap(6),
    refetchInterval: 600_000,
  });

  const ratio = stats.data?.acwr.ratio ?? null;
  const acute = stats.data?.acwr.acute ?? null;
  const chronic = stats.data?.acwr.chronic ?? null;
  const sigma = stats.data?.hrv.deviation_sigma ?? null;
  const zone = acwrZone(ratio);
  const readiness = readinessSignal(sigma, ratio);
  const todayRecovery = trend.data?.length ? trend.data[trend.data.length - 1].score : null;

  const trainStreak = useMemo(() => {
    if (!heatmap.data?.length) return null;
    const sorted = [...heatmap.data].sort((a, b) => b.date.localeCompare(a.date));
    let streak = 0;
    for (const day of sorted) {
      if (day.intensity > 0) streak++;
      else break;
    }
    return streak;
  }, [heatmap.data]);

  const weekly = trend.data
    ? Array.from({ length: 14 }, (_, i) => {
        // i=0 is oldest week, i=13 is most recent; each window is 7 days from the end
        const end = trend.data.length - (13 - i) * 7;
        const start = end - 7;
        const slice = trend.data.slice(Math.max(0, start), Math.max(0, end));
        const avg = slice.length ? slice.reduce((a, b) => a + (b.score ?? 0), 0) / slice.length : null;
        return { wk: i + 1, load: avg != null ? 100 - avg : null };
      })
    : [];

  const sigmaColor = sigma == null ? "var(--text-muted)" : sigma >= 0 ? "var(--positive)" : "var(--negative)";
  const readinessColor =
    readiness.tone === "positive" ? "var(--positive)" : readiness.tone === "negative" ? "var(--negative)" : "var(--neutral)";

  return (
    <div className="shc-card shc-enter p-5 flex flex-col">
      <div className="flex items-baseline justify-between">
        <Eyebrow>Training load · ACWR</Eyebrow>
        <span className="text-[10.5px] text-[var(--text-dim)]">proxy · 7d ÷ 28d recovery</span>
      </div>

      <div className="mt-3 flex items-baseline gap-3">
        <Metric value={ratio != null ? ratio.toFixed(2) : "—"} size="xl" tone={zone.tone} />
        <span className="text-[13px]" style={{ color: zone.color }}>{zone.label}</span>
      </div>
      <p className="text-[10.5px] text-[var(--text-dim)] mt-1 tabular-nums">
        acute {acute ? acute.toFixed(0) : "—"} · chronic {chronic ? chronic.toFixed(0) : "—"}
      </p>

      <div className="mt-3">
        <Gauge ratio={ratio ?? 1} color={zone.color} />
        <div className="flex justify-between text-[9.5px] text-[var(--text-faint)] mt-1 tabular-nums">
          <span>0</span><span>0.8</span><span>1.3</span><span>1.5</span><span>2.0+</span>
        </div>
      </div>

      <div
        className="mt-4 px-3 py-2.5 rounded-lg border border-[var(--hairline)] flex items-center justify-between gap-3"
        style={{ background: "oklch(1 0 0 / 0.025)" }}
      >
        <div className="shrink-0">
          <p className="text-[10px] text-[var(--text-dim)] uppercase tracking-wider mb-0.5">Today's call</p>
          <p className="text-[14px] font-semibold" style={{ color: readinessColor }}>{readiness.label}</p>
        </div>
        {readiness.detail && (
          <p className="text-[10.5px] text-[var(--text-dim)] text-right leading-snug">{readiness.detail}</p>
        )}
      </div>

      <div className="mt-4">
        <div className="flex items-baseline justify-between mb-1.5">
          <p className="text-[10px] text-[var(--text-dim)] uppercase tracking-wider">Weekly load · 14w</p>
          <p className="text-[10.5px] text-[var(--text-dim)]">higher = harder week</p>
        </div>
        <div className="h-[80px]">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={weekly}>
              <defs>
                <linearGradient id="load-fill" x1="0" x2="0" y1="0" y2="1">
                  <stop offset="0%" stopColor="var(--chart-line-2)" stopOpacity="0.4" />
                  <stop offset="100%" stopColor="var(--chart-line-2)" stopOpacity="0" />
                </linearGradient>
              </defs>
              <Area dataKey="load" stroke="var(--chart-line-2)" strokeWidth={1.5} fill="url(#load-fill)" isAnimationActive={false} dot={false} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>

      <p className="mt-3 text-[10.5px] text-[var(--text-dim)] leading-snug">
        <span className="text-[var(--text-muted)]">How to read this. </span>
        ACWR (acute ÷ chronic load) 0.8–1.3 is the adaptation sweet spot.
        &gt; 1.5 spikes injury risk; &lt; 0.8 means undertraining.
        Today&apos;s call combines ACWR with HRV σ.
      </p>

      <div className="mt-4 pt-4 grid grid-cols-3 gap-3 text-[11px] border-t border-[var(--hairline)]">
        <div className="border-l border-[var(--hairline)] pl-3">
          <p className="text-[10px] text-[var(--text-dim)] uppercase tracking-wider">Train streak</p>
          <p className="tabular-nums text-[var(--text-primary)] mt-0.5 text-[13px]">
            {trainStreak != null ? `${trainStreak}d` : "—"}
          </p>
        </div>
        <div className="border-l border-[var(--hairline)] pl-3">
          <p className="text-[10px] text-[var(--text-dim)] uppercase tracking-wider">HRV delta</p>
          <p className="tabular-nums mt-0.5 text-[13px]" style={{ color: sigmaColor }}>
            {sigma != null ? `${sigma >= 0 ? "+" : ""}${sigma.toFixed(1)}σ` : "—"}
          </p>
        </div>
        <div className="border-l border-[var(--hairline)] pl-3">
          <p className="text-[10px] text-[var(--text-dim)] uppercase tracking-wider">Recovery</p>
          <p className="tabular-nums text-[var(--text-primary)] mt-0.5 text-[13px]">
            {todayRecovery != null ? Math.round(todayRecovery) : "—"}
          </p>
        </div>
      </div>
    </div>
  );
}
