"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Area,
  Bar,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "@/lib/api";

/**
 * One drawer behind every number: its history, its normal band, a range
 * control, and a related metric to read underneath it.
 *
 * The drawer unmounts on close instead of animating out: framer-motion's
 * AnimatePresence never finishes an exit under React 19 StrictMode, which
 * leaves the old drawer mounted. Entry is a CSS animation.
 */

export type MetricKey = "hrv" | "rhr" | "recovery" | "sleep" | "load" | "form" | "sets";

type Row = { date: string } & Record<string, number | null | string>;

interface MetricDef {
  title: string;
  unit: string;
  source: string;
  about: string;
  digits: number;
  fetch: (days: number) => Promise<Row[]>;
  lines: { key: string; name: string; color: string }[];
  bars?: boolean;
  band?: [string, string];
  refs?: { y: number; label: string }[];
  related: MetricKey[];
}

const S1 = "var(--series-1)";
const S2 = "var(--series-2)";

const DEFS: Record<MetricKey, MetricDef> = {
  hrv: {
    title: "HRV",
    unit: "ms",
    source: "/api/hrv/trend",
    about: "Nightly heart rate variability. The shaded band is your 28-day average plus or minus one standard deviation: your normal range. Several nights below it in a row matter; one does not.",
    digits: 0,
    fetch: async (d) =>
      (await api.hrvTrend(d)).map((p) => ({ date: p.date, hrv: p.hrv, avg: p.avg, lo: p.avg - p.sd, hi: p.avg + p.sd })),
    lines: [
      { key: "hrv", name: "HRV", color: S1 },
      { key: "avg", name: "28-day average", color: S2 },
    ],
    band: ["lo", "hi"],
    related: ["rhr", "recovery", "sleep", "load"],
  },
  rhr: {
    title: "Resting heart rate",
    unit: "bpm",
    source: "/api/recovery/trend",
    about: "Resting heart rate each morning. Lower than your normal usually means well recovered; a run of higher mornings often comes before illness or after hard weeks.",
    digits: 0,
    fetch: async (d) => (await api.recoveryTrend(d)).map((p) => ({ date: p.date, rhr: p.rhr })),
    lines: [{ key: "rhr", name: "Resting HR", color: S1 }],
    related: ["hrv", "recovery", "sleep"],
  },
  recovery: {
    title: "Recovery score",
    unit: "%",
    source: "/api/recovery/trend",
    about: "WHOOP's 0–100 recovery score. 67 and up is green, under 34 is red.",
    digits: 0,
    fetch: async (d) => (await api.recoveryTrend(d)).map((p) => ({ date: p.date, score: p.score })),
    lines: [{ key: "score", name: "Recovery", color: S1 }],
    refs: [
      { y: 67, label: "green 67" },
      { y: 34, label: "red 34" },
    ],
    related: ["hrv", "rhr", "sleep"],
  },
  sleep: {
    title: "Sleep",
    unit: "h",
    source: "/api/sleep/trend",
    about: "Hours asleep each night. Where WHOOP recorded two main sleeps on one night, the longer one is shown.",
    digits: 1,
    fetch: async (d) => {
      const best = new Map<string, number>();
      for (const p of await api.sleepTrend(d)) {
        if (p.hours == null) continue;
        best.set(p.date, Math.max(best.get(p.date) ?? 0, p.hours));
      }
      return [...best].map(([date, hours]) => ({ date, hours }));
    },
    lines: [{ key: "hours", name: "Sleep", color: S1 }],
    refs: [{ y: 7, label: "7 h" }],
    related: ["hrv", "recovery", "rhr"],
  },
  load: {
    title: "Fitness vs fatigue",
    unit: "",
    source: "/api/training/load-curve",
    about: "Two rolling averages of daily training load: fitness (slow, about 6 weeks) and fatigue (fast, about 1 week). Fatigue above fitness means you've been training harder than you're used to.",
    digits: 1,
    fetch: async (d) => (await api.loadCurve(d)).points.map((p) => ({ date: p.date, ctl: p.ctl, atl: p.atl })),
    lines: [
      { key: "ctl", name: "Fitness", color: S1 },
      { key: "atl", name: "Fatigue", color: S2 },
    ],
    related: ["form", "sets", "hrv"],
  },
  form: {
    title: "Form",
    unit: "",
    source: "/api/training/load-curve",
    about: "Fitness minus fatigue. Above zero is fresh, below zero is carrying fatigue. Weeks well below zero mean you're digging a hole.",
    digits: 1,
    fetch: async (d) => (await api.loadCurve(d)).points.map((p) => ({ date: p.date, tsb: p.tsb })),
    lines: [{ key: "tsb", name: "Form", color: S1 }],
    refs: [{ y: 0, label: "0" }],
    related: ["load", "sets", "recovery"],
  },
  sets: {
    title: "Working sets per week",
    unit: "sets",
    source: "/api/training/weekly",
    about: "Total working sets logged each week, all muscles together.",
    digits: 0,
    fetch: async (d) => (await api.trainingWeekly(Math.max(2, Math.ceil(d / 7)))).map((w) => ({ date: w.week, sets: w.sets })),
    lines: [{ key: "sets", name: "Sets", color: S1 }],
    bars: true,
    related: ["load", "form", "recovery"],
  },
};

