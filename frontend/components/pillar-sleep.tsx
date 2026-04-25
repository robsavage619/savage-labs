"use client";

import { useQuery } from "@tanstack/react-query";
import { api, type SleepEntry } from "@/lib/api";
import { Eyebrow, Metric } from "@/components/ui/metric";

interface Stages {
  deep_min?: number;
  rem_min?: number;
  light_min?: number;
  awake_min?: number;
}

function parseStages(raw: string | null): Stages {
  if (!raw) return {};
  let obj: Record<string, unknown>;
  try {
    obj = JSON.parse(raw.replace(/'/g, '"'));
  } catch {
    return {};
  }
  // Normalized format
  if ("deep_min" in obj) return obj as Stages;
  // Raw WHOOP millisecond format
  const ms = (k: string) => typeof obj[k] === "number" ? Math.round((obj[k] as number) / 60000) : 0;
  return {
    deep_min: ms("total_slow_wave_sleep_time_milli"),
    rem_min: ms("total_rem_sleep_time_milli"),
    light_min: ms("total_light_sleep_time_milli"),
    awake_min: ms("total_awake_time_milli"),
  };
}

const STAGE_COLOR = {
  deep: "var(--stage-deep)",
  rem: "var(--stage-rem)",
  light: "var(--stage-light)",
  awake: "var(--stage-awake)",
} as const;

function SleepRow({ entry }: { entry: SleepEntry }) {
  const st = parseStages(entry.stages);
  const total = (st.deep_min ?? 0) + (st.rem_min ?? 0) + (st.light_min ?? 0) + (st.awake_min ?? 0);
  if (!total) return null;
  const segs = [
    { k: "deep" as const, min: st.deep_min ?? 0 },
    { k: "rem" as const, min: st.rem_min ?? 0 },
    { k: "light" as const, min: st.light_min ?? 0 },
    { k: "awake" as const, min: st.awake_min ?? 0 },
  ].filter((s) => s.min > 0);
  const label = new Date(entry.date + "T00:00:00").toLocaleDateString("en-US", { weekday: "short" });
  return (
    <div className="flex items-center gap-3 group">
      <span className="text-[10.5px] text-[var(--text-dim)] w-7">{label}</span>
      <div className="flex h-[8px] flex-1 rounded-full overflow-hidden gap-px bg-[oklch(1_0_0/0.04)]">
        {segs.map((s) => (
          <div
            key={s.k}
            className="h-full transition-all"
            style={{ width: `${(s.min / total) * 100}%`, background: STAGE_COLOR[s.k] }}
            title={`${s.k}: ${s.min}m`}
          />
        ))}
      </div>
      <span className="text-[11.5px] text-[var(--text-muted)] tabular-nums w-10 text-right">
        {(total / 60).toFixed(1)}h
      </span>
    </div>
  );
}

export function PillarSleep() {
  const { data, isLoading } = useQuery({
    queryKey: ["sleep-7"],
    queryFn: () => api.sleepRecent(7),
    refetchInterval: 5 * 60 * 1000,
  });
  const stats = useQuery({ queryKey: ["stats-summary"], queryFn: api.statsSummary });

  const entries = data ?? [];
  const parsed = entries.map((e) => ({ e, s: parseStages(e.stages) }));
  const totals = parsed.map(({ s }) => (s.deep_min ?? 0) + (s.rem_min ?? 0) + (s.light_min ?? 0) + (s.awake_min ?? 0));
  const totalMinutes = totals.reduce((a, b) => a + b, 0);
  const avgDeepPct = totalMinutes ? (parsed.reduce((a, { s }) => a + (s.deep_min ?? 0), 0) / totalMinutes) * 100 : 0;
  const avgRemPct = totalMinutes ? (parsed.reduce((a, { s }) => a + (s.rem_min ?? 0), 0) / totalMinutes) * 100 : 0;
  const avgHours = stats.data?.sleep.avg_7d ?? 0;
  const consistency = stats.data?.sleep.consistency_stdev ?? null;

  const best = parsed.reduce<{ e: SleepEntry; total: number } | null>((best, cur) => {
    const total = (cur.s.deep_min ?? 0) + (cur.s.rem_min ?? 0) + (cur.s.light_min ?? 0);
    if (!best || total > best.total) return { e: cur.e, total };
    return best;
  }, null);

  const consistencyLabel =
    consistency == null
      ? "—"
      : consistency < 0.5
      ? "Tight"
      : consistency < 1.0
      ? "Steady"
      : consistency < 1.5
      ? "Variable"
      : "Scattered";

  const consistencyTone: "positive" | "neutral" | "negative" =
    consistency == null ? "neutral" : consistency < 0.8 ? "positive" : consistency < 1.3 ? "neutral" : "negative";

  return (
    <div className="shc-card shc-enter p-5 min-h-[320px] flex flex-col">
      <div className="flex items-baseline justify-between">
        <Eyebrow>Sleep architecture</Eyebrow>
        <span className="text-[10.5px] text-[var(--text-dim)] tabular-nums">last 7 nights</span>
      </div>

      <div className="grid grid-cols-4 gap-2 mt-3">
        <div>
          <p className="text-[10px] text-[var(--text-dim)] uppercase tracking-wider">Avg</p>
          <Metric value={avgHours ? avgHours.toFixed(1) : "—"} unit="h" size="md" />
        </div>
        <div>
          <p className="text-[10px] text-[var(--text-dim)] uppercase tracking-wider">Deep</p>
          <Metric value={avgDeepPct ? avgDeepPct.toFixed(0) : "—"} unit="%" size="md" />
        </div>
        <div>
          <p className="text-[10px] text-[var(--text-dim)] uppercase tracking-wider">REM</p>
          <Metric value={avgRemPct ? avgRemPct.toFixed(0) : "—"} unit="%" size="md" />
        </div>
        <div>
          <p className="text-[10px] text-[var(--text-dim)] uppercase tracking-wider">Consist.</p>
          <Metric value={consistencyLabel} size="md" tone={consistencyTone} />
          {consistency != null && (
            <p className="text-[10px] text-[var(--text-muted)] tabular-nums mt-0.5">σ {consistency.toFixed(2)}h</p>
          )}
        </div>
      </div>

      <div className="mt-4 space-y-2">
        {isLoading || !entries.length
          ? Array.from({ length: 5 }).map((_, i) => <div key={i} className="shc-skeleton h-[16px]" />)
          : entries.slice(-7).map((e, i) => <SleepRow key={`${e.date}-${i}`} entry={e} />)}
      </div>

      <div className="flex gap-3 mt-3 text-[9.5px] text-[var(--text-faint)] uppercase tracking-wider">
        {(["deep", "rem", "light", "awake"] as const).map((k) => (
          <span key={k} className="flex items-center gap-1">
            <span className="inline-block h-2 w-2 rounded-sm" style={{ background: STAGE_COLOR[k] }} />
            {k}
          </span>
        ))}
      </div>

      {best && (
        <div className="mt-auto pt-3 text-[11.5px] text-[var(--text-muted)]">
          <span className="text-[var(--text-dim)]">Best night </span>
          <span className="text-[var(--text-primary)] tabular-nums">
            {new Date(best.e.date + "T00:00:00").toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" })}
          </span>
          <span className="text-[var(--text-dim)]"> · deep </span>
          <span className="tabular-nums">{(((best.e ? parseStages(best.e.stages).deep_min ?? 0 : 0) / best.total) * 100).toFixed(0)}%</span>
        </div>
      )}
    </div>
  );
}
