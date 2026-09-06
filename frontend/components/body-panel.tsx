"use client";

import { useQuery } from "@tanstack/react-query";
import { WarningIcon } from "@/components/ui/icons";
import {
  Area,
  Bar,
  ComposedChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
} from "recharts";
import { api } from "@/lib/api";
import { Eyebrow } from "@/components/ui/metric";

// ── Weight trend ─────────────────────────────────────────────────────────────

function rollingAvg(data: { lbs: number | null }[], window: number) {
  return data.map((_, i) => {
    const slice = data
      .slice(Math.max(0, i - window + 1), i + 1)
      .filter((x): x is { lbs: number } => x.lbs != null);
    if (!slice.length) return null;
    return slice.reduce((s, x) => s + x.lbs, 0) / slice.length;
  });
}

/**
 * Flag readings that cannot be this body.
 *
 * The feed carries two 138 lb entries from May 2026 sitting inside a run of
 * 233–239 lb — a 100 lb round trip in five days, so a different person's scale
 * session or a unit slip, not a measurement. Left in, they drag the y-domain
 * down by a hundred pounds and gouge the rolling mean, which is what made this
 * chart unreadable.
 *
 * They are not silently dropped: excluded from the trend and the domain, drawn
 * in the negative colour, and counted in a note under the chart.
 */
function markImplausible(data: { lbs: number }[]): boolean[] {
  const n = data.length;
  return data.map((d, i) => {
    const lo = Math.max(0, i - 3);
    const neighbours = data
      .slice(lo, Math.min(n, i + 4))
      .filter((_, j) => lo + j !== i)
      .map((x) => x.lbs)
      .sort((a, b) => a - b);
    if (neighbours.length < 4) return false;
    const median = neighbours[Math.floor(neighbours.length / 2)];
    return Math.abs(d.lbs - median) / median > 0.25;
  });
}

const CHECKIN_COLOR = "var(--sl-accent)";

const WtTooltip = ({ active, payload, label }: {
  active?: boolean;
  payload?: { dataKey: string; value: number | null; payload?: { source?: string } }[];
  label?: string | number;
}) => {
  if (!active || !payload?.length) return null;
  const when =
    typeof label === "number"
      ? new Date(label).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" })
      : label;
  const lbs = payload.find((p) => p.dataKey === "lbs")?.value;
  const avg = payload.find((p) => p.dataKey === "avg")?.value;
  const source = payload.find((p) => p.dataKey === "lbs")?.payload?.source;
  return (
    <div className="rounded-lg border px-3 py-2 text-[11px] font-mono" style={{ background: "var(--card-hover)", borderColor: "var(--hairline-strong)", minWidth: 140 }}>
      <p className="text-[var(--text-dim)] mb-1">{when}</p>
      {lbs && <p className="text-[var(--text-primary)]">{lbs} lbs</p>}
      {avg && <p className="text-[var(--text-muted)]">{avg.toFixed(1)} lbs 7d avg</p>}
      {source && (
        <p className="mt-1 text-[9.5px]" style={{ color: source === "checkin" ? CHECKIN_COLOR : "var(--text-faint)" }}>
          {source === "checkin" ? "● daily log" : "○ Apple Health"}
        </p>
      )}
    </div>
  );
};

