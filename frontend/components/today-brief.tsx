"use client";

import { useState, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { api, type DailyState, type NoiseFloorSignal, type WorkoutExercise, type WorkoutPlan } from "@/lib/api";
import { readinessCommand } from "@/components/athlete-os-panel";
import { ease, FillLines, useWidth } from "@/components/kit";
import { useExplorer, type MetricKey } from "@/components/metric-explorer";
import { ProgressionDrawer } from "@/components/progression-drawer";
import { Markdown } from "@/components/ui/markdown";
import { ObsidianSourceTag } from "@/components/obsidian-badge";

/**
 * Today as a morning brief: the call and why, the overnight evidence against
 * your own normal, four weeks of mornings on one tape, the session as a
 * working sheet, and whether the body can take it. Every DailyState value is
 * rendered as served; the only arithmetic here is unit conversion (°C → °F)
 * and chart scaling.
 */

const STALE = 5 * 60 * 1000;
const TONE = { positive: "var(--positive)", neutral: "var(--neutral)", negative: "var(--negative)" } as const;
const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const short = (iso: string) => `${MON[+iso.slice(5, 7) - 1]} ${+iso.slice(8, 10)}`;
const signed = (v: number, d = 1) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(d)}`;

export const useDailyState = () => useQuery({ queryKey: ["daily-state"], queryFn: api.dailyState, staleTime: STALE });
const usePlan = () => useQuery({ queryKey: ["workout-next"], queryFn: () => api.workoutNext(false), staleTime: 60 * 60 * 1000, retry: 1 });

const Skel = ({ h }: { h: number }) => <div className="ts-skeleton td-skel" style={{ height: h }} />;
const Err = ({ what, e }: { what: string; e: unknown }) => (
  <p className="td-err">
    Couldn&apos;t load {what}: {String(e)}
  </p>
);

/** Section header: number, title, one-line question. */
export function Block({ n, title, sub, aside, children, id }: { n: string; title: string; sub: string; aside?: ReactNode; children: ReactNode; id?: string }) {
  return (
    <section className="td-block scroll-mt-24" id={id}>
      <header className="td-bhead">
        <span className="td-n">{n}</span>
        <div>
          <h2>{title}</h2>
          <p>{sub}</p>
        </div>
        {aside}
      </header>
      {children}
    </section>
  );
}

// ── 01 The call ─────────────────────────────────────────────────────────────

/** Signals in the overnight roster; skin temp is served in °C and shown in °F. */
const SIGNALS: { key: string; label: string; metric?: MetricKey; unit: string; f?: boolean; d: number }[] = [
  { key: "hrv", label: "HRV", metric: "hrv", unit: "ms", d: 0 },
  { key: "rhr", label: "Resting HR", metric: "rhr", unit: "bpm", d: 0 },
  { key: "recovery_score", label: "WHOOP recovery", metric: "recovery", unit: "%", d: 0 },
  { key: "sleep_efficiency", label: "Sleep efficiency", metric: "sleep", unit: "%", d: 1 },
  { key: "respiratory_rate", label: "Breathing rate", unit: "br/min", d: 1 },
  { key: "skin_temp", label: "Skin temp", unit: "°F", f: true, d: 1 },
];

function bandPos(s: NoiseFloorSignal) {
  if (s.delta == null || s.swc == null) return null;
  const z = s.swc === 0 ? (s.delta === 0 ? 0 : Math.sign(s.delta) * 3) : s.delta / s.swc;
  return 50 + (Math.max(-3, Math.min(3, z)) / 3) * 50;
}

function Overnight() {
  const q = useQuery({ queryKey: ["noise-floor"], queryFn: () => api.noiseFloor(), staleTime: STALE });
  const open = useExplorer();
  if (q.isError) return <Err what="the overnight signals" e={q.error} />;
  if (!q.data) return <Skel h={420} />;
  const n = Object.keys(q.data.signals).length;
  const moved = q.data.moved.length;
  return (
    <div className="td-roster">
      <div className="td-roster-head">
        <span className="td-label">Overnight, against your own normal</span>
        <b>{moved === 0 ? "Nothing moved past your normal wobble" : `${moved} of ${n} signals moved past your normal wobble`}</b>
      </div>
      {SIGNALS.map(({ key, label, metric, unit, f, d }, i) => {
        const s = q.data!.signals[key];
        if (!s) return null;
        const pos = bandPos(s);
        const out = s.within_noise === false;
        const value = s.value == null ? null : f ? s.value * 1.8 + 32 : s.value;
        const delta = s.delta == null ? null : f ? s.delta * 1.8 : s.delta;
        const body = (
          <>
            <span className="td-sig-name">{label}</span>
            <span className="td-sig-val">
              {value == null ? "–" : value.toFixed(d)}
              <small>{unit}</small>
            </span>
            <span className="td-sig-track" aria-hidden="true">
              <span className="td-sig-band" />
              <span className="td-sig-mid" />
              {pos != null && <motion.span className={`td-sig-dot${out ? " out" : ""}`} initial={{ left: "50%" }} animate={{ left: `${pos}%` }} transition={{ delay: 0.2 + 0.06 * i, duration: 0.8, ease }} />}
            </span>
            <span className={`td-sig-delta${out ? " out" : ""}`}>
              {delta == null ? "–" : signed(delta, Math.max(d, Math.abs(delta) < 1 ? 1 : 0))}
              <small>{out ? (s.direction === "up" ? "moved ↑" : "moved ↓") : s.within_noise == null ? "no data" : "noise"}</small>
            </span>
          </>
        );
        const title = `${label}: baseline ${s.baseline == null ? "–" : (f ? s.baseline * 1.8 + 32 : s.baseline).toFixed(1)} ${unit}, normal band ±${((s.swc ?? 0) * (f ? 1.8 : 1)).toFixed(1)} ${unit}, ${s.n} nights`;
        return metric ? (
          <button key={key} className="td-sig" title={title} onClick={() => open(metric)}>
            {body}
          </button>
        ) : (
          <div key={key} className="td-sig" title={title}>
            {body}
          </div>
        );
      })}
      <div className="td-sig-axis" aria-hidden="true">
        <span>lower</span>
        <span>your normal band</span>
        <span>higher</span>
      </div>
    </div>
  );
}

function ReadinessEquation({ s }: { s: DailyState }) {
  const r = s.readiness;
  const parts = [
    { k: "hrv", label: "HRV" },
    { k: "sleep", label: "Sleep" },
    { k: "rhr", label: "Resting HR" },
    { k: "subj", label: "Check-in" },
  ] as const;
  const logged = parts.filter((p) => r.components[p.k] != null);
  const weakest = logged.length ? logged.reduce((a, b) => ((r.components[a.k] ?? 0) <= (r.components[b.k] ?? 0) ? a : b)) : null;
  const tier = r.tier === "green" ? "positive" : r.tier === "red" ? "negative" : "neutral";
  return (
    <div className="td-eq">
      <div className="td-eq-head">
        <span className="td-label">Readiness, built from four inputs</span>
        <b style={{ color: r.tier ? TONE[tier] : undefined }}>
          {r.score == null ? "–" : Math.round(r.score)}
          <small>{r.tier ?? "no data"}</small>
        </b>
      </div>
      <div className="td-eq-bar">
        {parts.map((p, i) => {
          const v = r.components[p.k];
          return (
            <div key={p.k} className={`td-eq-seg${p === weakest ? " weak" : ""}${v == null ? " none" : ""}`} style={{ flexGrow: r.weights[p.k] }} title={`${p.label}: ${v == null ? "not logged" : Math.round(v)} of 100, counts ${Math.round(r.weights[p.k] * 100)}%`}>
              <span className="td-eq-track">
                <motion.span className="td-eq-fill" initial={{ scaleY: 0 }} animate={{ scaleY: 1 }} style={{ height: `${v ?? 0}%`, transformOrigin: "bottom" }} transition={{ delay: 0.3 + 0.08 * i, duration: 0.7, ease }} />
              </span>
              <span className="td-eq-lbl">
                {p.label} <em>×{Math.round(r.weights[p.k] * 100)}%</em>
              </span>
              <b>{v == null ? "not logged" : Math.round(v)}</b>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function TheCall() {
  const state = useDailyState();
  const plan = usePlan();
  if (state.isError) return <Err what="today's state" e={state.error} />;
  const s = state.data;
  if (!s) return <Skel h={520} />;
  const p = plan.data;
  const cmd = readinessCommand(s, p);
  const g = s.gates;
  const locks = [
    ...g.forbid_muscle_groups.map((t) => ({ t, hard: true })),
    ...g.forbid_muscles.map((t) => ({ t, hard: false })),
    ...(g.max_intensity !== "high" ? [{ t: `ceiling ${g.max_intensity}`, hard: false }] : []),
    ...(g.deload_required ? [{ t: "deload", hard: true }] : []),
  ];
  const exs = p?.blocks.flatMap((b) => b.exercises) ?? [];
  const sets = exs.reduce((n, e) => n + e.sets, 0);
  const executed = p?.execution?.executed === true;
  const day = new Date(s.as_of + "T12:00:00").toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" });
  return (
    <header className="td-mast">
      <div className="td-mast-l">
        <span className="td-eyebrow">{day} · the call</span>
        <motion.h1 className="td-verdict" style={{ color: TONE[cmd.tone] }} initial={{ opacity: 0.001, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.7, ease }}>
          {cmd.label}
        </motion.h1>
        {/* `recommendation.rationale` is the planner's audit trail; `summary` is the dashboard sentence. */}
        <p className="td-why">{p?.recommendation.summary ?? g.deload_reason ?? g.reasons[0] ?? p?.readiness_summary ?? cmd.detail}</p>
        <div className="td-locks">
          <span className="td-label">Locked today</span>
          {locks.length === 0 ? (
            <span className="td-chip clear">nothing</span>
          ) : (
            locks.map((l) => (
              <span key={l.t} className={`td-chip ${l.hard ? "hard" : "soft"}`} title={g.reasons.find((r) => r.startsWith(l.t)) ?? undefined}>
                {l.t.replace(/_/g, " ")}
              </span>
            ))
          )}
        </div>
        {p && (
          <a className={`td-ticket${executed ? " done" : ""}`} href="#session">
            <span className="td-ticket-k">{executed ? "Trained" : "The session"}</span>
            <b>{p.recommendation.focus.split(/: | — /)[0]}</b>
            <span className="td-ticket-m">
              <span>
                <em>{exs.length}</em> lifts
              </span>
              <span>
                <em>{sets}</em> sets
              </span>
              {p.recommendation.estimated_duration_min != null && (
                <span>
                  <em>~{p.recommendation.estimated_duration_min}</em> min
                </span>
              )}
              {p.recommendation.target_rpe != null && (
                <span>
                  RPE <em>{p.recommendation.target_rpe}</em>
                </span>
              )}
            </span>
            <span className="td-ticket-go">Open ↓</span>
          </a>
        )}
        <ReadinessEquation s={s} />
      </div>
      <Overnight />
    </header>
  );
}

// ── 02 The tape ─────────────────────────────────────────────────────────────

type Lane = {
  key: string;
  label: string;
  unit: string;
  kind: "line" | "bar";
  y: (number | null)[];
  band?: ([number, number] | null)[];
  ref?: { v: number; label: string };
  color: (v: number) => string;
  fmt: (v: number) => string;
};

function isoDays(end: string, n: number) {
  const t = Date.parse(end + "T00:00:00Z");
  return Array.from({ length: n }, (_, i) => new Date(t - (n - 1 - i) * 86_400_000).toISOString().slice(0, 10));
}

const DAYS = 28;

export function Tape() {
  const st = useDailyState();
  const hrv = useQuery({ queryKey: ["hrv-trend", DAYS], queryFn: () => api.hrvTrend(DAYS), staleTime: STALE });
  const rec = useQuery({ queryKey: ["recovery-trend", DAYS], queryFn: () => api.recoveryTrend(DAYS), staleTime: STALE });
  const slp = useQuery({ queryKey: ["sleep-trend", DAYS], queryFn: () => api.sleepTrend(DAYS), staleTime: STALE });
  const load = useQuery({ queryKey: ["load-curve", DAYS], queryFn: () => api.loadCurve(DAYS), staleTime: STALE });
  const [ref, W] = useWidth(1200);
  const [hov, setHov] = useState<number | null>(null);
  // The measured wrapper renders from the first paint: useWidth observes once, at mount.
  const err = [st, hrv, rec, slp, load].find((q) => q.isError);
  if (err || !st.data || !hrv.data || !rec.data || !slp.data || !load.data)
    return (
      <div className="td-tape" ref={ref}>
        {err ? <Err what="the four-week tape" e={err.error} /> : <Skel h={400} />}
      </div>
    );
  const s = st.data;
  const dates = isoDays(s.as_of, DAYS);
  const by = <T extends { date: string }>(rows: T[]) => new Map(rows.map((r) => [r.date, r]));
  const H = by(hrv.data);
  const R = by(rec.data);
  const L = by(load.data.points);
  // The sleep route can return a nap beside the main sleep on one date; the main sleep is the longest.
  const S = new Map<string, number>();
  for (const p of slp.data) if (p.hours != null) S.set(p.date, Math.max(S.get(p.date) ?? 0, p.hours));

  const recColor = (v: number) => (v >= 67 ? "var(--positive)" : v >= 34 ? "var(--neutral)" : "var(--negative)");
  const lanes: Lane[] = [
    {
      key: "hrv",
      label: "HRV",
      unit: "ms",
      kind: "line",
      y: dates.map((d) => H.get(d)?.hrv ?? null),
      band: dates.map((d) => {
        const h = H.get(d);
        return h ? [h.avg - h.sd, h.avg + h.sd] : null;
      }),
      color: () => "var(--series-1)",
      fmt: (v) => v.toFixed(0),
    },
    {
      key: "rhr",
      label: "Resting HR",
      unit: "bpm",
      kind: "line",
      y: dates.map((d) => R.get(d)?.rhr ?? null),
      ref: s.recovery.rhr_baseline_28d != null ? { v: s.recovery.rhr_baseline_28d, label: "baseline" } : undefined,
      color: () => "var(--series-2)",
      fmt: (v) => v.toFixed(0),
    },
    { key: "rec", label: "WHOOP recovery", unit: "%", kind: "bar", y: dates.map((d) => R.get(d)?.score ?? null), color: recColor, fmt: (v) => v.toFixed(0) },
    {
      key: "sleep",
      label: "Sleep",
      unit: "h",
      kind: "bar",
      y: dates.map((d) => S.get(d) ?? null),
      ref: s.sleep.avg_7d != null ? { v: s.sleep.avg_7d, label: "7-day avg" } : undefined,
      color: () => "var(--series-1)",
      fmt: (v) => v.toFixed(1),
    },
    { key: "load", label: "Training load", unit: "", kind: "bar", y: dates.map((d) => L.get(d)?.load ?? null), color: () => "var(--series-2)", fmt: (v) => v.toFixed(1) },
  ];

  const P = { l: 150, r: 64, t: 6, b: 26 };
  const LH = 56;
  const GAP = 16;
  const height = P.t + lanes.length * LH + (lanes.length - 1) * GAP + P.b;
  const step = (W - P.l - P.r) / DAYS;
  const cx = (i: number) => P.l + step * (i + 0.5);
  const hi = hov ?? DAYS - 1;

  return (
    <div className="td-tape" ref={ref} onMouseLeave={() => setHov(null)}>
      <svg width={W} height={height} role="img" aria-label="Four weeks of HRV, resting HR, recovery, sleep and training load">
        {dates.map((d, i) =>
          new Date(d + "T00:00:00Z").getUTCDay() === 1 ? <line key={d} x1={cx(i) - step / 2} x2={cx(i) - step / 2} y1={P.t} y2={height - P.b + 4} className="td-week" /> : null,
        )}
        <rect x={cx(hi) - step / 2} y={P.t} width={step} height={height - P.t - P.b} className="td-hovcol" />
        {lanes.map((ln, li) => {
          const top = P.t + li * (LH + GAP);
          const vals = [...ln.y, ...(ln.band ?? []).flatMap((b) => b ?? []), ...(ln.ref ? [ln.ref.v] : [])].filter((v): v is number => v != null);
          if (!vals.length)
            return (
              <text key={ln.key} x={P.l} y={top + LH / 2} className="td-tick">
                No {ln.label.toLowerCase()} data in this window.
              </text>
            );
          let lo = ln.kind === "bar" ? 0 : Math.min(...vals);
          let hiV = Math.max(...vals);
          if (ln.kind === "line") {
            const pad = (hiV - lo) * 0.12 || 1;
            lo -= pad;
            hiV += pad;
          }
          const y = (v: number) => top + LH - ((v - lo) / (hiV - lo || 1)) * LH;
          const last = ln.y.reduce<number | null>((acc, v, i) => (v != null ? i : acc), null);
          const shown = hov == null ? (last == null ? null : ln.y[last]) : (ln.y[hov] ?? null);
          let path = "";
          ln.y.forEach((v, i) => {
            if (v == null) return;
            path += `${path && ln.y[i - 1] != null ? "L" : "M"}${cx(i).toFixed(1)},${y(v).toFixed(1)}`;
          });
          let band = "";
          if (ln.band) {
            const idx = ln.band.map((b, i) => (b ? i : -1)).filter((i) => i >= 0);
            if (idx.length > 1)
              band = `${idx.map((i, k) => `${k ? "L" : "M"}${cx(i).toFixed(1)},${y(ln.band![i]![1]).toFixed(1)}`).join("")}${[...idx]
                .reverse()
                .map((i) => `L${cx(i).toFixed(1)},${y(ln.band![i]![0]).toFixed(1)}`)
                .join("")}Z`;
          }
          const bw = Math.min(18, Math.max(3, step * 0.62));
          return (
            <g key={ln.key}>
              <line x1={P.l} x2={W - P.r} y1={top + LH} y2={top + LH} className="td-grid" />
              <text x={0} y={top + 14} className="td-lane-name">
                {ln.label}
              </text>
              <text x={0} y={top + 40} className="td-lane-val" style={{ fill: shown != null ? ln.color(shown) : undefined }}>
                {shown == null ? "–" : ln.fmt(shown)}
                <tspan className="td-lane-unit">{ln.unit ? ` ${ln.unit}` : ""}</tspan>
              </text>
              {band && <path d={band} className="td-band" />}
              {ln.ref && (
                <g>
                  <line x1={P.l} x2={W - P.r} y1={y(ln.ref.v)} y2={y(ln.ref.v)} className="td-ref" />
                  <text x={W - P.r + 6} y={y(ln.ref.v) + 4} className="td-tick">
                    {ln.fmt(ln.ref.v)} {ln.ref.label === "baseline" ? "base" : "avg"}
                  </text>
                </g>
              )}
              {ln.kind === "bar"
                ? ln.y.map((v, i) => {
                    if (v == null || v <= 0) return null;
                    const h = Math.max(2, top + LH - y(v));
                    return (
                      <rect key={i} x={cx(i) - bw / 2} width={bw} y={top + LH - h} height={h} rx={Math.min(3, bw / 3)} fill={ln.color(v)} opacity={hov == null || hov === i ? 0.9 : 0.4} className="td-bar" />
                    );
                  })
                : (
                    <>
                      <motion.path d={path} fill="none" stroke={ln.color(0)} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.8, ease }} />
                      {last != null && <circle cx={cx(last)} cy={y(ln.y[last]!)} r={4.5} fill={ln.color(0)} className="td-enddot" />}
                      {hov != null && ln.y[hov] != null && <circle cx={cx(hov)} cy={y(ln.y[hov]!)} r={3.5} fill={ln.color(0)} />}
                    </>
                  )}
              {last != null && (
                <text x={W - P.r + 6} y={(ln.kind === "bar" ? y(ln.y[last]!) : y(ln.y[last]!)) + 4} className="td-endlbl" style={{ fill: ln.color(ln.y[last]!) }}>
                  {ln.ref && Math.abs(y(ln.ref.v) - y(ln.y[last]!)) < 12 ? "" : ln.fmt(ln.y[last]!)}
                </text>
              )}
            </g>
          );
        })}
        {dates.map((d, i) =>
          i % 7 === DAYS % 7 || i === DAYS - 1 ? (
            <text key={d} x={cx(i)} y={height - 8} textAnchor="middle" className={`td-tick${i === DAYS - 1 ? " today" : ""}`}>
              {i === DAYS - 1 ? "today" : short(d)}
            </text>
          ) : null,
        )}
        <rect
          x={P.l}
          y={P.t}
          width={Math.max(0, W - P.l - P.r)}
          height={height - P.t - P.b}
          fill="transparent"
          onMouseMove={(e) => {
            const r = (e.currentTarget as SVGRectElement).getBoundingClientRect();
            const i = Math.floor(((e.clientX - r.left) / r.width) * DAYS);
            setHov(i >= 0 && i < DAYS ? i : null);
          }}
        />
      </svg>
      <span className="td-tape-day">{hov == null ? `Today · ${short(dates[DAYS - 1])}` : new Date(dates[hov] + "T12:00:00").toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" })}</span>
    </div>
  );
}

// ── 03 The session ──────────────────────────────────────────────────────────

/** A lift's last eight sessions (top set, lbs) with today's prescribed load as the end point. */
function LiftSpark({ name, target }: { name: string; target?: number }) {
  const q = useQuery({ queryKey: ["progression", name, 8], queryFn: () => api.trainingProgression(name, 8), staleTime: 10 * 60 * 1000, retry: 0 });
  const asOf = useDailyState().data?.as_of;
  const [ref, W] = useWidth(180);
  const H = 40;
  const hist = [...(q.data?.history ?? [])].reverse().filter((h) => h.max_lbs > 0);
  const last = hist[hist.length - 1];
  const ago = last && asOf ? Math.round((Date.parse(asOf) - Date.parse(last.date)) / 86_400_000) : null;
  const vals = [...hist.map((h) => h.max_lbs), ...(target ? [target] : [])];
  const lo = Math.min(...vals);
  const hi = Math.max(...vals);
  const n = hist.length + (target ? 1 : 0);
  const x = (i: number) => 4 + (i / Math.max(1, n - 1)) * (W - 8);
  const y = (v: number) => 6 + (hi === lo ? 0.5 : (hi - v) / (hi - lo)) * (H - 12);
  return (
    <div className="td-spark" ref={ref}>
      {q.isLoading ? (
        <span className="td-spark-note">…</span>
      ) : hist.length === 0 ? (
        <span className="td-spark-note">first time, no history</span>
      ) : (
        <>
          <svg width={W} height={H} aria-hidden="true">
            <path d={hist.map((h, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(h.max_lbs).toFixed(1)}`).join("")} fill="none" stroke="var(--series-1)" strokeWidth={1.75} strokeLinejoin="round" />
            {hist.map((h, i) => (
              <circle key={h.date} cx={x(i)} cy={y(h.max_lbs)} r={2} fill="var(--series-1)" />
            ))}
            {target != null && last && (
              <>
                <line x1={x(hist.length - 1)} x2={x(n - 1)} y1={y(last.max_lbs)} y2={y(target)} stroke="var(--series-2)" strokeWidth={1.5} strokeDasharray="3 3" />
                <circle cx={x(n - 1)} cy={y(target)} r={4} fill="var(--series-2)" className="td-enddot" />
              </>
            )}
          </svg>
          <span className="td-spark-note">
            last {last.max_lbs.toFixed(0)} lbs · {ago === 0 ? "today" : ago === 1 ? "yesterday" : ago != null && ago < 60 ? `${ago}d ago` : short(last.date)}
          </span>
        </>
      )}
    </div>
  );
}

