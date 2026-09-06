"use client";

import { useQuery } from "@tanstack/react-query";
import {
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { api, type AirwayTrend } from "@/lib/api";
import { CHART, withAlpha } from "@/lib/palette";
import { Eyebrow } from "@/components/ui/metric";

/**
 * Overnight oxygen saturation and respiratory rate, against their thresholds.
 *
 * Both numbers were already recorded every night and neither was trended. The
 * vault is direct about why that matters here:
 *
 *   "WHOOP SpO2 floor is the primary OSA screening signal in SHC. A
 *    consistently low floor (< 94%) displayed in the sleep panel warrants
 *    clinical discussion."  — [[obstructive-sleep-apnea]]
 *
 *   "Build a 'nocturnal RR' panel showing 28d baseline, current 7d mean, and
 *    any sustained excursion > +1 bpm with a colour-coded gate state."
 *    — [[nicolo-2020-respiratory-rate-monitoring]]
 *
 * The two belong on one card because they answer one question between them —
 * how the airway is behaving overnight — and because respiratory rate is what
 * separates an infection from an airway night when saturation dips.
 */

const AXIS = { fontSize: 9.5, fill: CHART.axis } as const;

function tick(v: number, unit: string) {
  return `${v}${unit}`;
}

function Stat({
  label,
  value,
  unit,
  tone,
  note,
}: {
  label: string;
  value: string;
  unit?: string;
  tone?: string;
  note?: string;
}) {
  return (
    <div className="min-w-0">
      <p className="text-[9.5px] uppercase tracking-[0.14em] text-[var(--text-dim)]">{label}</p>
      <p className="text-[17px] font-medium tabular-nums" style={{ color: tone ?? "var(--text-primary)" }}>
        {value}
        {unit && <span className="text-[10px] text-[var(--text-faint)] ml-0.5">{unit}</span>}
      </p>
      {note && <p className="text-[9.5px] text-[var(--text-faint)] mt-0.5">{note}</p>}
    </div>
  );
}

function Key({ items }: { items: { color: string; text: string }[] }) {
  return (
    <div className="flex flex-wrap gap-x-3 gap-y-1 mt-1 text-[9.5px] text-[var(--text-faint)]">
      {items.map((i) => (
        <span key={i.text} className="inline-flex items-center gap-1">
          <span
            className="inline-block rounded-full"
            style={{ width: 6, height: 6, background: i.color }}
          />
          {i.text}
        </span>
      ))}
    </div>
  );
}

function Spo2Chart({ d }: { d: AirwayTrend }) {
  const { spo2, nights } = d;
  const pts = nights.filter((n) => n.spo2 != null || n.spo2_7d != null);
  if (!pts.length) return null;
  // Tight to the data. A domain padded down to 88% turned the sub-94 region
  // into half the plot area, which read as "most nights are bad" when most
  // nights are 94-96. The band a night falls in is carried by its colour now,
  // so the axis only has to hold the data.
  const lo = Math.floor((spo2.min ?? 92) - 0.5);
  const hi = Math.min(100, Math.ceil(Math.max(...pts.map((n) => n.spo2 ?? 0)) + 0.5));
  const dotFill = (v: number) =>
    v < spo2.screen_pct ? CHART.bad : v < spo2.normal_pct ? CHART.warn : CHART.ok;
  return (
    <div>
      <div className="flex items-baseline justify-between gap-3 mb-1">
        <Eyebrow>Overnight SpO₂ · {d.window_days}d</Eyebrow>
        <span className="text-[10px] text-[var(--text-faint)]">
          {spo2.below_94} of {spo2.n} nights under {spo2.screen_pct}%
        </span>
      </div>
      <div className="h-[150px]">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={pts} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
            <XAxis
              dataKey="date"
              tick={AXIS}
              tickLine={false}
              axisLine={false}
              minTickGap={48}
              tickFormatter={(v: string) => v.slice(5)}
            />
            <YAxis
              domain={[lo, hi]}
              tick={AXIS}
              tickLine={false}
              axisLine={false}
              width={34}
              tickFormatter={(v: number) => tick(v, "%")}
            />
            <ReferenceLine y={spo2.normal_pct} stroke={CHART.ok} strokeOpacity={0.35} strokeDasharray="3 3" />
            <ReferenceLine
              y={spo2.screen_pct}
              stroke={CHART.bad}
              strokeOpacity={0.5}
              strokeDasharray="4 3"
            />
            <Tooltip
              cursor={{ stroke: CHART.hairlineStrong }}
              contentStyle={{
                background: CHART.tooltip,
                border: `1px solid ${CHART.hairlineStrong}`,
                borderRadius: 8,
                fontSize: 11,
                color: CHART.text,
              }}
              labelStyle={{ color: CHART.textMuted, fontSize: 10 }}
              formatter={(v: number, name: string) => [
                `${v.toFixed(1)}%`,
                name === "spo2" ? "that night" : "7-night mean",
              ]}
            />
            <Line
              dataKey="spo2"
              stroke="none"
              isAnimationActive={false}
              dot={(d: { cx?: number; cy?: number; payload?: { spo2: number | null } }) => {
                const v = d.payload?.spo2;
                if (v == null || d.cx == null || d.cy == null) return <g key={`${d.cx}-${d.cy}`} />;
                return (
                  <circle
                    key={`${d.cx}-${d.cy}`}
                    cx={d.cx}
                    cy={d.cy}
                    r={2}
                    fill={dotFill(v)}
                    fillOpacity={0.75}
                  />
                );
              }}
            />
            <Line
              dataKey="spo2_7d"
              stroke={CHART.line}
              strokeWidth={1.8}
              dot={false}
              connectNulls
              isAnimationActive={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <Key
        items={[
          { color: CHART.ok, text: `≥ ${spo2.normal_pct}%` },
          { color: CHART.warn, text: `${spo2.screen_pct}–${spo2.normal_pct}%` },
          { color: CHART.bad, text: `under ${spo2.screen_pct}% — screening floor` },
          { color: CHART.line, text: "7-night mean" },
        ]}
      />
    </div>
  );
}

function RespChart({ d }: { d: AirwayTrend }) {
  const { resp, nights } = d;
  const pts = nights.filter((n) => n.resp != null || n.resp_7d != null);
  const base = resp.baseline_28d;
  if (!pts.length || base == null) return null;
  const vals = pts.map((n) => n.resp).filter((v): v is number => v != null);
  const lo = Math.floor(Math.min(base - 1, ...vals) - 0.5);
  const hi = Math.ceil(Math.max(base + resp.gate_delta + 0.5, ...vals) + 0.5);
  const dotFill = (v: number) => {
    const d = v - base;
    return d >= resp.gate_delta ? CHART.bad : d >= resp.watch_delta ? CHART.warn : CHART.ok;
  };
  return (
    <div>
      <div className="flex items-baseline justify-between gap-3 mb-1">
        <Eyebrow>Nocturnal respiratory rate · {d.window_days}d</Eyebrow>
        <span className="text-[10px] text-[var(--text-faint)]">
          current 28-night baseline {base.toFixed(1)} bpm
        </span>
      </div>
      <div className="h-[150px]">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={pts} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
            <XAxis
              dataKey="date"
              tick={AXIS}
              tickLine={false}
              axisLine={false}
              minTickGap={48}
              tickFormatter={(v: string) => v.slice(5)}
            />
            <YAxis
              domain={[lo, hi]}
              tick={AXIS}
              tickLine={false}
              axisLine={false}
              width={34}
              tickFormatter={(v: number) => tick(v, "")}
            />
            {/* Thresholds sit on the baseline, not on absolute numbers — the
                signal is drift against his own norm, which is what the engine's
                illness gate reads too. */}
            <ReferenceLine y={base} stroke={CHART.baseline} strokeDasharray="4 3" />
            <ReferenceLine
              y={base + resp.watch_delta}
              stroke={CHART.warn}
              strokeOpacity={0.4}
              strokeDasharray="3 3"
            />
            <ReferenceLine
              y={base + resp.gate_delta}
              stroke={CHART.bad}
              strokeOpacity={0.45}
              strokeDasharray="4 3"
            />
            {resp.clinical_bpm <= hi && (
              <ReferenceLine
                y={resp.clinical_bpm}
                stroke={CHART.bad}
                strokeOpacity={0.55}
                strokeDasharray="2 3"
              />
            )}
            <Tooltip
              cursor={{ stroke: CHART.hairlineStrong }}
              contentStyle={{
                background: CHART.tooltip,
                border: `1px solid ${CHART.hairlineStrong}`,
                borderRadius: 8,
                fontSize: 11,
                color: CHART.text,
              }}
              labelStyle={{ color: CHART.textMuted, fontSize: 10 }}
              formatter={(v: number, name: string) => [
                `${v.toFixed(2)} bpm`,
                name === "resp" ? "that night" : "7-night mean",
              ]}
            />
            <Line
              dataKey="resp"
              stroke="none"
              isAnimationActive={false}
              dot={(d: { cx?: number; cy?: number; payload?: { resp: number | null } }) => {
                const v = d.payload?.resp;
                if (v == null || d.cx == null || d.cy == null) return <g key={`${d.cx}-${d.cy}`} />;
                return (
                  <circle
                    key={`${d.cx}-${d.cy}`}
                    cx={d.cx}
                    cy={d.cy}
                    r={2}
                    fill={dotFill(v)}
                    fillOpacity={0.75}
                  />
                );
              }}
            />
            <Line
              dataKey="resp_7d"
              stroke={withAlpha(CHART.warn, 0.9)}
              strokeWidth={1.8}
              dot={false}
              connectNulls
              isAnimationActive={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <Key
        items={[
          { color: CHART.ok, text: "at baseline" },
          { color: CHART.warn, text: `+${resp.watch_delta} watch` },
          { color: CHART.bad, text: `+${resp.gate_delta} illness gate` },
          { color: withAlpha(CHART.warn, 0.9), text: "7-night mean" },
        ]}
      />
      <p className="text-[9.5px] text-[var(--text-faint)] mt-1">
        Every night is scored against today&apos;s baseline, so an older dot is coloured by how
        it compares with where you sit now, not with where you sat that month.
      </p>
    </div>
  );
}

export function AirwayPanel() {
  const { data, isLoading } = useQuery({
    queryKey: ["sleep-airway", 180],
    queryFn: () => api.sleepAirway(180),
    staleTime: 1000 * 60 * 15,
  });

  if (isLoading || !data) {
    return (
      <div className="shc-card shc-enter p-5 space-y-4">
        {[64, 150, 150].map((h, i) => (
          <div key={i} className="shc-skeleton rounded" style={{ height: h }} />
        ))}
      </div>
    );
  }

  const { spo2, resp } = data;
  const pctBelow95 = spo2.n ? Math.round((spo2.below_95 / spo2.n) * 100) : 0;
  const spo2Tone =
    spo2.mean == null
      ? undefined
      : spo2.mean < spo2.screen_pct
        ? "var(--negative)"
        : spo2.mean < spo2.normal_pct
          ? "var(--neutral)"
          : "var(--positive)";
  const delta = resp.delta;
  const respTone =
    delta == null
      ? undefined
      : delta >= resp.gate_delta
        ? "var(--negative)"
        : delta >= resp.watch_delta
          ? "var(--neutral)"
          : "var(--positive)";

  return (
    <div className="shc-card shc-enter p-5 space-y-5">
      <div className="grid grid-cols-2 @md:grid-cols-4 gap-4">
        <Stat
          label="SpO₂ mean"
          value={spo2.mean?.toFixed(1) ?? "—"}
          unit="%"
          tone={spo2Tone}
          note={`floor ${spo2.min?.toFixed(1) ?? "—"}%`}
        />
        <Stat
          label={`Nights under ${spo2.normal_pct}%`}
          value={`${spo2.below_95}`}
          note={`${pctBelow95}% of ${spo2.n} · ${spo2.below_92} under ${spo2.gate_pct}%`}
        />
        <Stat
          label="Resp rate"
          value={resp.last_7d_mean?.toFixed(1) ?? "—"}
          unit="bpm"
          note="last 7 nights"
        />
        <Stat
          label="vs baseline"
          value={delta == null ? "—" : `${delta > 0 ? "+" : ""}${delta.toFixed(2)}`}
          unit="bpm"
          tone={respTone}
          note={
            delta == null
              ? undefined
              : delta >= resp.gate_delta
                ? "illness-gate territory"
                : delta >= resp.watch_delta
                  ? "watch"
                  : "steady"
          }
        />
      </div>

      <Spo2Chart d={data} />
      <RespChart d={data} />

      <p className="text-[10px] text-[var(--text-faint)] leading-relaxed pt-1 border-t border-[var(--hairline)]">
        Dots are coloured by band, the line is a seven-night mean. A nightly{" "}
        <strong>average</strong> saturation is not an ODI or an AHI — it cannot count events, and
        a night that dips hard for ten minutes can average the same as a flat one. The sensor
        also sits on the bicep, off-label for pulse oximetry. Treat a persistently low mean as a
        reason to raise this with a physician, not as a severity score. Respiratory rate is the
        companion: infection and airway load both push it up, so a saturation dip with a flat
        respiratory rate reads differently from one where both move together.
      </p>
    </div>
  );
}
