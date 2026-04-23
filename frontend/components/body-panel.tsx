"use client";

import { useQuery } from "@tanstack/react-query";
import {
  ComposedChart,
  Line,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
  Area,
} from "recharts";
import { api } from "@/lib/api";
import { Eyebrow } from "@/components/ui/metric";

// ── Weight trend ─────────────────────────────────────────────────────────────

function rollingAvg(data: { lbs: number }[], window: number) {
  return data.map((d, i) => {
    const slice = data.slice(Math.max(0, i - window + 1), i + 1);
    return slice.reduce((s, x) => s + x.lbs, 0) / slice.length;
  });
}

const WtTooltip = ({ active, payload, label }: any) => {
  if (!active || !payload?.length) return null;
  const lbs = payload.find((p: any) => p.dataKey === "lbs")?.value;
  const avg = payload.find((p: any) => p.dataKey === "avg")?.value;
  return (
    <div className="rounded-lg border px-3 py-2 text-[11px] font-mono" style={{ background: "var(--card-hover)", borderColor: "var(--hairline-strong)" }}>
      <p className="text-[var(--text-dim)] mb-1">{label}</p>
      {lbs && <p className="text-[var(--text-primary)]">{lbs} lbs</p>}
      {avg && <p className="text-[var(--text-muted)]">{avg.toFixed(1)} lbs avg</p>}
    </div>
  );
};

function WeightTrend() {
  const { data = [], isLoading } = useQuery({
    queryKey: ["body-weight"],
    queryFn: () => api.bodyTrend(),
    refetchInterval: 3_600_000,
  });

  const avgs = rollingAvg(data, 7);
  const formatted = data.map((d, i) => ({
    label: d.date.slice(5),
    lbs: d.lbs,
    avg: +avgs[i].toFixed(1),
  }));

  const latest = data[data.length - 1];
  const earliest = data[0];
  const delta = latest && earliest ? +(latest.lbs - earliest.lbs).toFixed(1) : null;
  const deltaColor = delta == null ? "var(--text-faint)" : delta <= 0 ? "var(--positive)" : "var(--negative)";

  return (
    <div className="space-y-2">
      <div className="flex items-baseline justify-between">
        <Eyebrow>Body weight · all-time (Apple Health)</Eyebrow>
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
        <p className="text-[12px] text-[var(--text-faint)] py-8 text-center">No weight data in Apple Health export</p>
      ) : (
        <ResponsiveContainer width="100%" height={140}>
          <ComposedChart data={formatted} margin={{ top: 4, right: 0, left: -20, bottom: 0 }}>
            <XAxis dataKey="label" tick={{ fontSize: 9.5, fill: "var(--text-faint)" }} tickLine={false} axisLine={false} interval={Math.floor(formatted.length / 6) || 1} />
            <YAxis tick={{ fontSize: 9.5, fill: "var(--text-faint)" }} tickLine={false} axisLine={false} domain={["auto", "auto"]} />
            <Tooltip content={<WtTooltip />} cursor={{ stroke: "var(--hairline-strong)" }} />
            <Bar dataKey="lbs" fill="oklch(1 0 0 / 0.06)" radius={[2, 2, 0, 0]} maxBarSize={6} isAnimationActive={false} />
            <Line dataKey="avg" stroke="var(--chart-line)" strokeWidth={2} dot={false} isAnimationActive={false} />
          </ComposedChart>
        </ResponsiveContainer>
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
        <Eyebrow>VO₂ max · Apple Health</Eyebrow>
        {latest && zone && (
          <span className="text-[10.5px] font-medium" style={{ color: zone.color }}>{zone.label} for age (39)</span>
        )}
      </div>
      {isLoading ? (
        <div className="h-[140px] shc-skeleton rounded" />
      ) : data.length === 0 ? (
        <p className="text-[12px] text-[var(--text-faint)] py-6 text-center">No VO₂ max data</p>
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
              ⚠ Decline is ~4× expected age-related rate. Priority: zone 2 cardio 3×/wk.
            </p>
          )}
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
  const { data = [], isLoading } = useQuery({
    queryKey: ["steps-90"],
    queryFn: () => api.bodySteps(90),
    refetchInterval: 3_600_000,
  });

  const avg = data.length ? Math.round(data.reduce((s, d) => s + d.steps, 0) / data.length) : 0;
  const formatted = data.map(d => ({ label: d.date.slice(5), steps: d.steps }));

  const StepTooltip = ({ active, payload, label }: any) => {
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
        <Eyebrow>Daily steps · 90 days</Eyebrow>
        {avg > 0 && (
          <span className="text-[10.5px] font-mono tabular-nums" style={{ color: avg >= 10000 ? "var(--positive)" : avg >= 7500 ? "var(--neutral)" : "var(--negative)" }}>
            avg {avg.toLocaleString()}/day
            {avg >= 10000 ? " · on target" : avg >= 7500 ? " · near target" : " · below 10k goal"}
          </span>
        )}
      </div>
      {isLoading ? (
        <div className="h-[100px] shc-skeleton rounded" />
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