const restLbl = (s?: number) => (s ? (s >= 60 ? `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}` : `${s}s`) : "–");

function ExRow({ ex, i, onPick }: { ex: WorkoutExercise; i: number; onPick: (n: string) => void }) {
  const [cues, setCues] = useState(false);
  const timed = String(ex.reps).includes("min");
  const perHand = /dumbbell/i.test(ex.name);
  return (
    <div className={`td-ex${cues ? " open" : ""}`}>
      <button className="td-ex-name no-tactile" onClick={() => onPick(ex.name)} title="Open this lift's progression">
        <span className="td-ex-i">{String(i + 1).padStart(2, "0")}</span>
        <b>{ex.name}</b>
      </button>
      {timed ? <div className="td-spark"><span className="td-spark-note">conditioning, by effort</span></div> : <LiftSpark name={ex.name} target={ex.weight_lbs ?? undefined} />}
      <span className="td-ex-dose">
        <b>
          {ex.sets}
          <i>×</i>
          {ex.reps}
        </b>
        <small>{timed ? "rounds × time" : "sets × reps"}</small>
      </span>
      <span className="td-ex-load">
        {ex.weight_lbs ? (
          <>
            <b>{ex.weight_lbs}</b>
            <small>{perHand ? "lbs / hand" : "lbs"}</small>
          </>
        ) : (
          <>
            <b className="dim">—</b>
            <small>{timed ? "no load" : "work up to RPE"}</small>
          </>
        )}
      </span>
      <span className="td-ex-rpe" title={`Target RPE ${ex.rpe_target}`}>
        <span className="td-pips">
          {[6, 7, 8, 9, 10].map((v) => (
            <i key={v} className={ex.rpe_target >= v ? (v >= 9 ? "on hot" : "on") : ""} />
          ))}
        </span>
        <small>RPE {ex.rpe_target}</small>
      </span>
      <span className="td-ex-rest">
        <b>{restLbl(ex.rest_seconds)}</b>
        <small>rest</small>
      </span>
      {ex.notes ? (
        <button className="td-ex-cue no-tactile" aria-expanded={cues} onClick={() => setCues((v) => !v)}>
          {cues ? "Hide" : "Cues"}
        </button>
      ) : (
        <span />
      )}
      {cues && ex.notes && <p className="td-ex-notes">{ex.notes}</p>}
    </div>
  );
}