function WeightTrend() {
  const { data = [], isLoading } = useQuery({
    queryKey: ["body-weight"],
    queryFn: () => api.bodyTrend(),
    refetchInterval: 3_600_000,
  });

  const bad = markImplausible(data);
  const avgs = rollingAvg(
    data.map((d, i) => ({ lbs: bad[i] ? null : d.lbs })),
    7,
  );
  // Time, not index. These weigh-ins are spread unevenly across nine years —
  // one in 2017, a cluster this summer — so an ordinal axis compresses the gaps
  // and stretches the clusters, which is exactly backwards for a weight trend.
  const formatted = data.map((d, i) => ({
    t: new Date(`${d.date}T00:00:00`).getTime(),
    label: d.date,
    lbs: bad[i] ? null : d.lbs,
    bad: bad[i] ? d.lbs : null,
    avg: avgs[i] == null ? null : +avgs[i]!.toFixed(1),
    source: d.source,
  }));
  const badCount = bad.filter(Boolean).length;

  // The excluded readings must not define the axis — that is the whole point —
  // but they should still be visible, so they are pinned to the domain edge.
  const cleanVals = data.filter((_, i) => !bad[i]).map((d) => d.lbs);
  // Snapped to 5 lb so the axis ticks come out even rather than ending on a
  // ragged domain bound.
  const yMin = cleanVals.length ? Math.floor((Math.min(...cleanVals) - 4) / 5) * 5 : 0;
  const yMax = cleanVals.length ? Math.ceil((Math.max(...cleanVals) + 4) / 5) * 5 : 1;
  for (const row of formatted) {
    if (row.bad != null) row.bad = Math.min(yMax, Math.max(yMin, row.bad));
  }

  const clean = data.filter((_, i) => !bad[i]);
  const latest = clean[clean.length - 1];
  const earliest = clean[0];
  const delta = latest && earliest ? +(latest.lbs - earliest.lbs).toFixed(1) : null;
  const deltaColor = delta == null ? "var(--text-faint)" : delta <= 0 ? "var(--positive)" : "var(--negative)";
  const checkinCount = data.filter(d => d.source === "checkin").length;

  return (
    <div className="space-y-2">
      <div className="flex items-baseline justify-between">
        <div className="flex items-baseline gap-2">
          <Eyebrow>Body weight · all-time</Eyebrow>
          {checkinCount > 0 && (
            <span className="text-[9px] tabular-nums" style={{ color: CHECKIN_COLOR, fontFamily: "var(--font-orbitron)", letterSpacing: "0.1em" }}>
              {checkinCount} logged
            </span>
          )}
        </div>
        <div className="flex items-baseline gap-3">
          {latest && (
            <span className="text-[11px] font-mono tabular-nums text-[var(--text-primary)]">{latest.lbs} lbs</span>
          )}
          {delta != null && (
            <span className="text-[10.5px] font-mono tabular-nums" style={{ color: deltaColor }}>
              {delta > 0 ? "+" : ""}{delta} lbs over period
            </span>
          )}
        </div>
      </div>
      {isLoading ? (
        <div className="h-[140px] shc-skeleton rounded" />
      ) : data.length === 0 ? (
        <p className="text-[12px] text-[var(--text-faint)] py-8 text-center">No weight data</p>
      ) : (
        <ResponsiveContainer width="100%" height={140}>
          <ComposedChart data={formatted} margin={{ top: 6, right: 4, left: 0, bottom: 0 }}>
            <defs>
              <linearGradient id="wt-fill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="var(--chart-line)" stopOpacity={0.22} />
                <stop offset="100%" stopColor="var(--chart-line)" stopOpacity={0} />
              </linearGradient>
            </defs>
            <XAxis
              dataKey="t"
              type="number"
              scale="time"
              domain={["dataMin", "dataMax"]}
              tick={{ fontSize: 9.5, fill: "var(--text-faint)" }}
              tickLine={false}
              axisLine={false}
              tickFormatter={(t: number) =>
                new Date(t).toLocaleDateString(undefined, { month: "short", year: "2-digit" })
              }
              minTickGap={44}
            />
            <YAxis
              tick={{ fontSize: 9.5, fill: "var(--text-faint)" }}
              tickLine={false}
              axisLine={false}
              domain={[yMin, yMax]}
              allowDataOverflow
              width={34}
            />
            <Tooltip content={<WtTooltip />} cursor={{ stroke: "var(--hairline-strong)" }} />
            <Area
              dataKey="avg"
              stroke="none"
              fill="url(#wt-fill)"
              isAnimationActive={false}
              connectNulls
            />
            {/* Raw weigh-ins as points, the rolling mean as the line. The
                measurement and the trend are different claims and should not
                share a mark. */}
            <Line
              dataKey="lbs"
              stroke="none"
              dot={{ r: 1.6, fill: "var(--text-faint)", stroke: "none" }}
              isAnimationActive={false}
            />
            <Line
              dataKey="avg"
              stroke="var(--chart-line)"
              strokeWidth={2}
              dot={false}
              isAnimationActive={false}
              connectNulls
            />
            <Line
              dataKey="bad"
              stroke="none"
              dot={{ r: 2.4, fill: "none", stroke: "var(--negative)", strokeWidth: 1 }}
              isAnimationActive={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      )}
      {badCount > 0 && (
        <p className="text-[10px] text-[var(--text-faint)]">
          <span style={{ color: "var(--negative)" }}>○</span> {badCount} reading
          {badCount === 1 ? "" : "s"} excluded from the trend — more than 25% off the
          surrounding weigh-ins, so a scale or unit error rather than a measurement. Fix at the
          source and they come back.
        </p>
      )}
    </div>
  );
}

// ── VO2 Max ──────────────────────────────────────────────────────────────────

const VO2_ZONES = [
  { min: 55, label: "Superior", color: "var(--positive)" },
  { min: 47, label: "Excellent", color: "oklch(0.72 0.18 145)" },
  { min: 39, label: "Good", color: "var(--neutral)" },
  { min: 31, label: "Fair", color: "oklch(0.72 0.18 45)" },
  { min: 0, label: "Poor", color: "var(--negative)" },
];

function VO2Zone(val: number) {
  return VO2_ZONES.find(z => val >= z.min) ?? VO2_ZONES[VO2_ZONES.length - 1];
}

function VO2MaxPanel() {
  const { data = [], isLoading } = useQuery({
    queryKey: ["vo2max"],
    queryFn: api.bodyVO2Max,
    refetchInterval: 3_600_000,
  });

  const latest = data[data.length - 1];
  const peak = data.length ? data.reduce((best, d) => d.vo2max > best.vo2max ? d : best, data[0]) : null;
  const zone = latest ? VO2Zone(latest.vo2max) : null;
  const delta = latest && peak ? +(latest.vo2max - peak.vo2max).toFixed(1) : null;
  const formatted = data.map(d => ({ label: d.date.slice(0, 7), vo2max: d.vo2max }));

  return (
    <div className="space-y-2">
      <div className="flex items-baseline justify-between">
        <Eyebrow>VO₂ max · {latest?.source === "apple_watch" ? "Apple Watch" : "estimated from WHOOP RHR"}</Eyebrow>
        {latest && zone && (
          <span className="text-[10.5px] font-medium" style={{ color: zone.color }}>{zone.label} for age (39)</span>
        )}
      </div>
      {isLoading ? (
        <div className="h-[140px] shc-skeleton rounded" />
      ) : data.length === 0 ? (
        <p className="text-[12px] text-[var(--text-faint)] py-6 text-center">No RHR data to estimate VO₂ max</p>
      ) : (
        <div className="space-y-3">
          <div className="flex items-end gap-6">
            <div>
              <p className="text-[9.5px] uppercase tracking-wider text-[var(--text-faint)] mb-0.5">Current</p>
              <div className="flex items-baseline gap-1.5">
                <span className="text-[28px] font-light tabular-nums leading-none" style={{ color: zone?.color }}>
                  {latest?.vo2max}
                </span>
                <span className="text-[11px] text-[var(--text-dim)]">mL/kg/min</span>
              </div>
            </div>
            {peak && (
              <div>
                <p className="text-[9.5px] uppercase tracking-wider text-[var(--text-faint)] mb-0.5">Peak ({peak.date.slice(0,7)})</p>
                <div className="flex items-baseline gap-1.5">
                  <span className="text-[20px] font-light tabular-nums leading-none text-[var(--text-muted)]">{peak.vo2max}</span>
                </div>
              </div>
            )}
            {delta != null && delta < 0 && (
              <div>
                <p className="text-[9.5px] uppercase tracking-wider text-[var(--text-faint)] mb-0.5">From peak</p>
                <div className="flex items-baseline gap-1">
                  <span className="text-[20px] font-light tabular-nums leading-none text-[var(--negative)]">{delta}</span>
                  <span className="text-[11px] text-[var(--negative)]">↓</span>
                </div>
              </div>
            )}
          </div>
          {delta != null && delta < -5 && (
            <p className="text-[10.5px] leading-snug" style={{ color: "var(--negative)" }}>
              <WarningIcon size={11} className="inline mr-1 align-middle" />Decline is ~4× expected age-related rate. Priority: zone 2 cardio 3×/wk.
            </p>
          )}
          <p className="text-[10px] text-[var(--text-faint)] leading-snug">
            {latest && latest.source === "apple_watch"
              ? "Direct Apple Watch measurement (cardiorespiratory fitness test)."
              : "Uth-Sørensen: 15.3 × HRmax/RHR · HRmax = 208 − (0.7 × age) = 180.7 (Tanaka). Propranolol PRN suppresses RHR → floor estimate on dosing days."}
          </p>
          <ResponsiveContainer width="100%" height={80}>
            <ComposedChart data={formatted} margin={{ top: 4, right: 0, left: -20, bottom: 0 }}>
              <XAxis dataKey="label" tick={{ fontSize: 9.5, fill: "var(--text-faint)" }} tickLine={false} axisLine={false} interval={Math.floor(formatted.length / 5) || 1} />
              <YAxis tick={{ fontSize: 9.5, fill: "var(--text-faint)" }} tickLine={false} axisLine={false} domain={[35, 55]} />
              <Tooltip contentStyle={{ background: "var(--card-hover)", border: "1px solid var(--hairline-strong)", borderRadius: 8, fontSize: 11 }} cursor={{ stroke: "var(--hairline-strong)" }} />
              {peak && <ReferenceLine x={peak.date.slice(0,7)} stroke="var(--neutral)" strokeDasharray="3 2" />}
              <Line dataKey="vo2max" stroke={zone?.color ?? "var(--chart-line)"} strokeWidth={2} dot={false} isAnimationActive={false} />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}

// ── Steps ─────────────────────────────────────────────────────────────────────

function StepsPanel() {
  const recent = useQuery({
    queryKey: ["steps-90"],
    queryFn: () => api.bodySteps(90),
    refetchInterval: 3_600_000,
  });
  // Fall back to all-time if no recent data (Apple Health export may be older)
  const historical = useQuery({
    queryKey: ["steps-alltime"],
    queryFn: () => api.bodySteps(4000),
    enabled: !recent.isLoading && recent.data?.length === 0,
    refetchInterval: 3_600_000,
  });

  const isLoading = recent.isLoading || historical.isLoading;
  const data = recent.data?.length ? recent.data : (historical.data ?? []);
  const windowLabel = recent.data?.length ? "90 days" : data.length ? "all-time" : "";

  const avg = data.length ? Math.round(data.reduce((s, d) => s + d.steps, 0) / data.length) : 0;
  const formatted = data.map(d => ({ label: d.date.slice(5), steps: d.steps }));

  const StepTooltip = ({ active, payload, label }: {
    active?: boolean;
    payload?: { value: number | null }[];
    label?: string;
  }) => {
    if (!active || !payload?.length) return null;
    return (
      <div className="rounded-lg border px-3 py-2 text-[11px] font-mono" style={{ background: "var(--card-hover)", borderColor: "var(--hairline-strong)" }}>
        <p className="text-[var(--text-dim)] mb-1">{label}</p>
        <p className="text-[var(--text-primary)]">{payload[0].value?.toLocaleString()} steps</p>
      </div>
    );
  };

  return (
    <div className="space-y-2">
      <div className="flex items-baseline justify-between">
        <Eyebrow>Daily steps · {windowLabel || "—"}</Eyebrow>
        {avg > 0 && (
          <span className="text-[10.5px] font-mono tabular-nums" style={{ color: avg >= 10000 ? "var(--positive)" : avg >= 7500 ? "var(--neutral)" : "var(--negative)" }}>
            avg {avg.toLocaleString()}/day
            {avg >= 10000 ? " · on target" : avg >= 7500 ? " · near target" : " · below 10k goal"}
          </span>
        )}
      </div>
      {isLoading ? (
        <div className="h-[100px] shc-skeleton rounded" />
      ) : data.length === 0 ? (
        <p className="text-[12px] text-[var(--text-faint)] py-6 text-center">No step data — Apple Health export not yet ingested</p>
      ) : (
        <ResponsiveContainer width="100%" height={100}>
          <ComposedChart data={formatted} margin={{ top: 4, right: 0, left: -20, bottom: 0 }}>
            <XAxis dataKey="label" tick={{ fontSize: 9.5, fill: "var(--text-faint)" }} tickLine={false} axisLine={false} interval={Math.floor(formatted.length / 6) || 1} />
            <YAxis tick={{ fontSize: 9.5, fill: "var(--text-faint)" }} tickLine={false} axisLine={false} tickFormatter={v => `${(v / 1000).toFixed(0)}k`} />
            <Tooltip content={<StepTooltip />} cursor={{ fill: "oklch(1 0 0 / 0.03)" }} />
            <ReferenceLine y={10000} stroke="var(--chart-baseline)" strokeDasharray="3 3" />
            <Bar dataKey="steps" fill="var(--chart-line-2)" radius={[2, 2, 0, 0]} maxBarSize={6} isAnimationActive={false} />
          </ComposedChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}

// ── Dual-source RHR ──────────────────────────────────────────────────────────

function RHRPanel() {
  const { data = [], isLoading } = useQuery({
    queryKey: ["rhr-trend-90"],
    queryFn: () => api.bodyRHRTrend(90),
    refetchInterval: 3_600_000,
  });

  const formatted = data.map(d => ({ label: d.date.slice(5), apple: d.apple, whoop: d.whoop }));

  return (
    <div className="space-y-2">
      <div className="flex items-baseline justify-between">
        <Eyebrow>Resting HR · Apple vs WHOOP · 90d</Eyebrow>
        <div className="flex items-center gap-3 text-[10px]">
          <span className="flex items-center gap-1"><span className="inline-block w-3 h-0.5" style={{ background: "var(--chart-line)" }} /> Apple</span>
          <span className="flex items-center gap-1"><span className="inline-block w-3 h-0.5 border-t border-dashed" style={{ borderColor: "var(--chart-line-2)" }} /> WHOOP</span>
        </div>
      </div>
      {isLoading ? (
        <div className="h-[100px] shc-skeleton rounded" />
      ) : (
        <>
          <ResponsiveContainer width="100%" height={100}>
            <ComposedChart data={formatted} margin={{ top: 4, right: 0, left: -20, bottom: 0 }}>
              <XAxis dataKey="label" tick={{ fontSize: 9.5, fill: "var(--text-faint)" }} tickLine={false} axisLine={false} interval={Math.floor(formatted.length / 6) || 1} />
              <YAxis tick={{ fontSize: 9.5, fill: "var(--text-faint)" }} tickLine={false} axisLine={false} domain={["auto", "auto"]} />
              <Tooltip contentStyle={{ background: "var(--card-hover)", border: "1px solid var(--hairline-strong)", borderRadius: 8, fontSize: 11 }} cursor={{ stroke: "var(--hairline-strong)" }} />
              <Line dataKey="apple" stroke="var(--chart-line)" strokeWidth={1.5} dot={false} isAnimationActive={false} connectNulls />
              <Line dataKey="whoop" stroke="var(--chart-line-2)" strokeWidth={1.5} strokeDasharray="4 3" dot={false} isAnimationActive={false} connectNulls />
            </ComposedChart>
          </ResponsiveContainer>
          <p className="text-[10px] text-[var(--text-faint)]">
            Note: propranolol (β-blocker) artificially suppresses RHR — absolute values less meaningful than within-source trends.
          </p>
        </>
      )}
    </div>
  );
}

// ── Export ────────────────────────────────────────────────────────────────────

export function BodyPane() {
  return (
    <div className="space-y-8">
      <WeightTrend />
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
        <VO2MaxPanel />
        <StepsPanel />
      </div>
      <RHRPanel />
    </div>
  );
}
