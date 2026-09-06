"use client";

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Area, AreaChart, ResponsiveContainer } from "recharts";
import { api } from "@/lib/api";
import { reconciledVerdict } from "@/lib/readiness";
import { localDate } from "@/lib/date";
import { Eyebrow, Metric } from "@/components/ui/metric";
import { PlainRead } from "@/components/plain-read";
import { loadRead } from "@/lib/reads";

function acwrZone(ratio: number | null | undefined): { label: string; tone: "positive" | "neutral" | "negative"; color: string } {
  if (ratio == null) return { label: "Awaiting load data", tone: "neutral", color: "var(--neutral)" };
  if (ratio >= 0.8 && ratio <= 1.3) return { label: "Optimal adaptation", tone: "positive", color: "var(--positive)" };
  if (ratio > 1.3 && ratio <= 1.5) return { label: "Overreach risk", tone: "neutral", color: "var(--neutral)" };
  if (ratio > 1.5) return { label: "Injury risk zone", tone: "negative", color: "var(--negative)" };
  return { label: "Undertraining", tone: "negative", color: "var(--negative)" };
}

/**
 * The verdict has exactly one source: reconciledVerdict() over DailyState.
 *
 * This panel used to carry its own readinessSignal(sigma, ratio) that derived a
 * Push/Train/Easy/Maintain/Rest call in the browser — a third vocabulary
 * alongside reconciledVerdict()'s "Moderate / Push it / Train hard" and the
 * backend's training_call, and a direct breach of "DailyState is the single
 * source of truth ... never recompute these client-side." When state is
 * missing we now say so instead of guessing.
 */
const AWAITING_VERDICT = {
  label: "—",
  tone: "neutral" as const,
  detail: "Awaiting daily state",
};

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
  const stateQ = useQuery({
    queryKey: ["daily-state"],
    queryFn: api.dailyState,
    staleTime: 5 * 60 * 1000,
  });

  const ratio = stats.data?.acwr.ratio ?? null;
  const acute = stats.data?.acwr.acute ?? null;
  const chronic = stats.data?.acwr.chronic ?? null;
  const sigma = stats.data?.hrv.deviation_sigma ?? null;
  const zone = acwrZone(ratio);
  const readiness = stateQ.data
    ? (() => {
        const v = reconciledVerdict(stateQ.data);
        // Never reprint the readiness score here. This panel showed it raw
        // (65.6) while the header showed it rounded (66) and the WHOOP pillar
        // showed its own score (71) — three numbers, one apparent quantity.
        // The score has exactly one home: the header HUD. This says what the
        // gates DID, which is the part the header can't show.
        const detail = v.gated
          ? `Capped by engine gate · ceiling ${stateQ.data.gates.max_intensity}`
          : stateQ.data.readiness.score != null
            ? "Matches today's readiness — no gate applied"
            : "Awaiting biometric data";
        return { label: v.label, tone: v.tone, detail };
      })()
    : AWAITING_VERDICT;
  // Plain-English layer. loadRead reads the engine's own acute/chronic loads
  // out of DailyState, which is a different quantity from the recovery-proxy
  // ACWR this panel plots — it says what the ratio means, it does not restate it.
  const loadR = stateQ.data ? loadRead(stateQ.data) : null;
  const todayRecovery = trend.data?.length ? trend.data[trend.data.length - 1].score : null;

  const trainStreak = useMemo(() => {
    if (!heatmap.data?.length) return null;
    const trainedDates = new Set(heatmap.data.map((d) => d.date));
    let streak = 0;
    const cur = new Date();
    // If today has no training yet, start counting from yesterday.
    if (!trainedDates.has(localDate(cur))) cur.setDate(cur.getDate() - 1);
    while (trainedDates.has(localDate(cur))) {
      streak++;
      cur.setDate(cur.getDate() - 1);
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
    <div className="@container shc-card shc-enter p-6 flex flex-col">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <Eyebrow className="min-w-0">Training load · recovery proxy</Eyebrow>
        <span className="text-[10.5px] text-[var(--text-dim)] min-w-0">7d ÷ 28d avg recovery</span>
      </div>

      <div className="mt-3 flex flex-wrap items-baseline gap-x-3 gap-y-1 min-w-0">
        <Metric value={ratio != null ? ratio.toFixed(2) : "—"} size="xl" tone={zone.tone} />
        <span className="text-[13px] min-w-0" style={{ color: zone.color }}>{zone.label}</span>
      </div>
      <p className="text-[10.5px] text-[var(--text-dim)] mt-1 tabular-nums">
        acute {acute ? acute.toFixed(0) : "—"} · chronic {chronic ? chronic.toFixed(0) : "—"}
      </p>

      {loadR && (
        <PlainRead state={loadR.state} className="mt-2">
          {loadR.read}
        </PlainRead>
      )}

      <div className="mt-3">
        <Gauge ratio={ratio ?? 1} color={zone.color} />
        <div className="flex justify-between text-[9.5px] text-[var(--text-faint)] mt-1 tabular-nums">
          <span>0</span><span>0.8</span><span>1.3</span><span>1.5</span><span>2.0+</span>
        </div>
      </div>

      <div
        className="mt-4 px-3 py-2.5 rounded-lg border border-[var(--hairline)] flex flex-wrap items-center justify-between gap-x-3 gap-y-1 min-w-0"
        style={{ background: "oklch(1 0 0 / 0.025)" }}
      >
        <div className="min-w-0">
          <p className="text-[10px] text-[var(--text-dim)] uppercase tracking-wider mb-0.5">Today's call</p>
          <p className="text-[14px] font-semibold" style={{ color: readinessColor }}>{readiness.label}</p>
        </div>
        {readiness.detail && (
          <p className="text-[10.5px] text-[var(--text-dim)] text-left @md:text-right leading-snug min-w-0">{readiness.detail}</p>
        )}
      </div>

      <div className="mt-4">
        <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5 mb-1.5 min-w-0">
          <p className="text-[10px] text-[var(--text-dim)] uppercase tracking-wider min-w-0">Weekly load · 14w</p>
          <p className="text-[10.5px] text-[var(--text-dim)] min-w-0">higher = harder week</p>
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

      <div className="mt-4 pt-4 grid grid-cols-3 gap-2 @lg:gap-3 text-[11px] border-t border-[var(--hairline)] min-w-0">
        <div className="min-w-0 border-l border-[var(--hairline)] pl-2 @lg:pl-3">
          <p className="text-[10px] text-[var(--text-dim)] uppercase tracking-wider">Train streak</p>
          <p className="tabular-nums text-[var(--text-primary)] mt-0.5 text-[13px]">
            {trainStreak != null ? `${trainStreak}d` : "—"}
          </p>
        </div>
        <div className="min-w-0 border-l border-[var(--hairline)] pl-2 @lg:pl-3">
          <p className="text-[10px] text-[var(--text-dim)] uppercase tracking-wider">HRV delta</p>
          <p className="tabular-nums mt-0.5 text-[13px]" style={{ color: sigmaColor }}>
            {sigma != null ? `${sigma >= 0 ? "+" : ""}${sigma.toFixed(1)}σ` : "—"}
          </p>
        </div>
        <div className="min-w-0 border-l border-[var(--hairline)] pl-2 @lg:pl-3">
          <p className="text-[10px] text-[var(--text-dim)] uppercase tracking-wider">Recovery</p>
          <p className="tabular-nums text-[var(--text-primary)] mt-0.5 text-[13px]">
            {todayRecovery != null ? Math.round(todayRecovery) : "—"}
          </p>
        </div>
      </div>
    </div>
  );
}