const RANGES = [30, 90, 180, 365] as const;

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
function fmtDate(iso: string, withYear = false) {
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return withYear ? `${MONTHS[m - 1]} ${d}, ${y}` : `${MONTHS[m - 1]} ${d}`;
}

function fmt(v: unknown, digits: number) {
  return typeof v === "number" ? v.toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: digits }) : "–";
}

function ExplorerTooltip({ active, payload, label, def }: { active?: boolean; payload?: { dataKey: string; value: number; color: string; name: string }[]; label?: string; def: MetricDef }) {
  if (!active || !payload?.length || !label) return null;
  const row = payload[0] as unknown as { payload: Row };
  return (
    <div className="xp-tip">
      <div className="xp-tip-date">{fmtDate(label, true)}</div>
      {def.lines.map((l) => (
        <div key={l.key} className="xp-tip-row">
          <i style={{ background: l.color }} />
          {l.name}
          <b>
            {fmt(row.payload[l.key], def.digits)} {def.unit}
          </b>
        </div>
      ))}
      {def.band && (
        <div className="xp-tip-band">
          normal range {fmt(row.payload[def.band[0]], def.digits)}–{fmt(row.payload[def.band[1]], def.digits)}
        </div>
      )}
    </div>
  );
}

function MetricChart({ k, days, height }: { k: MetricKey; days: number; height: number }) {
  const def = DEFS[k];
  const q = useQuery({ queryKey: ["explorer", k, days], queryFn: () => def.fetch(days), staleTime: 5 * 60 * 1000 });
  if (q.isError) return <p className="xp-empty">Couldn&apos;t load {def.source} ({String(q.error)}).</p>;
  if (!q.data) return <div className="xp-skeleton" style={{ height }} />;
  if (!q.data.length) return <p className="xp-empty">No data in this range.</p>;
  const data = def.band ? q.data.map((r) => ({ ...r, band: [r[def.band![0]], r[def.band![1]]] })) : q.data;
  const last = q.data[q.data.length - 1];
  return (
    <>
      <div className="xp-now">
        {def.lines.map((l) => (
          <span key={l.key}>
            <i style={{ background: l.color }} />
            {l.name} <b>{fmt(last[l.key], def.digits)}</b> {def.unit}
          </span>
        ))}
        <span className="xp-now-date">latest {fmtDate(last.date)}</span>
      </div>
      <div style={{ height }}>
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={data} margin={{ top: 8, right: 24, bottom: 0, left: 0 }}>
            <CartesianGrid vertical={false} stroke="var(--chart-grid)" />
            <XAxis
              dataKey="date"
              tickFormatter={(d: string) => fmtDate(d)}
              tick={{ fill: "var(--text-dim)", fontSize: 11, fontFamily: "var(--font-data)" }}
              tickLine={false}
              axisLine={{ stroke: "var(--hairline-strong)" }}
              minTickGap={36}
            />
            <YAxis
              width={40}
              domain={["auto", "auto"]}
              tick={{ fill: "var(--text-dim)", fontSize: 11, fontFamily: "var(--font-data)" }}
              tickLine={false}
              axisLine={false}
              tickFormatter={(v: number) => fmt(v, def.digits > 0 && Math.abs(v) < 10 ? 1 : 0)}
            />
            <Tooltip content={<ExplorerTooltip def={def} />} cursor={{ stroke: "var(--text-dim)", strokeWidth: 1 }} />
            {def.band && <Area dataKey="band" stroke="none" fill="var(--series-1)" fillOpacity={0.12} isAnimationActive={false} />}
            {def.refs?.map((r) => (
              <ReferenceLine key={r.label} y={r.y} stroke="var(--text-dim)" strokeDasharray="4 4" label={{ value: r.label, position: "insideTopLeft", fill: "var(--text-dim)", fontSize: 11 }} />
            ))}
            {def.lines.map((l, i) =>
              def.bars ? (
                <Bar key={l.key} dataKey={l.key} name={l.name} fill={l.color} radius={[4, 4, 0, 0]} maxBarSize={24} isAnimationActive={false} />
              ) : (
                <Line
                  key={l.key}
                  dataKey={l.key}
                  name={l.name}
                  stroke={l.color}
                  strokeWidth={2}
                  dot={false}
                  activeDot={{ r: 4.5, stroke: "var(--card)", strokeWidth: 2 }}
                  connectNulls
                  animationDuration={700 + i * 150}
                />
              ),
            )}
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </>
  );
}

