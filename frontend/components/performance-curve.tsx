"use client";

import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import {
  Bar,
  BarChart,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "@/lib/api";
import { Eyebrow } from "@/components/ui/metric";

// ──────────────────────────────────────────────────────────────────────────

function tsbLabel(tsb: number): { label: string; color: string } {
  if (tsb > 15) return { label: "Peak Ready", color: "var(--positive)" };
  if (tsb > 5) return { label: "Optimal", color: "var(--positive)" };
  if (tsb > -10) return { label: "Managed Fatigue", color: "var(--neutral)" };
  if (tsb > -25) return { label: "Accumulating", color: "var(--warn)" };
  return { label: "Overreach Risk", color: "var(--negative)" };
}

function PMCTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: { dataKey: string; value: number | null }[];
  label?: string;
}) {
  if (!active || !payload?.length) return null;
  const get = (k: string) => payload.find((p) => p.dataKey === k)?.value ?? null;
  const ctl = get("ctl");
  const atl = get("atl");
  const load = get("load");
  return (
    <div
      style={{
        background: "var(--card-hover)",
        border: "1px solid var(--hairline-strong)",
        borderRadius: 8,
        padding: "8px 12px",
        fontSize: 11,
        lineHeight: 1.7,
        minWidth: 148,
      }}
    >
      <div
        style={{
          color: "var(--text-muted)",
          marginBottom: 4,
          fontSize: 10.5,
          letterSpacing: "0.04em",
        }}
      >
        {label}
      </div>
      {ctl != null && (
        <div style={{ color: "oklch(0.65 0.18 240)" }}>
          CTL&nbsp;&nbsp;<span style={{ float: "right" }}>{ctl.toFixed(1)}</span>
        </div>
      )}
      {atl != null && (
        <div style={{ color: "oklch(0.72 0.18 55)" }}>
          ATL&nbsp;&nbsp;<span style={{ float: "right" }}>{atl.toFixed(1)}</span>
        </div>
      )}
      {load != null && (
        <div style={{ color: "var(--text-dim)" }}>
          Load&nbsp;&nbsp;<span style={{ float: "right" }}>{load.toFixed(1)}</span>
        </div>
      )}
    </div>
  );
}

function TSBTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: { dataKey: string; value: number | null }[];
  label?: string;
}) {
  if (!active || !payload?.length) return null;
  const tsb = payload.find((p) => p.dataKey === "tsb")?.value ?? null;
  if (tsb == null) return null;
  const { label: tsbL, color } = tsbLabel(tsb);
  return (
    <div
      style={{
        background: "var(--card-hover)",
        border: "1px solid var(--hairline-strong)",
        borderRadius: 8,
        padding: "8px 12px",
        fontSize: 11,
        minWidth: 140,
      }}
    >
      <div style={{ color: "var(--text-muted)", fontSize: 10.5, marginBottom: 3 }}>{label}</div>
      <div style={{ color }}>
        TSB {tsb >= 0 ? "+" : ""}
        {tsb.toFixed(1)}&nbsp;&nbsp;<span style={{ fontSize: 10, opacity: 0.8 }}>{tsbL}</span>
      </div>
    </div>
  );
}