type Push = { kind: "idle" } | { kind: "pushing" } | { kind: "ok"; focus: string } | { kind: "err"; msg: string };

export function SessionSheet() {
  const qc = useQueryClient();
  const q = usePlan();
  const [push, setPush] = useState<Push>({ kind: "idle" });
  const [picked, setPicked] = useState<string | null>(null);
  const [why, setWhy] = useState(false);
  const [busy, setBusy] = useState(false);
  if (q.isError) return <Err what="today's session" e={q.error} />;
  const p: WorkoutPlan | undefined = q.data;
  if (!p) return <Skel h={640} />;
  const ex = p.execution;
  const executed = ex?.executed === true;
  const now = new Date();
  const today = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
  const carried = (ex?.plan_date ?? p.generated_at) < today;
  const [head, ...rest] = p.recommendation.focus.split(/: | — /);
  const exs = p.blocks.flatMap((b) => b.exercises);

  async function pushHevy() {
    setPush({ kind: "pushing" });
    try {
      const r = await api.hevyPushRoutine(false);
      setPush({ kind: "ok", focus: r.plan_focus });
    } catch (e) {
      setPush({ kind: "err", msg: e instanceof Error ? e.message : "push failed" });
    }
  }
  async function discard() {
    if (!confirm("Discard today's plan and regenerate from current readiness?")) return;
    setBusy(true);
    try {
      await api.workoutDelete();
    } catch {
      /* a 404 still means there is nothing to keep: regenerate */
    }
    try {
      await qc.fetchQuery({ queryKey: ["workout-next"], queryFn: () => api.workoutNext(true) });
    } finally {
      setBusy(false);
      setPush({ kind: "idle" });
    }
  }

  let n = 0;
  return (
    <div className={`td-sheet${executed ? " done" : ""}`}>
      <div className="td-sheet-head">
        <div>
          <span className="td-label">
            {executed ? "Trained · this is the record, not a target" : carried ? `Last plan · written ${short(p.generated_at)}, not today's` : `Written ${short(p.generated_at)} · ${p.source === "fallback" ? "fallback planner" : "AI planner"}`}
          </span>
          <h3>{head}</h3>
          {rest.length > 0 && <p>{rest.join(": ")}</p>}
        </div>
        <div className="td-sheet-act">
          <button className={push.kind === "ok" ? "btn btn-primary" : "btn btn-secondary"} onClick={pushHevy} disabled={push.kind === "pushing" || executed} title={executed ? "Already trained: pushing would re-prescribe pre-session loads" : "Push today's plan to Hevy as a routine"}>
            {push.kind === "pushing" ? "Sending…" : push.kind === "ok" ? "In Hevy ✓" : "Send to Hevy"}
          </button>
          <button className="btn btn-ghost" onClick={discard} disabled={busy || q.isFetching} title="Delete today's plan and regenerate">
            {busy ? "Rebuilding…" : "Discard"}
          </button>
        </div>
      </div>
      {push.kind === "err" && <p className="td-note bad">Hevy push failed: {push.msg}</p>}
      {push.kind === "ok" && <p className="td-note good">{push.focus} is ready in Hevy. Open the app to start.</p>}
      {executed && ex && (
        <p className="td-note good">
          Logged {ex.sets_done} working sets{ex.prescribed_sets > 0 ? ` of ${ex.prescribed_sets}` : ""}
          {ex.avg_rpe != null ? ` at avg RPE ${ex.avg_rpe.toFixed(1)}` : ""}
          {ex.exercises.length ? `: ${ex.exercises.join(" · ")}` : ""}. Don&apos;t train it again off these loads.
        </p>
      )}
      <div className="td-sheet-stats">
        <div>
          <b>{exs.length}</b>
          <span>lifts</span>
        </div>
        <div>
          <b>{exs.reduce((a, e) => a + e.sets, 0)}</b>
          <span>working sets</span>
        </div>
        <div>
          <b>{p.recommendation.estimated_duration_min != null ? `~${p.recommendation.estimated_duration_min}` : "–"}</b>
          <span>minutes</span>
        </div>
        <div>
          <b>{p.recommendation.target_rpe ?? "–"}</b>
          <span>target RPE</span>
        </div>
        <div className="td-warm">
          <span className="td-label">Warm-up</span>
          <p>{p.warmup.length ? p.warmup.map((w) => `${w.name} ${w.sets && w.reps ? (String(w.reps).includes("min") ? w.reps : `${w.sets}×${w.reps}`) : w.duration_sec ? `${w.duration_sec}s` : ""}`.trim()).join(" · ") : "None written"}</p>
        </div>
      </div>
      <div className="td-ex-head" aria-hidden="true">
        <span>Lift</span>
        <span>Last 8 sessions → today</span>
        <span>Dose</span>
        <span>Load</span>
        <span>Effort</span>
        <span>Rest</span>
        <span />
      </div>
      <div className="td-ex-list">
        {p.blocks.map((b) => (
          <div key={b.label} className="td-ex-block">
            <span className="td-ex-blabel">{b.label.replace(/ - /g, " · ")}</span>
            {b.exercises.map((e) => (
              <ExRow key={e.name} ex={e} i={n++} onPick={setPicked} />
            ))}
          </div>
        ))}
      </div>
      <div className="td-sheet-foot">
        <p>
          <span className="td-label">Cool-down</span> {p.cooldown || "None written"}
        </p>
        <button className="td-why-btn no-tactile" aria-expanded={why} onClick={() => setWhy((v) => !v)}>
          {why ? "Hide why this session" : "Why this session ↓"}
        </button>
      </div>
      {why && (
        <div className="td-why-box">
          {p.readiness_summary && <p>{p.readiness_summary}</p>}
          {p.recommendation.rationale && <p className="dim">{p.recommendation.rationale}</p>}
          <div className="td-why-cols">
            {p.clinical_notes.length > 0 && (
              <div>
                <span className="td-label">Clinical notes</span>
                <ul>
                  {p.clinical_notes.map((t) => (
                    <li key={t}>{t}</li>
                  ))}
                </ul>
              </div>
            )}
            {p.vault_insights.length > 0 && (
              <div>
                <span className="td-label">From the research vault</span>
                <ul>
                  {p.vault_insights.map((t) => (
                    <li key={t}>{t}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </div>
      )}
      <ProgressionDrawer exercise={picked} onClose={() => setPicked(null)} />
    </div>
  );
}

// ── 04 The body ─────────────────────────────────────────────────────────────

const AX = [0.6, 1.8] as const;
const ax = (v: number) => ((Math.max(AX[0], Math.min(AX[1], v)) - AX[0]) / (AX[1] - AX[0])) * 100;

export function BodyCheck() {
  const st = useDailyState();
  const curve = useQuery({ queryKey: ["load-curve", 42], queryFn: () => api.loadCurve(42), staleTime: STALE });
  if (st.isError) return <Err what="training load" e={st.error} />;
  if (!st.data) return <Skel h={560} />;
  // Served by /api/state/today but not yet on the shared DailyStateLoad type.
  const t = st.data.training_load as DailyState["training_load"] & Partial<Record<"resistance_acute_7d" | "resistance_chronic_21d" | "conditioning_acute_7d" | "conditioning_chronic_21d", number | null>>;
  const g = st.data.gates;
  const ratios: [string, number | null | undefined, number | null | undefined, number | null | undefined][] = [
    ["All training", t.acwr, t.acute_load_7d, t.chronic_load_21d],
    ["Lifting", t.resistance_acwr, t.resistance_acute_7d, t.resistance_chronic_21d],
    ["Conditioning", t.conditioning_acwr, t.conditioning_acute_7d, t.conditioning_chronic_21d],
  ];
  const patterns: [string, number | null | undefined][] = [
    ["Legs", t.days_since_legs],
    ["Push", t.days_since_push],
    ["Pull", t.days_since_pull],
    ["Court", t.days_since_pickleball],
  ];
  const muscles = Object.entries(t.muscle_recovery ?? {}).sort((a, b) => (a[1].days_since_dose ?? 99) - (b[1].days_since_dose ?? 99));
  const pts = curve.data?.points ?? [];
  return (
    <div className="td-body">
      <div className="td-body-top">
        <div className="td-acwr">
          <span className="td-label">Last 7 days vs the 21 before</span>
          {ratios.map(([label, v, a, c], i) => (
            <div key={label} className="td-acwr-row">
              <span>
                {label}
                <small>{a != null && c != null ? `${a.toFixed(1)} vs ${c.toFixed(1)}` : "no load yet"}</small>
              </span>
              <span className="td-acwr-track" style={{ ["--a" as string]: `${ax(0.8)}%`, ["--b" as string]: `${ax(1.3)}%`, ["--c" as string]: `${ax(1.5)}%` }}>
                {v != null && <motion.i className={v >= 1.5 ? "hot" : ""} initial={{ left: `${ax(1)}%` }} animate={{ left: `${ax(v)}%` }} transition={{ delay: 0.1 * i, duration: 0.8, ease }} />}
              </span>
              <b>{v == null ? "–" : v.toFixed(2)}</b>
            </div>
          ))}
          <div className="td-acwr-axis" aria-hidden="true">
            <span style={{ left: `${ax(0.8)}%` }}>0.8</span>
            <span style={{ left: `${ax(1.3)}%` }}>1.3</span>
            <span style={{ left: `${ax(1.5)}%` }}>1.5 gate</span>
          </div>
          <p className="td-foot">Daily load, last 7 days vs the 21 before. Green is steady building; from 1.5 the engine starts locking muscles.</p>
        </div>
        <div className="td-fresh">
          <span className="td-label">Days since</span>
          <div className="td-pat">
            {patterns.map(([l, d]) => (
              <div key={l} style={{ ["--f" as string]: d == null ? 0 : Math.min(d / 4, 1) }}>
                <b>{d == null ? "–" : d}</b>
                <span>{l}</span>
              </div>
            ))}
          </div>
          {muscles.length > 0 && (
            <ul className="td-doses">
              {muscles.map(([m, v]) => {
                const locked = g.forbid_muscles.includes(m);
                return (
                  <li key={m} className={locked ? "locked" : ""}>
                    <span>{m.replace(/_/g, " ")}</span>
                    <em>
                      {v.last_dose_sets ?? "–"} sets{v.last_rpe != null ? ` @ ${v.last_rpe}` : ""}
                    </em>
                    <b>{v.days_since_dose == null ? "–" : `${v.days_since_dose}d`}</b>
                    {locked && <i>locked</i>}
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </div>
      <div className="td-body-chart">
        <span className="td-label">Fitness vs fatigue, last 6 weeks</span>
        {pts.length > 1 ? (
          <FillLines
            labels={pts.map((p) => p.date)}
            series={[
              { name: "Fitness", color: "var(--series-1)", y: pts.map((p) => p.ctl) },
              { name: "Fatigue", color: "var(--series-2)", y: pts.map((p) => p.atl) },
            ]}
            min={170}
            fmt={(v) => v.toFixed(0)}
          />
        ) : curve.isError ? (
          <Err what="the load curve" e={curve.error} />
        ) : (
          <Skel h={170} />
        )}
      </div>
    </div>
  );
}

// ── 05 The write-up ─────────────────────────────────────────────────────────

/** The generated morning report: one section at a time, set in two balanced columns. */
export function WriteUp() {
  const q = useQuery({ queryKey: ["daily-report"], queryFn: () => api.dailyReport(), refetchInterval: 300_000 });
  const asOf = useDailyState().data?.as_of;
  const [tab, setTab] = useState(0);
  const [copied, setCopied] = useState<"idle" | "ok" | "err">("idle");
  async function copyPrompt() {
    try {
      const { prompt } = await api.dailyReportPrompt();
      await navigator.clipboard.writeText(prompt);
      setCopied("ok");
    } catch {
      setCopied("err");
    }
    setTimeout(() => setCopied("idle"), 2500);
  }
  if (q.isError) return <Err what="the morning report" e={q.error} />;
  if (!q.data) return <Skel h={240} />;
  const r = q.data.report;
  const stale = r != null && asOf != null && r.report_date !== asOf;
  const sec = r?.sections[Math.min(tab, (r?.sections.length ?? 1) - 1)];
  return (
    <div className="td-wu">
      <div className="td-wu-head">
        <div>
          <span className="td-label">
            {r ? `${r.mode === "post_workout" ? "Post-workout" : r.mode === "pre_workout" ? "Pre-workout" : "Report"} · ${short(r.report_date)}` : "No report yet"}
          </span>
          <p className={stale ? "stale" : ""}>
            {!r
              ? "Generate one, run the copied prompt in Claude Code, and it posts the full write-up here."
              : stale
                ? `No report for today. This one is from ${short(r.report_date)}, so its advice may not apply.`
                : (r.readiness_headline ?? "Today's report")}
          </p>
        </div>
        <button className={`btn ${copied === "ok" ? "btn-primary" : "btn-secondary"}`} onClick={copyPrompt}>
          {copied === "ok" ? "Copied: run it in Claude Code" : copied === "err" ? "Copy failed" : "Generate today's report"}
        </button>
      </div>
      {r && r.sections.length > 0 && (
        <>
          <div className="td-wu-tabs" role="tablist">
            {r.sections.map((s, i) => (
              <button key={s.title} role="tab" aria-selected={s === sec} className={`no-tactile${s === sec ? " on" : ""}`} onClick={() => setTab(i)}>
                <em>{String(i + 1).padStart(2, "0")}</em>
                {s.title}
              </button>
            ))}
          </div>
          {sec && (
            <div className={`td-wu-body${stale ? " stale" : ""}`}>
              <Markdown text={sec.body_md} />
            </div>
          )}
          {r.sources.length > 0 && (
            <div className="td-wu-src">
              <span className="td-label">Research cited</span>
              {r.sources.map((s) => (
                <ObsidianSourceTag key={s} source={s} />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
