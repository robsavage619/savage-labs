"use client";

import { useQuery } from "@tanstack/react-query";
import { Area, AreaChart, ResponsiveContainer } from "recharts";
import { api } from "@/lib/api";
import { Eyebrow, Metric } from "@/components/ui/metric";

function toneFor(score: number | null | undefined) {
  if (score == null) return { color: "var(--neutral)", token: "neutral" as const };
  if (score >= 67) return { color: "var(--positive)", token: "positive" as const };
  if (score >= 34) return { color: "var(--neutral)", token: "neutral" as const };
  return { color: "var(--negative)", token: "negative" as const };
}

function RecoveryArc({ score, color }: { score: number | null; color: string }) {
  const size = 168;
  const r = 66;
  const cx = size / 2;
  const cy = size / 2 + 14;
  const startAngle = -220;
  const sweepAngle = 260;
  const pct = score != null ? Math.min(100, Math.max(0, score)) / 100 : 0;

  const arc = (deg: number) => {
    const rad = (deg * Math.PI) / 180;
    return {
      x: Number((cx + r * Math.cos(rad)).toFixed(3)),
      y: Number((cy + r * Math.sin(rad)).toFixed(3)),
    };
  };
  const start = arc(startAngle);
  const trackEnd = arc(startAngle + sweepAngle);
  const fillEnd = arc(startAngle + sweepAngle * pct);
  const largeArc = sweepAngle > 180 ? 1 : 0;
  const fillLargeArc = sweepAngle * pct > 180 ? 1 : 0;

  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
      <defs>
        <linearGradient id="arc-fill" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.4" />
          <stop offset="100%" stopColor={color} stopOpacity="1" />
        </linearGradient>
      </defs>
      <path
        d={`M ${start.x} ${start.y} A ${r} ${r} 0 ${largeArc} 1 ${trackEnd.x} ${trackEnd.y}`}
        fill="none"
        stroke="oklch(1 0 0 / 0.06)"
        strokeWidth={9}
        strokeLinecap="round"
      />
      {pct > 0 && (
        <path
          d={`M ${start.x} ${start.y} A ${r} ${r} 0 ${fillLargeArc} 1 ${fillEnd.x} ${fillEnd.y}`}
          fill="none"
          stroke="url(#arc-fill)"
          strokeWidth={9}
          strokeLinecap="round"
          style={{ transition: "d 600ms cubic-bezier(0.2, 0.8, 0.2, 1)" }}
        />
      )}
      <text
        x={cx}
        y={cy - 6}
        textAnchor="middle"
        dominantBaseline="middle"
        fontSize={42}
        fontWeight={500}
        fill="var(--text-primary)"
        fontFamily="var(--font-geist-mono, monospace)"
        style={{ fontVariantNumeric: "tabular-nums", letterSpacing: "-0.02em" }}
      >
        {score ?? "—"}
      </text>
      <text
        x={cx}
        y={cy + 22}
        textAnchor="middle"
        fontSize={9.5}
        fill="var(--text-dim)"
        letterSpacing="0.15em"
      >
        RECOVERY
      </text>
    </svg>
  );
}

