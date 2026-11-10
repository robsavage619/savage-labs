"use client";

import { useQuery } from "@tanstack/react-query";
import { Bar, BarChart, CartesianGrid, Cell, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "@/lib/api";
import { Eyebrow } from "@/components/ui/metric";
import { ExploreButton, type MetricKey } from "@/components/metric-explorer";

/**
 * Three figures the Week page never drew: how alike the training days are,
 * the aerobic-base dose, and why last night's sleep target moved. Each renders
 * its route's values as served.
 */

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const md = (iso: string) => `${MONTHS[Number(iso.slice(5, 7)) - 1]} ${Number(iso.slice(8, 10))}`;
const TICK = { fill: "var(--text-dim)", fontSize: 11, fontFamily: "var(--font-data)" };

function Head({ eyebrow, title, metric }: { eyebrow: string; title: string; metric?: MetricKey }) {
  return (
    <div className="ts-head">
      <div>
        <Eyebrow>{eyebrow}</Eyebrow>
        <h3 className="shc-section-title mt-1">{title}</h3>
      </div>
      {metric && <ExploreButton metric={metric} />}
    </div>
  );
}

function Frame({ children, error, height }: { children: React.ReactNode; error?: unknown; height: number }) {
  if (error) return <div className="shc-card p-6 ts-card"><p className="ts-error">Couldn&apos;t load: {String(error)}</p></div>;
  if (!children) return <div className="shc-card p-6 ts-card ts-skeleton" style={{ height }} />;
  return <div className="shc-card shc-enter p-6 ts-card">{children}</div>;
}

// ── Monotony ────────────────────────────────────────────────────────────────

export function MonotonyCard() {
  const q = useQuery({ queryKey: ["training-monotony", 12], queryFn: () => api.trainingMonotony(12), staleTime: 10 * 60 * 1000 });
  const d = q.data;
  const ref = d?.heuristic_reference ?? 2;
  return (
    <Frame error={q.error} height={300}>
      {d && (
        <>
          <Head eyebrow="Foster monotony · 12 weeks" title="Is every week the same week?" metric="load" />
          <p className="ts-lede">
            {d.weeks_above_heuristic === 0 ? `No week crossed ${ref.toFixed(1)}. Your days are ${d.verdict}.` : `${d.weeks_above_heuristic} of ${d.weeks.length} weeks crossed ${ref.toFixed(1)}.`}
          </p>
          <div style={{ height: 170 }}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={d.weeks} margin={{ top: 12, right: 8, bottom: 0, left: 0 }}>
                <CartesianGrid vertical={false} stroke="var(--chart-grid)" />
                <XAxis dataKey="week_start" tickFormatter={md} tick={TICK} tickLine={false} axisLine={{ stroke: "var(--hairline-strong)" }} minTickGap={24} />
                <YAxis width={32} domain={[0, (max: number) => Math.ceil(Math.max(ref * 1.1, max) * 2) / 2]} tickCount={6} tick={TICK} tickLine={false} axisLine={false} tickFormatter={(v: number) => v.toFixed(1)} />
                <Tooltip
                  cursor={{ fill: "oklch(1 0 0 / 0.04)" }}
                  content={({ active, payload }) => {
                    const w = active && payload?.[0]?.payload;
                    if (!w) return null;
                    return (
                      <div className="xp-tip">
                        <div className="xp-tip-date">week of {md(w.week_start)}</div>
                        <div className="xp-tip-row">monotony<b>{w.monotony?.toFixed(2) ?? "–"}</b></div>
                        <div className="xp-tip-row">training days<b>{w.training_days}</b></div>
                      </div>
                    );
                  }}
                />
                <ReferenceLine y={ref} stroke="var(--negative)" strokeDasharray="4 4" label={{ value: `${ref.toFixed(1)} warning`, position: "insideTopLeft", fill: "var(--negative)", fontSize: 11 }} />
                <Bar dataKey="monotony" radius={[4, 4, 0, 0]} maxBarSize={24} isAnimationActive={false}>
                  {d.weeks.map((w) => (
                    <Cell key={w.week_start} fill={w.above_heuristic ? "var(--negative)" : "var(--series-1)"} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
          <p className="ts-foot">Taller bars mean the days that week were more alike. The 2.0 line is a common rule of thumb, not Foster&apos;s own cut-off.</p>
        </>
      )}
    </Frame>
  );
}

// ── Aerobic base ────────────────────────────────────────────────────────────

const Z2_DOSE_MIN = 180;

export function AerobicBaseCard() {
  const q = useQuery({ queryKey: ["daily-state"], queryFn: api.dailyState, staleTime: 5 * 60 * 1000 });
  const t = q.data?.training_load;
  const base = t?.cardio_aerobic_base_min_7d ?? null;
  const zones = Object.entries(t?.cardio_zone_min_7d ?? {}).sort(([a], [b]) => a.localeCompare(b));
  const zmax = Math.max(1, ...zones.map(([, v]) => v));
  const r = 70;
  const arc = Math.PI * r;
  const pct = base == null ? 0 : Math.min(base / Z2_DOSE_MIN, 1);
  return (
    <Frame error={q.error} height={300}>
      {t && (
        <>
          <Head eyebrow="Last 7 days" title="Aerobic base" />
          <div className="ab-gauge">
            <svg width={180} height={104} viewBox="0 0 180 104" role="img" aria-label={`${base ?? 0} of ${Z2_DOSE_MIN} aerobic-base minutes`}>
              <path d="M20 94 A70 70 0 0 1 160 94" fill="none" stroke="oklch(1 0 0 / 0.07)" strokeWidth={12} strokeLinecap="round" />
              <path d="M20 94 A70 70 0 0 1 160 94" fill="none" stroke={pct >= 1 ? "var(--positive)" : "var(--neutral)"} strokeWidth={12} strokeLinecap="round" strokeDasharray={`${arc * pct} ${arc}`} className="ts-ring-fill" />
              <text x={90} y={80} textAnchor="middle" className="ab-num">{base ?? "–"}</text>
              <text x={90} y={98} textAnchor="middle" className="ab-sub">of {Z2_DOSE_MIN} min</text>
            </svg>
          </div>
          <div className="ab-zones">
            {zones.map(([k, v]) => {
              const counts = k === "z2" || k === "z3";
              return (
                <div key={k} className="ab-zone" title={`${k.toUpperCase()}: ${Math.round(v)} min${counts ? ", counts toward the base" : ""}`}>
                  <span className="ab-bar"><i style={{ height: `${(v / zmax) * 100}%`, background: counts ? "var(--series-1)" : "var(--hairline-strong)" }} /></span>
                  <small>{k.toUpperCase()}</small>
                  <b>{Math.round(v)}</b>
                </div>
              );
            })}
          </div>
          <p className="ts-foot">WHOOP zones 2 and 3 together. Zone 2 alone ({t.cardio_z2_min_7d} min) undercounts the aerobic dose.</p>
        </>
      )}
    </Frame>
  );
}

// ── Sleep need ──────────────────────────────────────────────────────────────

export function SleepNeedCard() {
  const q = useQuery({ queryKey: ["daily-state"], queryFn: api.dailyState, staleTime: 5 * 60 * 1000 });
  const s = q.data?.sleep;
  const parts: [string, number | null | undefined][] = s
    ? [
        ["Baseline need", s.sleep_need_baseline_min_last],
        ["+ sleep debt", s.sleep_need_debt_min_last],
        ["+ yesterday's strain", s.sleep_need_strain_min_last],
        ["+ naps (credit)", s.sleep_need_nap_min_last ? -s.sleep_need_nap_min_last : 0],
      ]
    : [];
  const need = s?.sleep_needed_min_last ?? null;
  const got = s?.last_hours != null ? s.last_hours * 60 : null;
  const scale = Math.max(need ?? 0, got ?? 0, 1) * 1.05;
  let run = 0;
  return (
    <Frame error={q.error} height={260}>
      {s && (
        <>
          <Head eyebrow="Last night" title={need ? `Why you needed ${(need / 60).toFixed(1)} h` : "Sleep need"} metric="sleep" />
          <div className="sn-rows">
            {parts.filter(([, v]) => v).map(([label, v]) => {
              const left = run;
              run += v ?? 0;
              const neg = (v ?? 0) < 0;
              return (
                <div key={label} className="sn-row">
                  <span>{label}</span>
                  <span className="sn-track">
                    <i style={{ left: `${((neg ? run : left) / scale) * 100}%`, width: `${(Math.abs(v ?? 0) / scale) * 100}%`, background: neg ? "var(--positive)" : "var(--series-2)" }} />
                  </span>
                  <b>{Math.round(v ?? 0)} min</b>
                </div>
              );
            })}
            <div className="sn-row sn-total">
              <span>You slept</span>
              <span className="sn-track">{got != null && <i style={{ left: 0, width: `${(got / scale) * 100}%`, background: "var(--series-1)" }} />}</span>
              <b>{got == null ? "–" : `${Math.round(got)} min`}</b>
            </div>
          </div>
          <p className="ts-foot">
            {need != null && got != null ? (got >= need ? `${Math.round(got - need)} min over what you needed.` : `${Math.round(need - got)} min short of what you needed.`) : "WHOOP hasn't served a need breakdown for last night."}
          </p>
        </>
      )}
    </Frame>
  );
}
