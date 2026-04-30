"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ProgressionDrawer } from "@/components/progression-drawer";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
  LineChart,
  Line,
} from "recharts";
import { api } from "@/lib/api";
import { Eyebrow, Metric } from "@/components/ui/metric";

// ── Heatmap ──────────────────────────────────────────────────────────────────

const HEAT = [
  "oklch(0.22 0 0)",
  "oklch(0.38 0.10 145)",
  "oklch(0.52 0.15 145)",
  "oklch(0.64 0.18 145)",
  "oklch(0.76 0.21 145)",
];

type HDay = { date: string; intensity: number; sets: number; volume_kg: number };

function buildGrid(days: HDay[]): HDay[][] {
  const map = new Map(days.map(d => [d.date, d]));
  const today = new Date();
  const start = new Date(today);
  start.setDate(start.getDate() - 104 * 7 - start.getDay());
  const weeks: HDay[][] = [];
  let week: HDay[] = [];
  const cur = new Date(start);
  while (cur <= today) {
    const k = cur.toISOString().slice(0, 10);
    week.push(map.get(k) ?? { date: k, intensity: 0, sets: 0, volume_kg: 0 });
    if (week.length === 7) { weeks.push(week); week = []; }
    cur.setDate(cur.getDate() + 1);
  }
  if (week.length) weeks.push(week);
  return weeks;
}

function Heatmap() {
  const { data = [], isLoading } = useQuery({
    queryKey: ["heatmap-104"],
    queryFn: () => api.trainingHeatmap(104),
    refetchInterval: 600_000,
  });
  const weeks = buildGrid(data);
  const activeDays = data.filter(d => d.sets > 0).length;

  return (
    <div className="space-y-2">
      <div className="flex items-baseline justify-between">
        <Eyebrow>Training consistency · 2 years</Eyebrow>
        <span className="text-[10.5px] text-[var(--text-faint)] tabular-nums">{activeDays} sessions</span>
      </div>
      {isLoading ? (
        <div className="h-[88px] shc-skeleton rounded" />
      ) : (
        <div className="overflow-x-auto">
          <div className="flex gap-[3px] min-w-max">
            {weeks.map((wk, wi) => (
              <div key={wi} className="flex flex-col gap-[3px]">
                {wk.map((day, di) => (
                  <div
                    key={di}
                    title={day.sets > 0 ? `${day.date}: ${day.sets} sets · ${(day.volume_kg ?? 0).toLocaleString()}kg` : day.date}
                    className="w-[11px] h-[11px] rounded-[2px] cursor-default hover:opacity-70 transition-opacity"
                    style={{ background: HEAT[day.intensity] }}
                  />
                ))}
              </div>
            ))}
          </div>
        </div>
      )}
      <div className="flex items-center gap-1.5 justify-end">
        <span className="text-[9.5px] text-[var(--text-faint)]">Less</span>
        {HEAT.map((c, i) => <div key={i} className="w-[10px] h-[10px] rounded-[2px]" style={{ background: c }} />)}
        <span className="text-[9.5px] text-[var(--text-faint)]">More</span>
      </div>
    </div>
  );
}

// ── Volume trend with overload signal ────────────────────────────────────────

const VolumeTooltip = ({ active, payload, label }: any) => {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  return (
    <div className="rounded-lg border px-3 py-2 text-[11px] font-mono" style={{ background: "var(--card-hover)", borderColor: "var(--hairline-strong)" }}>
      <p className="text-[var(--text-dim)] mb-1">{label}</p>
      <p className="text-[var(--text-primary)]">{(d.volume_kg ?? 0).toLocaleString()} kg</p>
      <p className="text-[var(--text-muted)]">{d.sets} sets · {d.sessions} days</p>
    </div>
  );
};

