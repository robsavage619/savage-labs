"use client";

import { useQuery } from "@tanstack/react-query";
import { api, type Briefing } from "@/lib/api";
import { Eyebrow, Dot } from "@/components/ui/metric";

const CALL_COLOR: Record<string, string> = {
  Push: "var(--positive)",
  Train: "var(--positive)",
  Maintain: "var(--neutral)",
  Easy: "var(--neutral)",
  Rest: "var(--negative)",
};

function AiBriefingStrip({ briefing }: { briefing: Briefing }) {
  const color = CALL_COLOR[briefing.training_call] ?? "var(--text-primary)";
  return (
    <div className="border-t border-[var(--hairline)] px-5 py-3 flex items-start gap-4">
      <div className="shrink-0">
        <p className="text-[9.5px] text-[var(--text-dim)] uppercase tracking-wider mb-0.5">Training call</p>
        <p className="text-[14px] font-semibold tabular-nums" style={{ color }}>{briefing.training_call}</p>
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-[11px] text-[var(--text-dim)] uppercase tracking-wider mb-0.5">{briefing.readiness_headline}</p>
        <p className="text-[11.5px] text-[var(--text-muted)] leading-relaxed">{briefing.coaching_note}</p>
        {briefing.flags.length > 0 && (
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {briefing.flags.map((f, i) => (
              <span
                key={i}
                className="rounded-full border border-[var(--hairline)] px-2 py-0.5 text-[9.5px] text-[var(--text-dim)]"
              >
                {f}
              </span>
            ))}
          </div>
        )}
      </div>
      <p className="shrink-0 text-[9px] text-[var(--text-faint)] tabular-nums self-end">
        {new Date(briefing.generated_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
      </p>
    </div>
  );
}

function tone(score: number | null | undefined): "positive" | "neutral" | "negative" {
  if (score == null) return "neutral";
  if (score >= 67) return "positive";
  if (score >= 34) return "neutral";
  return "negative";
}

function verdict(score: number | null | undefined): string {
  if (score == null) return "Awaiting data";
  if (score >= 80) return "Train hard";
  if (score >= 67) return "Push it";
  if (score >= 50) return "Moderate";
  if (score >= 34) return "Active recovery";
  return "Rest & restore";
}

function RangeBar({ value, min, max, tone }: { value: number; min: number; max: number; tone: "positive" | "neutral" | "negative" }) {
  const pct = Math.max(0, Math.min(100, ((value - min) / (max - min)) * 100));
  const color = tone === "positive" ? "var(--positive)" : tone === "negative" ? "var(--negative)" : "var(--neutral)";
  return (
    <div className="mt-1.5 h-[3px] w-full rounded-full bg-[oklch(1_0_0/0.06)]">
      <div
        className="h-full rounded-full"
        style={{ width: `${pct}%`, background: color, transition: "width 560ms cubic-bezier(0.2, 0.8, 0.2, 1)" }}
      />
    </div>
  );
}

function Slot({
  label,
  value,
  unit,
  sub,
  tone: t = "neutral",
  range,
}: {
  label: string;
  value: string;
  unit?: string;
  sub?: string;
  tone?: "positive" | "neutral" | "negative";
  range?: { min: number; max: number; cur: number };
}) {
  return (
    <div className="flex-1 min-w-[120px] px-4 py-3 border-r border-[var(--hairline)] last:border-r-0">
      <Eyebrow>{label}</Eyebrow>
      <div className="mt-1 flex items-baseline gap-1.5">
        <span className="metric-lg tabular-nums">{value}</span>
        {unit && <span className="text-[11px] text-[var(--text-dim)]">{unit}</span>}
      </div>
      {sub && <p className="mt-0.5 text-[11px] text-[var(--text-muted)] tabular-nums">{sub}</p>}
      {range && <RangeBar value={range.cur} min={range.min} max={range.max} tone={t} />}
    </div>
  );
}

export function CommandBriefing() {
  const readiness = useQuery({
    queryKey: ["readiness"],
    queryFn: api.readinessToday,
    refetchInterval: 5 * 60 * 1000,
  });
  const stats = useQuery({
    queryKey: ["stats-summary"],
    queryFn: api.statsSummary,
    refetchInterval: 5 * 60 * 1000,
  });
  const briefingQ = useQuery({
    queryKey: ["briefing"],
    queryFn: api.briefing,
    refetchInterval: 10 * 60 * 1000,
    staleTime: 5 * 60 * 1000,
  });

  const r = readiness.data;
  const s = stats.data;
  const score = r?.recovery_score ?? null;
  const t = tone(score);
  const v = verdict(score);

  if (readiness.isLoading || stats.isLoading || !r || !s) {
    return (
      <div className="shc-card overflow-hidden">
        <div className="flex animate-pulse">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="flex-1 h-[88px] border-r border-[var(--hairline)] last:border-r-0 shc-skeleton m-3 !rounded" />
          ))}
        </div>
      </div>
    );
  }

  const hrvDeltaPct =
    s.hrv.today && s.hrv.baseline_28d
      ? ((s.hrv.today - s.hrv.baseline_28d) / s.hrv.baseline_28d) * 100
      : null;

  const briefing = briefingQ.data && "training_call" in briefingQ.data ? briefingQ.data as Briefing : null;

  return (
    <div className="shc-card shc-enter overflow-hidden">
      <div className="flex flex-wrap">
        <div className="flex-[1.3] min-w-[180px] px-5 py-3.5 border-r border-[var(--hairline)] flex items-center gap-3">
          <Dot tone={t} />
          <div>
            <Eyebrow>Today · Verdict</Eyebrow>
            <p
              className="mt-0.5 text-[18px] font-medium tracking-tight"
              style={{ color: t === "positive" ? "var(--positive)" : t === "negative" ? "var(--negative)" : "var(--neutral)" }}
            >
              {v}
            </p>
          </div>
        </div>

        <Slot
          label="Recovery"
          value={score != null ? String(Math.round(score)) : "—"}
          sub={s.recovery_trend_slope_7d >= 0 ? "↑ 7d" : "↓ 7d"}
          tone={t}
          range={{ min: 0, max: 100, cur: score ?? 0 }}
        />
        <Slot
          label="HRV"
          value={r.hrv ? r.hrv.toFixed(0) : "—"}
          unit="ms"
          sub={hrvDeltaPct != null ? `${hrvDeltaPct >= 0 ? "+" : ""}${hrvDeltaPct.toFixed(1)}% vs 28d` : undefined}
          tone={hrvDeltaPct != null ? (hrvDeltaPct >= 0 ? "positive" : "negative") : "neutral"}
          range={
            s.hrv.baseline_28d
              ? { min: s.hrv.baseline_28d * 0.75, max: s.hrv.baseline_28d * 1.25, cur: r.hrv ?? s.hrv.baseline_28d }
              : undefined
          }
        />
        <Slot
          label="RHR"
          value={r.rhr ? String(r.rhr) : "—"}
          unit="bpm"
          sub={
            s.rhr.elevated_pct != null
              ? `${s.rhr.elevated_pct >= 0 ? "+" : ""}${s.rhr.elevated_pct.toFixed(1)}% vs 28d`
              : undefined
          }
          tone={s.rhr.elevated_pct != null ? (s.rhr.elevated_pct > 5 ? "negative" : s.rhr.elevated_pct < -2 ? "positive" : "neutral") : "neutral"}
          range={
            s.rhr.baseline_28d
              ? { min: s.rhr.baseline_28d * 0.85, max: s.rhr.baseline_28d * 1.2, cur: r.rhr ?? s.rhr.baseline_28d }
              : undefined
          }
        />
        <Slot
          label="Sleep"
          value={r.sleep_hours ? r.sleep_hours.toFixed(1) : "—"}
          unit="h"
          sub={s.sleep.avg_7d ? `${s.sleep.avg_7d.toFixed(1)}h · 7d avg` : undefined}
          tone={
            r.sleep_hours == null
              ? "neutral"
              : r.sleep_hours >= 7.5
              ? "positive"
              : r.sleep_hours >= 6.5
              ? "neutral"
              : "negative"
          }
          range={{ min: 4, max: 9, cur: r.sleep_hours ?? 7 }}
        />
        <Slot
          label="Readiness"
          value={String(Math.round(computeReadiness(r, s)))}
          sub="composite"
          tone={tone(computeReadiness(r, s))}
          range={{ min: 0, max: 100, cur: computeReadiness(r, s) }}
        />
      </div>
      {briefing && <AiBriefingStrip briefing={briefing} />}
    </div>
  );
}

function computeReadiness(
  r: { recovery_score: number; hrv: number; rhr: number; sleep_hours: number; energy: number | null },
  s: {
    hrv: { today: number | null; baseline_28d: number | null };
    rhr: { baseline_28d: number | null };
  },
): number {
  const hrvScore =
    s.hrv.today && s.hrv.baseline_28d ? Math.max(0, Math.min(100, 50 + ((s.hrv.today - s.hrv.baseline_28d) / s.hrv.baseline_28d) * 300)) : 50;
  const sleepScore = r.sleep_hours ? Math.max(0, Math.min(100, (r.sleep_hours / 8) * 100)) : 50;
  const rhrScore = s.rhr.baseline_28d && r.rhr ? Math.max(0, Math.min(100, 100 - ((r.rhr - s.rhr.baseline_28d) / s.rhr.baseline_28d) * 400)) : 50;
  const subj = r.energy != null ? r.energy * 10 : 70;
  return 0.4 * hrvScore + 0.3 * sleepScore + 0.2 * rhrScore + 0.1 * subj;
}