function Drawer({ k, close, open }: { k: MetricKey; close: () => void; open: (k: MetricKey) => void }) {
  const def = DEFS[k];
  const [days, setDays] = useState<number>(90);
  const [compare, setCompare] = useState<MetricKey | null>(null);
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && close();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [close]);

  return (
    <>
      <div className="xp-scrim" onClick={close} />
      <aside className="xp-drawer" role="dialog" aria-modal="true" aria-label={`${def.title} history`}>
        <header className="xp-head">
          <div>
            <p className="eyebrow">Metric explorer</p>
            <h2 className="xp-title">{def.title}</h2>
          </div>
          <button ref={closeRef} className="xp-close" onClick={close} aria-label="Close explorer">
            ×
          </button>
        </header>
        <p className="xp-about">{def.about}</p>
        <div className="xp-ranges" role="group" aria-label="Time range">
          {RANGES.map((r) => (
            <button key={r} className={r === days ? "on" : ""} aria-pressed={r === days} onClick={() => setDays(r)}>
              {r === 365 ? "1 yr" : `${r} d`}
            </button>
          ))}
        </div>
        <MetricChart k={k} days={days} height={240} />
        <div className="xp-compare">
          <p className="eyebrow">Read it against</p>
          <div className="xp-pills">
            {def.related.map((r) => (
              <button key={r} className={r === compare ? "on" : ""} aria-pressed={r === compare} onClick={() => setCompare(r === compare ? null : r)}>
                {DEFS[r].title}
              </button>
            ))}
          </div>
          {compare && (
            <div className="xp-second">
              <div className="xp-second-head">
                <span>{DEFS[compare].title}</span>
                <button onClick={() => open(compare)}>Open ↗</button>
              </div>
              <MetricChart k={compare} days={days} height={150} />
            </div>
          )}
        </div>
        <p className="xp-source">
          Source <code>{def.source}</code>
        </p>
      </aside>
    </>
  );
}

const ExplorerCtx = createContext<(k: MetricKey) => void>(() => {});

export function ExplorerProvider({ children }: { children: ReactNode }) {
  const [k, setK] = useState<MetricKey | null>(null);
  const close = useCallback(() => setK(null), []);
  return (
    <ExplorerCtx.Provider value={setK}>
      {children}
      {k && <Drawer key={k} k={k} close={close} open={setK} />}
    </ExplorerCtx.Provider>
  );
}

export const useExplorer = () => useContext(ExplorerCtx);

export function ExploreButton({ metric, label = "History" }: { metric: MetricKey; label?: string }) {
  const open = useExplorer();
  return (
    <button className="xp-open" onClick={() => open(metric)}>
      {label} ↗
    </button>
  );
}