function VolumeTrend() {
  const { data: weeks = [], isLoading: wLoading } = useQuery({
    queryKey: ["weekly-volume"],
    queryFn: () => api.trainingWeekly(104),
    refetchInterval: 600_000,
  });
  const { data: signal } = useQuery({
    queryKey: ["overload-signal"],
    queryFn: api.trainingOverloadSignal,
    refetchInterval: 600_000,
  });

  const formatted = weeks.map(d => ({ ...d, label: d.week.slice(5) }));
  const avg = weeks.length ? weeks.reduce((s, d) => s + d.volume_kg, 0) / weeks.length : 0;

  const trendColor =
    signal?.trend === "progressing" ? "var(--positive)"
    : signal?.trend === "deloading" ? "var(--negative)"
    : "var(--neutral)";

  const trendLabel =
    signal?.trend === "progressing" ? `↑ ${signal.overload_pct?.toFixed(0)}% progressive overload`
    : signal?.trend === "deloading" ? `↓ ${Math.abs(signal.overload_pct ?? 0).toFixed(0)}% volume reduction`
    : signal?.trend === "maintaining" ? "→ Volume maintained"
    : null;

  return (
    <div className="space-y-2">
      <div className="flex items-baseline justify-between">
        <Eyebrow>Volume load · 52 weeks (kg lifted)</Eyebrow>
        {trendLabel && (
          <span className="text-[10.5px] font-medium tabular-nums" style={{ color: trendColor }}>{trendLabel}</span>
        )}
      </div>
      {wLoading ? (
        <div className="h-[140px] shc-skeleton rounded" />
      ) : !formatted.length ? (
        <div className="h-[140px] flex items-center justify-center text-[11px] text-[var(--text-faint)]">No workout data</div>
      ) : (
        <ResponsiveContainer width="100%" height={140}>
          <BarChart data={formatted} margin={{ top: 4, right: 0, left: -24, bottom: 0 }}>
            <XAxis dataKey="label" tick={{ fontSize: 9.5, fill: "var(--text-faint)" }} tickLine={false} axisLine={false} />
            <YAxis tick={{ fontSize: 9.5, fill: "var(--text-faint)" }} tickLine={false} axisLine={false} tickFormatter={v => `${(v / 1000).toFixed(0)}k`} />
            <Tooltip content={<VolumeTooltip />} cursor={{ fill: "oklch(1 0 0 / 0.03)" }} />
            {avg > 0 && <ReferenceLine y={avg} stroke="var(--chart-baseline)" strokeDasharray="3 3" />}
            <Bar dataKey="volume_kg" fill="var(--chart-line)" radius={[3, 3, 0, 0]} maxBarSize={28} />
          </BarChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}

// ── PR table ─────────────────────────────────────────────────────────────────

function PRTable({ onPick }: { onPick: (exercise: string) => void }) {
  const today = new Date();
  const { data = [], isLoading } = useQuery({
    queryKey: ["prs"],
    queryFn: () => api.trainingPRs(15),
    refetchInterval: 600_000,
  });

  function staleness(lastPerformed: string): { label: string; color: string } {
    const daysAgo = Math.floor((today.getTime() - new Date(lastPerformed).getTime()) / 86_400_000);
    if (daysAgo <= 90) return { label: `${Math.floor(daysAgo / 30) || "<1"}mo`, color: "var(--positive)" };
    if (daysAgo <= 365) return { label: `${Math.floor(daysAgo / 30)}mo`, color: "var(--neutral)" };
    return { label: `${Math.floor(daysAgo / 365)}yr`, color: "var(--negative)" };
  }

  return (
    <div className="space-y-2">
      <div className="flex items-baseline justify-between">
        <Eyebrow>Strength PRs · top 15</Eyebrow>
        <span className="text-[10.5px] text-[var(--text-dim)]">click row · est 1RM →</span>
      </div>
      {isLoading ? (
        <div className="space-y-1">
          {[...Array(8)].map((_, i) => <div key={i} className="h-6 shc-skeleton rounded" />)}
        </div>
      ) : (
        <div className="space-y-px">
          {data.map((pr, i) => {
            const { label: staleLabel, color: staleColor } = staleness(pr.last_performed);
            const epleyDelta = pr.est_1rm_lbs - pr.pr_lbs;
            return (
              <button
                key={pr.exercise}
                onClick={() => onPick(pr.exercise)}
                className="w-full flex items-center justify-between px-2 py-[5px] rounded text-left hover:bg-[var(--card-hover)] transition-colors"
                style={{ background: i % 2 === 0 ? "oklch(1 0 0 / 0.025)" : "transparent" }}
                title={`${pr.exercise} — ${pr.pr_lbs} lbs × ${pr.pr_reps} on ${pr.pr_date}`}
              >
                <div className="flex items-center gap-2 min-w-0">
                  <span className="text-[9.5px] font-mono w-4 text-right flex-shrink-0 text-[var(--text-faint)]">{i + 1}</span>
                  <span className="text-[11.5px] truncate text-[var(--text-muted)]">{pr.exercise}</span>
                </div>
                <div className="flex items-center gap-3 flex-shrink-0 ml-2">
                  <span className="text-[11.5px] font-mono tabular-nums text-[var(--text-primary)]">
                    {pr.pr_lbs}
                    <span className="text-[var(--text-faint)] text-[9.5px] ml-0.5">×{pr.pr_reps}</span>
                  </span>
                  <span
                    className="text-[10px] font-mono tabular-nums w-14 text-right text-[var(--chart-line)]"
                    title="Epley estimated 1RM"
                  >
                    ≈{pr.est_1rm_lbs.toFixed(0)}
                    {epleyDelta > 5 && (
                      <span className="text-[8.5px] text-[var(--text-faint)] ml-0.5">·1RM</span>
                    )}
                  </span>
                  <span className="text-[9.5px] font-mono w-8 text-right tabular-nums" style={{ color: staleColor }}>{staleLabel}</span>
                </div>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ── Top exercises by frequency ────────────────────────────────────────────────

function TopExercisesTable({ onPick }: { onPick: (exercise: string) => void }) {
  const { data = [], isLoading } = useQuery({
    queryKey: ["top-exercises"],
    queryFn: () => api.trainingTopExercises(10),
    refetchInterval: 600_000,
  });

  return (
    <div className="space-y-2">
      <div className="flex items-baseline justify-between">
        <Eyebrow>Most trained · by set volume</Eyebrow>
        <span className="text-[10.5px] text-[var(--text-dim)]">click row →</span>
      </div>
      {isLoading ? (
        <div className="space-y-1">
          {[...Array(6)].map((_, i) => <div key={i} className="h-6 shc-skeleton rounded" />)}
        </div>
      ) : (
        <div className="space-y-px">
          {data.map((ex, i) => {
            const maxSets = data[0]?.total_sets ?? 1;
            const barPct = (ex.total_sets / maxSets) * 100;
            return (
              <button
                key={ex.exercise}
                onClick={() => onPick(ex.exercise)}
                className="w-full flex items-center gap-3 px-2 py-[5px] text-left rounded hover:bg-[var(--card-hover)] transition-colors"
              >
                <span className="text-[9.5px] font-mono w-4 text-right flex-shrink-0 text-[var(--text-faint)]">{i + 1}</span>
                <div className="flex-1 min-w-0">
                  <div className="flex items-baseline justify-between gap-2">
                    <span className="text-[11.5px] truncate text-[var(--text-muted)]">{ex.exercise}</span>
                    <span className="text-[10px] font-mono tabular-nums text-[var(--text-dim)] flex-shrink-0">{(ex.total_sets ?? 0).toLocaleString()} sets</span>
                  </div>
                  <div className="h-[3px] rounded-full mt-1 bg-[oklch(1_0_0/0.06)]">
                    <div className="h-full rounded-full" style={{ width: `${barPct}%`, background: "var(--chart-line)" }} />
                  </div>
                </div>
                <span className="text-[10px] font-mono tabular-nums text-[var(--text-faint)] w-16 text-right flex-shrink-0">{ex.pr_lbs} lbs PR</span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ── Muscle balance (push/pull/legs/core) ─────────────────────────────────────

const MUSCLE_LABEL: Record<string, string> = {
  push: "Push",
  pull: "Pull",
  legs: "Legs",
  core: "Core",
  other: "Other",
};

// Approximate weekly set targets (Schoenfeld et al., minimum effective dose).
const TARGET_WEEKLY: Record<string, number> = {
  push: 10,
  pull: 10,
  legs: 10,
  core: 6,
  other: 0,
};

// Neutral bars — status (on-target / high / below / neglected) carries the semantic
// color, not the muscle group identity. Avoids red Push looking like a danger signal.
const MUSCLE_COLOR: Record<string, string> = {
  push: "oklch(0.55 0.04 250)",
  pull: "oklch(0.55 0.04 250)",
  legs: "oklch(0.55 0.04 250)",
  core: "oklch(0.55 0.04 250)",
  other: "oklch(0.45 0.02 250)",
};

function MuscleBalance() {
  const { data, isLoading } = useQuery({
    queryKey: ["muscle-balance-4w"],
    queryFn: () => api.trainingMuscleBalance(4),
    refetchInterval: 600_000,
  });

  const groups = data?.groups ?? [];
  const real = groups.filter((g) => g.group !== "other");

  // Push/pull ratio is the most actionable balance signal.
  const push = real.find((g) => g.group === "push");
  const pull = real.find((g) => g.group === "pull");
  const ratio =
    push && pull && pull.sets > 0
      ? push.sets / pull.sets
      : null;
  const ratioColor =
    ratio == null
      ? "var(--text-faint)"
      : ratio > 1.4
        ? "var(--negative)"
        : ratio < 0.7
          ? "var(--negative)"
          : Math.abs(ratio - 1) < 0.2
            ? "var(--positive)"
            : "var(--neutral)";
  const ratioNote =
    ratio == null
      ? "—"
      : ratio > 1.4
        ? "push-dominant"
        : ratio < 0.7
          ? "pull-dominant"
          : Math.abs(ratio - 1) < 0.2
            ? "balanced"
            : "tilted";

  return (
    <div className="space-y-2">
      <div className="flex items-baseline justify-between">
        <Eyebrow>Muscle balance · last 4 weeks</Eyebrow>
        <span className="text-[10.5px] text-[var(--text-dim)]">
          push:pull{" "}
          <span className="tabular-nums font-medium" style={{ color: ratioColor }}>
            {ratio != null ? ratio.toFixed(2) : "—"}
          </span>
          <span className="text-[var(--text-faint)]"> · {ratioNote}</span>
        </span>
      </div>
      {isLoading ? (
        <div className="h-[88px] shc-skeleton rounded" />
      ) : (
        <div className="space-y-1.5">
          {real.map((g) => {
            const target = TARGET_WEEKLY[g.group] ?? 0;
            const pct = target > 0 ? Math.min(100, (g.weekly_sets / target) * 100) : 0;
            const status =
              target === 0
                ? "—"
                : g.weekly_sets >= target * 1.5
                  ? "high"
                  : g.weekly_sets >= target
                    ? "on target"
                    : g.weekly_sets >= target * 0.5
                      ? "below"
                      : "neglected";
            const statusColor =
              status === "on target"
                ? "var(--positive)"
                : status === "high"
                  ? "var(--neutral)"
                  : status === "below"
                    ? "var(--neutral)"
                    : status === "neglected"
                      ? "var(--negative)"
                      : "var(--text-faint)";
            return (
              <div key={g.group} className="flex items-center gap-3">
                <span className="text-[10.5px] text-[var(--text-dim)] uppercase tracking-wider w-9 flex-shrink-0">
                  {MUSCLE_LABEL[g.group]}
                </span>
                <div className="flex-1 h-[14px] rounded-sm bg-[oklch(1_0_0/0.04)] relative overflow-hidden">
                  <div
                    className="absolute inset-y-0 left-0 rounded-sm"
                    style={{
                      width: `${pct}%`,
                      background: status === "neglected" ? "var(--negative)" : status === "on target" ? "var(--positive)" : MUSCLE_COLOR[g.group],
                      opacity: status === "on target" ? 0.55 : status === "neglected" ? 0.55 : 0.7,
                    }}
                  />
                  <div className="absolute inset-y-0 flex items-center px-2 text-[9.5px] font-mono tabular-nums text-[var(--text-primary)]">
                    {g.weekly_sets.toFixed(1)} / {target} sets·wk
                  </div>
                </div>
                <span
                  className="text-[9.5px] tabular-nums w-16 text-right flex-shrink-0"
                  style={{ color: statusColor }}
                >
                  {status}
                </span>
              </div>
            );
          })}
        </div>
      )}
      <p className="text-[10px] text-[var(--text-faint)] leading-snug">
        Targets reflect Schoenfeld et al. minimum effective dose (~10 sets/wk
        per major group, 6 for core). Push:pull within 0.8–1.2 supports shoulder
        balance.
      </p>
    </div>
  );
}

// ── Recovery × Training correlation ──────────────────────────────────────────

function RecoveryCorrelation() {
  const { data: recovery = [] } = useQuery({
    queryKey: ["recovery-trend-90"],
    queryFn: () => api.recoveryTrend(90),
    refetchInterval: 600_000,
  });
  const { data: heatmapData = [] } = useQuery({
    queryKey: ["heatmap-13w"],
    queryFn: () => api.trainingHeatmap(13),
    refetchInterval: 600_000,
  });

  const result = useMemo(() => {
    if (!recovery.length || !heatmapData.length) return null;

    const trainSet = new Set(heatmapData.filter((d) => d.intensity > 0).map((d) => d.date));
    const recoveryMap = new Map(recovery.map((d) => [d.date, d.score]));

    const trainScores: number[] = [];
    const restScores: number[] = [];
    const nextDayAfterTrain: number[] = [];
    const nextDayAfterRest: number[] = [];

    for (const day of recovery) {
      if (day.score == null) continue;
      const isTrain = trainSet.has(day.date);
      if (isTrain) trainScores.push(day.score);
      else restScores.push(day.score);

      const next = new Date(day.date);
      next.setDate(next.getDate() + 1);
      const nextScore = recoveryMap.get(next.toISOString().slice(0, 10));
      if (nextScore != null) {
        if (isTrain) nextDayAfterTrain.push(nextScore);
        else nextDayAfterRest.push(nextScore);
      }
    }

    const avg = (arr: number[]) => (arr.length ? arr.reduce((a, b) => a + b, 0) / arr.length : null);
    const trainAvg = avg(trainScores);
    const restAvg = avg(restScores);
    const ndTrainAvg = avg(nextDayAfterTrain);
    const ndRestAvg = avg(nextDayAfterRest);
    const nextDayDelta = ndTrainAvg != null && ndRestAvg != null ? ndTrainAvg - ndRestAvg : null;

    return { trainAvg, restAvg, nextDayDelta, trainCount: trainScores.length, restCount: restScores.length };
  }, [recovery, heatmapData]);

  if (!result || result.trainAvg == null) return null;

  const { trainAvg, restAvg, nextDayDelta, trainCount, restCount } = result;

  let insight = "";
  if (nextDayDelta != null) {
    if (nextDayDelta >= 3) insight = `Training boosts next-day recovery by ${nextDayDelta.toFixed(0)} pts on average.`;
    else if (nextDayDelta <= -5) insight = `Training suppresses next-day recovery by ${Math.abs(nextDayDelta).toFixed(0)} pts on average.`;
    else insight = `Next-day recovery after training is roughly neutral (${nextDayDelta >= 0 ? "+" : ""}${nextDayDelta.toFixed(0)} pts vs rest days).`;
  }
  if (trainAvg != null && restAvg != null && trainAvg > restAvg + 5) {
    insight += (insight ? " " : "") + "You tend to train on higher-recovery days — good self-regulation.";
  }

  const deltaColor =
    nextDayDelta == null
      ? "var(--text-primary)"
      : nextDayDelta >= 0
        ? "var(--positive)"
        : nextDayDelta <= -5
          ? "var(--negative)"
          : "var(--neutral)";

  return (
    <div className="space-y-3">
      <div className="flex items-baseline justify-between">
        <Eyebrow>Recovery × training · 90d</Eyebrow>
        <span className="text-[10.5px] text-[var(--text-faint)] tabular-nums">{trainCount} train · {restCount} rest days</span>
      </div>
      <div className="grid grid-cols-3 gap-3">
        <div className="border-l border-[var(--hairline)] pl-3">
          <p className="text-[10px] text-[var(--text-dim)] uppercase tracking-wider mb-0.5">Train day recovery</p>
          <p className="text-[22px] font-light tabular-nums leading-none text-[var(--text-primary)]">
            {Math.round(trainAvg)}
          </p>
          <p className="text-[9.5px] text-[var(--text-faint)] mt-1">avg WHOOP score</p>
        </div>
        <div className="border-l border-[var(--hairline)] pl-3">
          <p className="text-[10px] text-[var(--text-dim)] uppercase tracking-wider mb-0.5">Rest day recovery</p>
          <p className="text-[22px] font-light tabular-nums leading-none text-[var(--text-primary)]">
            {restAvg != null ? Math.round(restAvg) : "—"}
          </p>
          <p className="text-[9.5px] text-[var(--text-faint)] mt-1">avg WHOOP score</p>
        </div>
        <div className="border-l border-[var(--hairline)] pl-3">
          <p className="text-[10px] text-[var(--text-dim)] uppercase tracking-wider mb-0.5">Next-day delta</p>
          <p className="text-[22px] font-light tabular-nums leading-none" style={{ color: deltaColor }}>
            {nextDayDelta != null ? `${nextDayDelta >= 0 ? "+" : ""}${nextDayDelta.toFixed(0)}` : "—"}
          </p>
          <p className="text-[9.5px] text-[var(--text-faint)] mt-1">after training vs rest</p>
        </div>
      </div>
      {insight && (
        <p className="text-[10.5px] text-[var(--text-dim)] leading-snug">{insight}</p>
      )}
    </div>
  );
}

// ── Session header strip ──────────────────────────────────────────────────────

function SessionHeader() {
  const { data: session, isLoading: sLoad } = useQuery({
    queryKey: ["last-session"],
    queryFn: api.trainingLastSession,
    refetchInterval: 600_000,
  });
  const { data: signal } = useQuery({
    queryKey: ["overload-signal"],
    queryFn: api.trainingOverloadSignal,
    refetchInterval: 600_000,
  });

  const daysAgo = session?.days_ago;
  const freshness =
    daysAgo == null ? "var(--text-faint)"
    : daysAgo <= 2 ? "var(--positive)"
    : daysAgo <= 5 ? "var(--neutral)"
    : "var(--negative)";

  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 pb-4 border-b border-[var(--hairline)]">
      <div>
        <p className="text-[10px] uppercase tracking-wider text-[var(--text-dim)] mb-0.5">Last session</p>
        {sLoad ? <div className="h-6 w-24 shc-skeleton rounded" /> : (
          <div className="flex items-baseline gap-1.5">
            <span className="text-[22px] font-light tabular-nums leading-none" style={{ color: freshness }}>
              {daysAgo ?? "—"}
            </span>
            <span className="text-[11px] text-[var(--text-faint)]">days ago</span>
          </div>
        )}
        {session?.exercise_list && (
          <p className="text-[10px] text-[var(--text-faint)] mt-1 leading-snug truncate">{session.exercise_list.slice(0, 3).join(" · ")}</p>
        )}
      </div>

      <div>
        <p className="text-[10px] uppercase tracking-wider text-[var(--text-dim)] mb-0.5">This week</p>
        <div className="flex items-baseline gap-1.5">
          <span className="text-[22px] font-light tabular-nums leading-none text-[var(--text-primary)]">
            {session?.week_sets ?? "—"}
          </span>
          <span className="text-[11px] text-[var(--text-faint)]">sets</span>
        </div>
        {session && (
          <p className="text-[10px] text-[var(--text-faint)] mt-1 tabular-nums">{(session.week_volume_kg ?? 0).toLocaleString()} kg lifted</p>
        )}
      </div>

      <div>
        <p className="text-[10px] uppercase tracking-wider text-[var(--text-dim)] mb-0.5">Frequency</p>
        <div className="flex items-baseline gap-1.5">
          <span className="text-[22px] font-light tabular-nums leading-none text-[var(--text-primary)]">
            {signal?.recent_sessions_per_week?.toFixed(1) ?? "—"}
          </span>
          <span className="text-[11px] text-[var(--text-faint)]">days/wk</span>
        </div>
        <p className="text-[10px] text-[var(--text-faint)] mt-1">rolling 8w avg</p>
      </div>

      <div>
        <p className="text-[10px] uppercase tracking-wider text-[var(--text-dim)] mb-0.5">Load trend</p>
        <div className="flex items-baseline gap-1.5">
          <span className="text-[22px] font-light tabular-nums leading-none" style={{
            color: signal?.trend === "progressing" ? "var(--positive)"
              : signal?.trend === "deloading" ? "var(--negative)"
              : "var(--neutral)"
          }}>
            {signal?.overload_pct != null ? `${signal.overload_pct > 0 ? "+" : ""}${signal.overload_pct.toFixed(0)}%` : "—"}
          </span>
        </div>
        <p className="text-[10px] text-[var(--text-faint)] mt-1">8w vs prior 8w</p>
      </div>
    </div>
  );
}

// ── Main export ───────────────────────────────────────────────────────────────

export function StrengthPanel() {
  const [picked, setPicked] = useState<string | null>(null);
  return (
    <div className="shc-card shc-enter p-5 space-y-6">
      <div className="flex items-baseline justify-between">
        <h2 className="shc-section-title">Strength Training</h2>
        <span className="text-[10.5px] text-[var(--text-faint)]">Fitbod · 2017 – present</span>
      </div>
      <p className="shc-helptext -mt-3">
        <span className="text-[var(--text-muted)]">How to read this. </span>
        Volume load (kg lifted/wk) drives hypertrophy &amp; strength; aim for slow-up trend.
        Push:pull ratio 0.8–1.2 keeps shoulders balanced. PR staleness &gt; 12 mo means it&apos;s
        time to revisit the lift.
      </p>

      <SessionHeader />
      <Heatmap />

      <MuscleBalance />

      <RecoveryCorrelation />

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
        <VolumeTrend />
        <PRTable onPick={setPicked} />
      </div>

      <TopExercisesTable onPick={setPicked} />

      <ProgressionDrawer exercise={picked} onClose={() => setPicked(null)} />
    </div>
  );
}