export function PillarRecovery() {
  const readiness = useQuery({ queryKey: ["readiness"], queryFn: api.readinessToday });
  const trend = useQuery({ queryKey: ["recovery-trend-14"], queryFn: () => api.recoveryTrend(14) });
  const stats = useQuery({ queryKey: ["stats-summary"], queryFn: api.statsSummary });

  const score = readiness.data?.recovery_score ?? null;
  const t = toneFor(score);

  const sparkData = trend.data?.map((p) => ({ date: p.date.slice(5), score: p.score })) ?? [];
  const first = sparkData[0]?.score ?? 0;
  const last = sparkData.at(-1)?.score ?? 0;
  const delta = last - first;

  const hrv = readiness.data?.hrv;
  const baselineHrv = stats.data?.hrv.baseline_28d;
  const hrvSigma = stats.data?.hrv.deviation_sigma;

  const rhr = readiness.data?.rhr;
  const rhrBase = stats.data?.rhr.baseline_28d;
  const rhrElevated = stats.data?.rhr.elevated_pct ?? 0;

  const drivers: { label: string; tone: "positive" | "neutral" | "negative" }[] = [];
  if (hrvSigma != null) {
    drivers.push({
      label: hrvSigma > 0.3 ? "HRV above baseline" : hrvSigma < -0.3 ? "HRV below baseline" : "HRV at baseline",
      tone: hrvSigma > 0.3 ? "positive" : hrvSigma < -0.3 ? "negative" : "neutral",
    });
  }
  if (rhrElevated != null) {
    drivers.push({
      label: rhrElevated > 3 ? "RHR elevated" : rhrElevated < -2 ? "RHR improving" : "RHR stable",
      tone: rhrElevated > 3 ? "negative" : rhrElevated < -2 ? "positive" : "neutral",
    });
  }
  const sleepH = readiness.data?.sleep_hours;
  if (sleepH != null) {
    drivers.push({
      label: sleepH >= 7.5 ? "Sleep sufficient" : sleepH >= 6.5 ? "Sleep short" : "Sleep deficit",
      tone: sleepH >= 7.5 ? "positive" : sleepH >= 6.5 ? "neutral" : "negative",
    });
  }

  return (
    <div className="shc-card shc-enter p-5 min-h-[320px] flex flex-col">
      <div className="flex items-baseline justify-between">
        <Eyebrow>Recovery intelligence</Eyebrow>
        <span className="text-[10.5px] text-[var(--text-dim)] tabular-nums">
          {delta >= 0 ? "+" : ""}
          {delta.toFixed(0)} · 14d
        </span>
      </div>

      <div className="flex items-center gap-5 mt-3">
        <RecoveryArc score={score != null ? Math.round(score) : 0} color={t.color} />
        <div className="flex-1 min-w-0">
          <div className="h-[72px] -mx-2">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={sparkData} margin={{ top: 4, right: 4, left: 4, bottom: 0 }}>
                <defs>
                  <linearGradient id="rec-spark" x1="0" x2="0" y1="0" y2="1">
                    <stop offset="0%" stopColor={t.color} stopOpacity="0.35" />
                    <stop offset="100%" stopColor={t.color} stopOpacity="0" />
                  </linearGradient>
                </defs>
                <Area dataKey="score" stroke={t.color} strokeWidth={1.5} fill="url(#rec-spark)" dot={false} isAnimationActive={false} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
          <p className="text-[10.5px] text-[var(--text-dim)] mt-1 tracking-wider uppercase">14d trend</p>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-3 mt-4">
        <div className="border-l border-[var(--hairline)] pl-3">
          <p className="text-[10px] text-[var(--text-dim)] uppercase tracking-wider">HRV</p>
          <div className="mt-0.5">
            <Metric value={hrv ? hrv.toFixed(0) : "—"} unit="ms" size="md" />
          </div>
          {hrvSigma != null && baselineHrv != null && (
            <p className="text-[10.5px] text-[var(--text-muted)] tabular-nums mt-0.5">
              {hrvSigma >= 0 ? "+" : ""}
              {hrvSigma.toFixed(2)}σ · vs {baselineHrv.toFixed(0)}
            </p>
          )}
        </div>
        <div className="border-l border-[var(--hairline)] pl-3">
          <p className="text-[10px] text-[var(--text-dim)] uppercase tracking-wider">RHR</p>
          <div className="mt-0.5">
            <Metric value={rhr ?? "—"} unit="bpm" size="md" />
          </div>
          {rhrBase != null && (
            <p className="text-[10.5px] text-[var(--text-muted)] tabular-nums mt-0.5">
              base {rhrBase.toFixed(0)}
            </p>
          )}
        </div>
        <div className="border-l border-[var(--hairline)] pl-3">
          <p className="text-[10px] text-[var(--text-dim)] uppercase tracking-wider">Skin Δ</p>
          <div className="mt-0.5">
            <Metric value="—" unit="°F" size="md" />
          </div>
          <p className="text-[10.5px] text-[var(--text-muted)] mt-0.5">pending WHOOP</p>
        </div>
      </div>

      <div className="mt-auto pt-4">
        <p className="text-[10px] text-[var(--text-dim)] uppercase tracking-wider mb-2">What&apos;s driving this</p>
        <ul className="space-y-1.5">
          {drivers.map((d) => (
            <li key={d.label} className="flex items-center gap-2 text-[12px] text-[var(--text-muted)]">
              <span
                className="inline-block h-1.5 w-1.5 rounded-full"
                style={{
                  background: d.tone === "positive" ? "var(--positive)" : d.tone === "negative" ? "var(--negative)" : "var(--neutral)",
                }}
              />
              {d.label}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
