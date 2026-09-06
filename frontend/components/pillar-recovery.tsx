"use client";

import { useQuery } from "@tanstack/react-query";
import { Area, AreaChart, ResponsiveContainer, ReferenceLine, Scatter, ComposedChart, XAxis, YAxis, Tooltip } from "recharts";
import { api } from "@/lib/api";
import { Eyebrow, Metric } from "@/components/ui/metric";
import { PlainRead } from "@/components/plain-read";
import { recoveryRead } from "@/lib/reads";

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
    <svg
      viewBox={`0 0 ${size} ${size}`}
      className="block h-auto w-full"
      role="img"
      aria-label="WHOOP recovery score"
    >
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
      {/* WHOOP's own recovery score, NOT the composite readiness in the header.
          Labelled bare "RECOVERY" these read as the same quantity disagreeing —
          on 2026-07-25 the screen carried 71 here and 66 up top. */}
      <text
        x={cx}
        y={cy + 22}
        textAnchor="middle"
        fontSize={9.5}
        fill="var(--text-dim)"
        letterSpacing="0.15em"
      >
        WHOOP RECOVERY
      </text>
    </svg>
  );
}

export function PillarRecovery() {
  const readiness = useQuery({ queryKey: ["readiness"], queryFn: api.readinessToday });
  const trend = useQuery({ queryKey: ["recovery-trend-14"], queryFn: () => api.recoveryTrend(14) });
  const stats = useQuery({ queryKey: ["stats-summary"], queryFn: api.statsSummary });
  const dailyState = useQuery({ queryKey: ["daily-state"], queryFn: api.dailyState });
  // beta_blocker_adjusted is true only on days propranolol was actually taken (PRN).
  // Reading from DailyState instead of the meds list prevents the badge firing every day.
  const betaBlocker = dailyState.data?.readiness.beta_blocker_adjusted ?? false;

  const score = readiness.data?.recovery_score ?? null;
  const t = toneFor(score);

  // Plain-English layer: ONE read, on the headline number. The per-channel HRV
  // and RHR reads still exist in lib/reads.ts — they are just not rendered here,
  // because three stacked paragraphs displaced the data they were explaining.
  const state = dailyState.data;
  const recRead = state ? recoveryRead(state) : null;

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

  const recoveryToday = useQuery({ queryKey: ["recovery-today"], queryFn: api.recoveryToday });
  const skinDelta = recoveryToday.data?.skin_temp_delta ?? null;
  const skinTone =
    skinDelta == null
      ? "neutral"
      : Math.abs(skinDelta) >= 0.9
        ? "negative"
        : Math.abs(skinDelta) >= 0.54
          ? "neutral"
          : "positive";

  const drivers: { label: string; tone: "positive" | "neutral" | "negative" }[] = [];
  if (hrvSigma != null) {
    const baseLabel =
      hrvSigma > 0.3 ? "HRV above baseline" : hrvSigma < -0.3 ? "HRV below baseline" : "HRV at baseline";
    drivers.push({
      label: betaBlocker ? `${baseLabel} (β-blocker blunts signal)` : baseLabel,
      tone: hrvSigma > 0.3 ? "positive" : hrvSigma < -0.3 ? (betaBlocker ? "neutral" : "negative") : "neutral",
    });
  }
  if (rhrElevated != null) {
    drivers.push({
      label: rhrElevated > 3 ? "RHR elevated" : rhrElevated < -2 ? "RHR improving" : "RHR stable",
      tone: rhrElevated > 3 ? "negative" : rhrElevated < -2 ? "positive" : "neutral",
    });
  }
  if (skinDelta != null && Math.abs(skinDelta) >= 0.9) {
    drivers.push({
      label: skinDelta > 0 ? `Skin temp +${skinDelta.toFixed(1)}°F — possible illness` : `Skin temp ${skinDelta.toFixed(1)}°F below baseline`,
      tone: "negative",
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
    <div className="@container shc-card shc-enter p-6 min-h-[320px] flex flex-col">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <Eyebrow className="min-w-0">WHOOP recovery</Eyebrow>
        <span className="text-[10.5px] text-[var(--text-dim)] tabular-nums shrink-0">
          {delta >= 0 ? "+" : ""}
          {delta.toFixed(0)} · 14d
        </span>
      </div>

      <div className="flex items-center gap-3 @lg:gap-5 mt-3 min-w-0 flex-wrap">
        <div className="relative flex-shrink-0 w-[132px] @xs:w-[148px] @lg:w-[168px]">
          <RecoveryArc score={score != null ? Math.round(score) : null} color={t.color} />
          <div className="shc-reticle" aria-hidden />
        </div>
        <div className="flex-1 min-w-0">
          <div className="h-[72px] -mx-2">
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={sparkData} margin={{ top: 4, right: 4, left: 4, bottom: 0 }}>
                <defs>
                  <linearGradient id="rec-spark" x1="0" x2="0" y1="0" y2="1">
                    <stop offset="0%" stopColor={t.color} stopOpacity="0.35" />
                    <stop offset="100%" stopColor={t.color} stopOpacity="0" />
                  </linearGradient>
                </defs>
                <YAxis hide domain={[0, 100]} />
                <XAxis dataKey="date" hide />
                <ReferenceLine y={67} stroke="var(--chart-grid)" strokeDasharray="2 3" strokeOpacity={0.6} />
                <ReferenceLine y={34} stroke="var(--chart-grid)" strokeDasharray="2 3" strokeOpacity={0.6} />
                <Area
                  dataKey="score"
                  stroke={t.color}
                  strokeWidth={1.5}
                  fill="url(#rec-spark)"
                  dot={(props) => {
                    const { cx, cy, payload } = props;
                    if (payload?.score == null || payload.score >= 34) return <g key={props.index} />;
                    return (
                      <circle
                        key={props.index}
                        cx={cx}
                        cy={cy}
                        r={2.5}
                        fill="var(--negative)"
                        stroke="var(--bg)"
                        strokeWidth={1}
                      />
                    );
                  }}
                  isAnimationActive={false}
                />
                <Tooltip
                  contentStyle={{
                    background: "var(--card-hover)",
                    border: "1px solid var(--hairline-strong)",
                    borderRadius: 6,
                    fontSize: 10.5,
                  }}
                  cursor={{ stroke: "var(--hairline-strong)" }}
                  formatter={(v: number) => [`${v?.toFixed?.(0) ?? v}`, "recovery"]}
                />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
          <p className="text-[10.5px] text-[var(--text-dim)] mt-1 tracking-wider uppercase">14d trend</p>
        </div>
      </div>

      {recRead && (
        <PlainRead state={recRead.state} className="mt-3">
          {recRead.read}
        </PlainRead>
      )}

      <div className="grid grid-cols-3 gap-2 @lg:gap-3 mt-4 min-w-0">
        <div className="min-w-0 border-l border-[var(--hairline)] pl-2 @lg:pl-3">
          <div className="flex flex-wrap items-center justify-between gap-x-1.5 gap-y-0.5 min-w-0">
            <div className="flex items-center gap-1.5 min-w-0">
            <p className="text-[10px] text-[var(--text-dim)] uppercase tracking-wider">HRV</p>
            {betaBlocker && (
              <span
                className="text-[8.5px] font-medium uppercase tracking-wider px-1 py-px rounded-sm"
                style={{
                  color: "var(--neutral)",
                  background: "var(--neutral-soft)",
                  border: "1px solid oklch(0.75 0.18 75 / 0.25)",
                }}
                title="Propranolol blunts HRV — interpret σ deviations cautiously"
              >
                β-adj
              </span>
            )}
            </div>
            <span className="shrink-0" style={{ fontFamily: "var(--font-geist-mono, monospace)", fontSize: 7, color: "var(--text-faint)", letterSpacing: "0.06em" }}>CH-01</span>
          </div>
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
        <div className="min-w-0 border-l border-[var(--hairline)] pl-2 @lg:pl-3">
          <div className="flex flex-wrap items-center justify-between gap-x-1.5 gap-y-0.5 min-w-0">
            <p className="text-[10px] text-[var(--text-dim)] uppercase tracking-wider">RHR</p>
            <span className="shrink-0" style={{ fontFamily: "var(--font-geist-mono, monospace)", fontSize: 7, color: "var(--text-faint)", letterSpacing: "0.06em" }}>CH-02</span>
          </div>
          <div className="mt-0.5">
            <Metric value={rhr ?? "—"} unit="bpm" size="md" />
          </div>
          {rhrBase != null && (
            <p className="text-[10.5px] text-[var(--text-muted)] tabular-nums mt-0.5">
              base {rhrBase.toFixed(0)}
            </p>
          )}
        </div>
        <div className="min-w-0 border-l border-[var(--hairline)] pl-2 @lg:pl-3">
          <div className="flex flex-wrap items-center justify-between gap-x-1.5 gap-y-0.5 min-w-0">
            <p className="text-[10px] text-[var(--text-dim)] uppercase tracking-wider">Skin Δ</p>
            <span className="shrink-0" style={{ fontFamily: "var(--font-geist-mono, monospace)", fontSize: 7, color: "var(--text-faint)", letterSpacing: "0.06em" }}>CH-03</span>
          </div>
          <div className="mt-0.5">
            <Metric
              value={
                skinDelta != null
                  ? `${skinDelta > 0 ? "+" : ""}${skinDelta.toFixed(1)}`
                  : "—"
              }
              unit="°F"
              size="md"
              tone={skinTone}
            />
          </div>
          <p className="text-[10.5px] text-[var(--text-muted)] tabular-nums mt-0.5">
            {skinDelta == null
              ? "no data"
              : Math.abs(skinDelta) >= 0.9
                ? "elevated · illness?"
                : Math.abs(skinDelta) >= 0.54
                  ? "watch"
                  : "normal"}
          </p>
        </div>
      </div>

      <div className="mt-4">
        <p className="text-[10px] text-[var(--text-dim)] uppercase tracking-wider mb-2" style={{ fontFamily: "var(--font-orbitron)", letterSpacing: "0.18em" }}>What&apos;s driving this</p>
        <ul className="space-y-1.5">
          {drivers.map((d) => (
            <li key={d.label} className="flex items-start gap-2 text-[12px] text-[var(--text-muted)] min-w-0">
              <span
                className="inline-block h-1.5 w-1.5 shrink-0 rounded-full mt-[5px]"
                style={{
                  background: d.tone === "positive" ? "var(--positive)" : d.tone === "negative" ? "var(--negative)" : "var(--neutral)",
                }}
              />
              <span className="min-w-0 leading-snug">{d.label}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