export function PerformanceCurvePane() {
  const curve = useQuery({
    queryKey: ["load-curve-90"],
    queryFn: () => api.loadCurve(90),
    refetchInterval: 10 * 60_000,
  });
  const state = useQuery({
    queryKey: ["daily-state"],
    queryFn: api.dailyState,
    refetchInterval: 5 * 60_000,
  });

  const { ctlSeries, tsbSeries, tickInterval } = useMemo(() => {
    const pts = curve.data?.points ?? [];
    const mapped = pts.map((p) => ({
      date: p.date.slice(5),
      load: p.load != null ? +p.load.toFixed(1) : null,
      ctl: p.ctl != null ? +p.ctl.toFixed(1) : null,
      atl: p.atl != null ? +p.atl.toFixed(1) : null,
      tsb: p.tsb != null ? +p.tsb.toFixed(1) : null,
    }));
    return {
      ctlSeries: mapped,
      tsbSeries: mapped,
      tickInterval: Math.floor(mapped.length / 6) || 1,
    };
  }, [curve.data]);

  const today = curve.data?.today;
  const gates = state.data?.gates;
  const tsb = today?.tsb ?? null;
  const tsbStatus = tsb != null ? tsbLabel(tsb) : null;

  if (curve.isLoading) {
    return (
      <div className="space-y-4">
        <div className="shc-skeleton h-[160px] rounded-lg" />
        <div className="shc-skeleton h-[80px] rounded-lg" />
      </div>
    );
  }

  if (!curve.data || ctlSeries.length === 0) {
    return (
      <div className="text-[12px] text-[var(--text-dim)] py-8 text-center">
        No training load data — sync Hevy or WHOOP to populate.
      </div>
    );
  }

  const lastDate = ctlSeries[ctlSeries.length - 1]?.date;

  return (
    <div className="space-y-6">
      <p className="shc-helptext">
        <span className="text-[var(--text-muted)]">How to read this. </span>
        CTL (fitness) builds over 42 days; ATL (fatigue) spikes and clears in 7. TSB = CTL − ATL:
        positive means you are fresh and below your fitness peak; deeply negative means accumulated
        fatigue is outpacing recovery. Sweet spot for performance: TSB +5 to +20.
      </p>

      {/* CTL + ATL line chart */}
      <div>
        <div className="flex items-baseline justify-between mb-2">
          <Eyebrow>CTL · ATL · 90d</Eyebrow>
          {today && (
            <div className="flex items-center gap-3 text-[10.5px] tabular-nums text-[var(--text-dim)]">
              <span>
                <span style={{ color: "oklch(0.65 0.18 240)" }}>CTL </span>
                {today.ctl?.toFixed(1) ?? "—"}
              </span>
              <span>
                <span style={{ color: "oklch(0.72 0.18 55)" }}>ATL </span>
                {today.atl?.toFixed(1) ?? "—"}
              </span>
              <span className="text-[var(--text-faint)]">τ {curve.data.tau.ctl_days}d / {curve.data.tau.atl_days}d</span>
            </div>
          )}
        </div>
        <div className="h-[160px]">
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={ctlSeries} margin={{ top: 4, right: 8, left: -22, bottom: 0 }} syncId="pmc">
              <Line
                dataKey="ctl"
                stroke="oklch(0.65 0.18 240)"
                strokeWidth={1.8}
                dot={false}
                isAnimationActive={false}
                activeDot={{ r: 3 }}
              />
              <Line
                dataKey="atl"
                stroke="oklch(0.72 0.18 55)"
                strokeWidth={1.5}
                strokeDasharray="5 2"
                dot={false}
                isAnimationActive={false}
                activeDot={{ r: 3 }}
              />
              {lastDate && (
                <ReferenceLine
                  x={lastDate}
                  stroke="var(--accent)"
                  strokeWidth={1.2}
                  strokeDasharray="2 2"
                />
              )}
              <XAxis
                dataKey="date"
                tick={{ fontSize: 9.5, fill: "var(--text-faint)" }}
                axisLine={false}
                tickLine={false}
                interval={tickInterval}
              />
              <YAxis
                tick={{ fontSize: 9.5, fill: "var(--text-faint)" }}
                axisLine={false}
                tickLine={false}
                width={30}
              />
              <Tooltip content={<PMCTooltip />} cursor={{ stroke: "var(--hairline-strong)", strokeWidth: 1 }} />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
        <div className="flex items-center gap-4 mt-1.5 text-[10px] text-[var(--text-faint)]">
          <span className="flex items-center gap-1">
            <span className="inline-block w-4 border-b-[1.8px]" style={{ borderColor: "oklch(0.65 0.18 240)" }} />
            CTL fitness
          </span>
          <span className="flex items-center gap-1">
            <span className="inline-block w-4 border-b border-dashed" style={{ borderColor: "oklch(0.72 0.18 55)" }} />
            ATL fatigue
          </span>
        </div>
      </div>

      {/* TSB bar chart */}
      <div>
        <div className="flex items-baseline justify-between mb-2">
          <Eyebrow>Form (TSB = CTL − ATL)</Eyebrow>
          {tsbStatus && tsb != null && (
            <span
              className="text-[10.5px] px-2 py-0.5 rounded-full tabular-nums"
              style={{
                color: tsbStatus.color,
                border: `1px solid ${tsbStatus.color}`,
                background: `${tsbStatus.color.replace(")", " / 0.1)").replace("var(", "color-mix(in oklch, ")}`,
              }}
            >
              {tsb >= 0 ? "+" : ""}{tsb.toFixed(1)} · {tsbStatus.label}
            </span>
          )}
        </div>
        <div className="h-[80px]">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={tsbSeries} margin={{ top: 4, right: 8, left: -22, bottom: 0 }} syncId="pmc">
              <Bar
                dataKey="tsb"
                isAnimationActive={false}
                shape={(props: {
                  x?: number;
                  y?: number;
                  width?: number;
                  height?: number;
                  value?: number;
                }) => {
                  const { x = 0, y = 0, width = 0, height = 0, value = 0 } = props;
                  const fill =
                    value >= 15
                      ? "oklch(0.65 0.2 145 / 0.85)"
                      : value >= 0
                      ? "oklch(0.58 0.16 145 / 0.6)"
                      : value >= -25
                      ? "oklch(0.65 0.18 55 / 0.65)"
                      : "oklch(0.55 0.22 25 / 0.8)";
                  return <rect x={x} y={y} width={Math.max(1, width)} height={height} fill={fill} />;
                }}
              />
              <ReferenceLine y={0} stroke="var(--hairline-strong)" strokeWidth={1} />
              <ReferenceLine y={15} stroke="oklch(0.55 0.16 145 / 0.4)" strokeDasharray="3 3" />
              <ReferenceLine y={-25} stroke="oklch(0.55 0.22 25 / 0.4)" strokeDasharray="3 3" />
              {lastDate && (
                <ReferenceLine
                  x={lastDate}
                  stroke="var(--accent)"
                  strokeWidth={1.2}
                  strokeDasharray="2 2"
                />
              )}
              <XAxis
                dataKey="date"
                tick={{ fontSize: 9.5, fill: "var(--text-faint)" }}
                axisLine={false}
                tickLine={false}
                interval={tickInterval}
              />
              <YAxis
                tick={{ fontSize: 9.5, fill: "var(--text-faint)" }}
                axisLine={false}
                tickLine={false}
                width={30}
              />
              <Tooltip content={<TSBTooltip />} cursor={{ stroke: "var(--hairline-strong)", strokeWidth: 1 }} />
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div className="flex justify-between text-[8.5px] text-[var(--text-faint)] mt-1 px-[30px]">
          <span>−25 overreach</span>
          <span>0</span>
          <span>+15 peak</span>
        </div>
      </div>

      {/* Today's stat grid */}
      {today && (
        <div className="grid grid-cols-4 gap-2">
          {[
            { label: "Fitness", value: today.ctl?.toFixed(1), sub: "CTL 42d" },
            { label: "Fatigue", value: today.atl?.toFixed(1), sub: "ATL 7d" },
            { label: "Form", value: today.tsb != null ? `${today.tsb >= 0 ? "+" : ""}${today.tsb.toFixed(1)}` : "—", sub: "TSB" },
            { label: "Load", value: today.load?.toFixed(1), sub: "today" },
          ].map((s) => (
            <div
              key={s.label}
              className="rounded-lg border border-[var(--hairline)] p-3 text-center"
            >
              <Eyebrow>{s.label}</Eyebrow>
              <div className="mt-1 text-[18px] font-medium tabular-nums text-[var(--text-primary)]">
                {s.value ?? "—"}
              </div>
              <div className="text-[9.5px] text-[var(--text-faint)] mt-0.5">{s.sub}</div>
            </div>
          ))}
        </div>
      )}

      {/* Gate integration */}
      {gates && (
        <div className="space-y-2">
          {gates.deload_required && (
            <div
              className="rounded-lg border p-3 text-[11.5px]"
              style={{
                borderColor: "var(--warn)",
                background: "oklch(0.65 0.16 80 / 0.07)",
              }}
            >
              <span className="font-semibold" style={{ color: "var(--warn)" }}>Deload recommended</span>
              {gates.reasons.length > 0 && (
                <span className="text-[var(--text-muted)] ml-2">{gates.reasons[0]}</span>
              )}
            </div>
          )}
          {gates.e1rm_regression_4wk_pct != null && gates.e1rm_regression_4wk_pct < -2 && (
            <div
              className="rounded-lg border p-3 text-[11.5px]"
              style={{
                borderColor: "var(--hairline-strong)",
                background: "var(--surface-1)",
              }}
            >
              <span className="text-[var(--text-muted)]">e1RM 4wk </span>
              <span className="tabular-nums" style={{ color: "var(--negative)" }}>
                {gates.e1rm_regression_4wk_pct.toFixed(1)}%
              </span>
              <span className="text-[var(--text-faint)] ml-2">strength regression detected</span>
            </div>
          )}
        </div>
      )}

      <p className="text-[10px] text-[var(--text-faint)] leading-relaxed pt-2 border-t border-[var(--hairline)]">
        Banister fitness-fatigue model. Load = WHOOP strain + scaled Hevy volume. CTL (42d EWMA) rises
        with consistent training; ATL (7d EWMA) spikes with hard sessions. TSB = CTL − ATL — deeply
        negative means digging a hole; +5 to +25 is the "race-ready" window.
      </p>
    </div>
  );
}
