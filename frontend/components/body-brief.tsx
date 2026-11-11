"use client";

import { useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { api, type TapeField } from "@/lib/api";
import { ease, Fill, niceTicks, useWidth } from "@/components/kit";
import { useDailyState } from "@/components/today-brief";

/**
 * Body as a ledger of change: when each body reading last came in and what it
 * would take to read the recomposition again, the energy that kept reporting
 * when the scale didn't, the weight record with its silence drawn as silence,
 * and six months of the slow signals on one tape. Values render as served.
 */

const STALE = 10 * 60 * 1000;
const DAY = 86_400_000;
const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const short = (iso: string) => `${MON[+iso.slice(5, 7) - 1]} ${+iso.slice(8, 10)}`;
const monthLbl = (iso: string) => `${MON[+iso.slice(5, 7) - 1]} ’${iso.slice(2, 4)}`;
const t = (iso: string) => Date.parse(iso + "T00:00:00Z");
const monthIdx = (iso: string) => +iso.slice(0, 4) * 12 + +iso.slice(5, 7);
const ago = (iso: string, today: string) => Math.round((t(today) - t(iso)) / DAY);
const signed = (v: number) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(Math.round(v)).toLocaleString()}`;
const kcal = (v: number) => Math.round(v).toLocaleString();

const Skel = ({ h }: { h: number }) => <div className="ts-skeleton td-skel" style={{ height: h }} />;
const Err = ({ what, e }: { what: string; e: unknown }) => (
  <p className="td-err">
    Couldn&apos;t load {what}: {String(e)}
  </p>
);

const useWeight = () => useQuery({ queryKey: ["body-trend"], queryFn: api.bodyTrend, staleTime: STALE });
const useTape = () => useQuery({ queryKey: ["body-tape"], queryFn: api.tape, staleTime: STALE });
const usePhotos = () => useQuery({ queryKey: ["progress-photos"], queryFn: () => api.progressPhotos(), staleTime: STALE });
const useVo2 = () => useQuery({ queryKey: ["body-vo2"], queryFn: api.bodyVO2Max, staleTime: STALE });
const useSteps = () => useQuery({ queryKey: ["body-steps", 180], queryFn: () => api.bodySteps(180), staleTime: STALE });
const useFood = () => useQuery({ queryKey: ["fueling-trend", 90], queryFn: () => api.fuelingTrend(90), staleTime: STALE });
const useBurn = () => useQuery({ queryKey: ["body-expenditure", 400], queryFn: () => api.bodyExpenditure(400), staleTime: STALE });
const useRhr = () => useQuery({ queryKey: ["body-rhr", 180], queryFn: () => api.bodyRHRTrend(180), staleTime: STALE });
const useAirway = () => useQuery({ queryKey: ["sleep-airway", 180], queryFn: () => api.sleepAirway(180), staleTime: STALE });

// ── 01 The read ─────────────────────────────────────────────────────────────

type Reading = { key: string; label: string; last: string | null; every: number; need: string; src: string };
type Status = "current" | "late" | "stale" | "never";
const status = (r: Reading, today: string): Status => {
  if (!r.last) return "never";
  const a = ago(r.last, today);
  return a <= r.every ? "current" : a <= r.every * 4 ? "late" : "stale";
};
/** Age on a log scale, so a day and a year both fit one track. */
const agePos = (d: number) => Math.min(100, (Math.log1p(Math.max(0, d)) / Math.log1p(365)) * 100);

function useReadings(): { rows: Reading[] | null; today: string | null; error: unknown } {
  const st = useDailyState();
  const qs = { w: useWeight(), tape: useTape(), ph: usePhotos(), vo2: useVo2(), steps: useSteps(), food: useFood(), burn: useBurn() };
  const err = [st, ...Object.values(qs)].find((q) => q.isError);
  if (err) return { rows: null, today: null, error: err.error };
  if (!st.data || Object.values(qs).some((q) => !q.data)) return { rows: null, today: null, error: null };
  const lastOf = (ds: string[]) => (ds.length ? ds.reduce((a, b) => (a > b ? a : b)) : null);
  // A lone snapshot day (a Shortcut push) isn't a day's count; the import is current only through a run of days.
  const stepDays = qs.steps.data!.map((p) => p.date);
  const run = stepDays.filter((d, i) => i > 0 && ago(stepDays[i - 1], d) === 1);
  const rows: Reading[] = [
    { key: "weight", label: "Weigh-in", last: lastOf(qs.w.data!.map((p) => p.date)), every: 3, need: "morning weigh-ins, fasted", src: "scale or check-in" },
    { key: "waist", label: "Waist tape", last: qs.tape.data!.waist_in?.date ?? null, every: 7, need: "a waist reading each week", src: "logged here" },
    { key: "photos", label: "Progress photos", last: lastOf(qs.ph.data!.map((p) => p.photo_date)), every: 28, need: "front and side every four weeks", src: "uploaded here" },
    { key: "vo2", label: "VO₂ max", last: lastOf(qs.vo2.data!.filter((p) => p.source === "apple_watch").map((p) => p.date)), every: 14, need: "an Apple Health import", src: "Apple Watch" },
    { key: "steps", label: "Steps", last: lastOf(run), every: 2, need: "an Apple Health import", src: "Apple Health" },
    { key: "food", label: "Food log", last: lastOf(qs.food.data!.filter((p) => p.kcal_in != null).map((p) => p.date)), every: 2, need: "intake from the food logger", src: "food logger" },
    { key: "burn", label: "Energy out", last: qs.burn.data!.as_of ?? null, every: 2, need: "the strap worn", src: "WHOOP cycles" },
  ];
  return { rows, today: st.data.as_of, error: null };
}

function Ledger({ rows, today }: { rows: Reading[]; today: string }) {
  const current = rows.filter((r) => status(r, today) === "current").length;
  return (
    <div className="td-roster bo-ledger" id="ledger">
      <div className="td-roster-head">
        <span className="td-label">When each reading last came in</span>
        <b>
          {current} of {rows.length} body readings are current
        </b>
      </div>
      {rows.map((r, i) => {
        const s = status(r, today);
        const a = r.last ? ago(r.last, today) : null;
        return (
          <div key={r.key} className={`bo-row ${s}`} title={`${r.label} from ${r.src}. Due every ${r.every} days.${s === "current" ? "" : ` Needs ${r.need}.`}`}>
            <span className="bo-row-name">
              {r.label}
              <small>{r.last ? short(r.last) + (r.last.slice(0, 4) !== today.slice(0, 4) ? ` ${r.last.slice(0, 4)}` : "") : "never logged"}</small>
            </span>
            <span className="bo-age" aria-hidden="true">
              <span className="bo-age-due" style={{ left: `${agePos(r.every)}%` }} />
              {a != null ? (
                <motion.span className="bo-age-fill" initial={{ width: 0 }} animate={{ width: `${Math.max(2, agePos(a))}%` }} transition={{ delay: 0.15 + 0.05 * i, duration: 0.8, ease }} />
              ) : (
                <span className="bo-age-none" />
              )}
            </span>
            <span className="bo-row-age">
              {a == null ? "–" : a === 0 ? "today" : `${a}d`}
              <small>{s === "current" ? "current" : s === "never" ? "no record" : s === "late" ? "late" : "stale"}</small>
            </span>
          </div>
        );
      })}
      <div className="bo-row bo-axis-row" aria-hidden="true">
        <span />
        <span className="bo-age-axis">
        {[
          [1, "1d"],
          [7, "1wk"],
          [30, "1mo"],
          [90, "3mo"],
          [365, "1yr"],
        ].map(([d, l]) => (
          <span key={l} style={{ left: `${agePos(d as number)}%` }}>
            {l}
          </span>
        ))}
        </span>
        <span />
      </div>
    </div>
  );
}

export function TheRead() {
  const st = useDailyState();
  const burn = useBurn();
  const { rows, today, error } = useReadings();
  if (error) return <Err what="the body readings" e={error} />;
  if (!rows || !today || !st.data || !burn.data) return <Skel h={520} />;
  const by = Object.fromEntries(rows.map((r) => [r.key, r]));
  const w = by.weight;
  const wAge = w.last ? ago(w.last, today) : null;
  const trend = st.data.checkin.body_weight_trend_4wk;
  const blind = wAge == null || wAge > 14;
  const verdict = blind ? "Unmeasured" : trend == null ? "Weighing in" : Math.abs(trend) < 0.5 ? "Holding" : trend > 0 ? "Gaining" : "Losing";
  const tone = blind ? "var(--neutral)" : "var(--text-primary)";
  const waist = by.waist.last;
  const sh = burn.data.shift;
  const dT = sh?.now != null && sh.prior != null ? sh.now - sh.prior : null;
  const dC = sh?.court_now != null && sh.court_prior != null ? sh.court_now - sh.court_prior : null;
  const needs = rows.filter((r) => ["weight", "waist", "photos"].includes(r.key) && status(r, today) !== "current");
  const day = new Date(today + "T12:00:00").toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" });
  return (
    <header className="td-mast bo-mast" id="read">
      <div className="td-mast-l">
        <span className="td-eyebrow">{day} · composition</span>
        <motion.h1 className="td-verdict" style={{ color: tone }} initial={{ opacity: 0.001, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.7, ease }}>
          {verdict}
        </motion.h1>
        <p className="td-why">
          {blind
            ? `No weigh-in for ${wAge == null ? "as long as the record runs" : `${wAge} days`}${waist ? `, waist last taped ${short(waist)}` : " and no waist tape on record"}, so whether the recomposition is working can't be read yet.`
            : `Weight ${trend == null ? "is logging again" : `${trend > 0 ? "up" : trend < 0 ? "down" : "flat"} ${Math.abs(trend).toFixed(1)}% over four weeks`}. Under recomposition the target is flat weight while the lifts climb.`}
          {dT != null && (
            <>
              {" "}
              Energy out kept reporting: <b>{signed(dT)} kcal a day</b> against three months ago
              {dC != null && Math.sign(dC) === Math.sign(dT) && Math.abs(dC) >= Math.abs(dT) ? ", and court time alone accounts for all of it." : "."}
            </>
          )}
        </p>
        {needs.length > 0 && (
          <a className="td-ticket bo-ticket" href="#log">
            <span className="td-ticket-k">To read it</span>
            <b>{needs.length === 1 ? `Restart ${needs[0].label.toLowerCase()}` : "Restart the measurements"}</b>
            <span className="td-ticket-m">
              {needs.map((r) => (
                <span key={r.key}>
                  <em>{r.label}</em> {r.need}
                </span>
              ))}
            </span>
            <span className="td-ticket-go">Log ↓</span>
          </a>
        )}
        {sh && (
          <div className="bo-stats" id="energy-shift">
            <div>
              <span className="td-label">Out, last 4 wk</span>
              <b>{sh.now != null ? kcal(sh.now) : "–"}</b>
              <small>kcal / day</small>
            </div>
            <div>
              <span className="td-label">vs 3 months ago</span>
              <b className={dT != null && dT < 0 ? "down" : ""}>{dT != null ? signed(dT) : "–"}</b>
              <small>{sh.prior != null ? `from ${kcal(sh.prior)}` : "no prior window"}</small>
            </div>
            <div>
              <span className="td-label">Court time</span>
              <b className="court">{dC != null ? signed(dC) : "–"}</b>
              <small>{sh.court_now != null ? `now ${kcal(sh.court_now)} / day` : ""}</small>
            </div>
            <div>
              <span className="td-label">Everything else</span>
              <b>{dT != null && dC != null ? signed(dT - dC) : "–"}</b>
              <small>outside the court</small>
            </div>
          </div>
        )}
      </div>
      <Ledger rows={rows} today={today} />
    </header>
  );
}

// ── 02 Energy out ───────────────────────────────────────────────────────────

/** Path over evenly spaced dates; a missing step lifts the pen. */
function datePath(pts: { d: string; v: number }[], x: (iso: string) => number, y: (v: number) => number, every = 1) {
  let s = "";
  pts.forEach((p, i) => {
    const pen = i > 0 && ago(pts[i - 1].d, p.d) === every;
    s += `${pen ? "L" : "M"}${x(p.d).toFixed(1)},${y(p.v).toFixed(1)}`;
  });
  return s;
}

export function EnergyOut() {
  const q = useBurn();
  const [ref, W] = useWidth(1200);
  const [hov, setHov] = useState<number | null>(null);
  if (q.isError || !q.data)
    return (
      <div className="bo-chart" ref={ref}>
        {q.isError ? <Err what="energy expenditure" e={q.error} /> : <Skel h={360} />}
      </div>
    );
  const asOf = q.data.as_of ?? q.data.points[q.data.points.length - 1]?.date;
  // Non-overlapping weeks: the trailing-week measure sampled every seventh day back from the latest.
  const pts = q.data.points.filter((p) => asOf && ago(p.date, asOf) % 7 === 0);
  const sh = q.data.shift;
  if (pts.length < 2)
    return (
      <div className="bo-chart" ref={ref}>
        <p className="td-foot">No WHOOP cycles with energy recorded yet.</p>
      </div>
    );
  const H = 340;
  const P = { l: 52, r: 132, t: 40, b: 28 };
  const t0 = t(pts[0].date);
  const t1 = t(pts[pts.length - 1].date);
  const x = (iso: string) => P.l + ((t(iso) - t0) / (t1 - t0 || 1)) * (W - P.l - P.r);
  const lo0 = Math.min(...pts.map((p) => p.kcal - p.court));
  const ticks = niceTicks(lo0, Math.max(...pts.map((p) => p.kcal)), 4);
  const lo = ticks[0];
  const hi = ticks[ticks.length - 1];
  const y = (v: number) => P.t + (1 - (v - lo) / (hi - lo || 1)) * (H - P.t - P.b);
  const total = datePath(pts.map((p) => ({ d: p.date, v: p.kcal })), x, y, 7);
  const outside = datePath(pts.map((p) => ({ d: p.date, v: p.kcal - p.court })), x, y, 7);
  const court = `${pts.map((p, i) => `${i ? "L" : "M"}${x(p.date).toFixed(1)},${y(p.kcal).toFixed(1)}`).join("")}${[...pts]
    .reverse()
    .map((p) => `L${x(p.date).toFixed(1)},${y(p.kcal - p.court).toFixed(1)}`)
    .join("")}Z`;
  const end = pts[pts.length - 1];
  const iso = (ms: number) => new Date(ms).toISOString().slice(0, 10);
  const win = sh ? [{ label: "last 4 weeks", e: t1 }, { label: "3 months before", e: t1 - sh.lag_days * DAY }].map((w) => ({ ...w, x0: x(iso(w.e - (sh.window_days - 1) * DAY)), x1: x(iso(w.e)) })) : [];
  const months: string[] = [];
  for (let m = new Date(t0); m.getTime() <= t1; m.setUTCMonth(m.getUTCMonth() + 1, 1)) if (m.getUTCDate() === 1 || m.getTime() === t0) months.push(iso(m.getTime()).slice(0, 7) + "-01");
  const mt = months.filter((m) => t(m) >= t0);
  const every = Math.ceil(mt.length / Math.max(2, Math.floor((W - P.l - P.r) / 90)));
  const h = hov == null ? null : pts[hov];
  const yEndT = y(end.kcal);
  const yEndO = Math.max(yEndT + 16, y(end.kcal - end.court));
  return (
    <div className="bo-chart" ref={ref} onMouseLeave={() => setHov(null)}>
      <div className="bo-chart-key">
        <span>
          <i style={{ background: "var(--series-1)" }} /> All energy out
        </span>
        <span>
          <i style={{ background: "var(--series-2)" }} /> Court time
        </span>
        <span>
          <i className="dash" /> Everything outside the court
        </span>
        <span className="bo-chart-read">
          {h ? (
            <>
              Week to {short(h.date)} <b>{kcal(h.kcal)}</b> total · <b className="court">{kcal(h.court)}</b> court · <b>{kcal(h.kcal - h.court)}</b> outside
            </>
          ) : (
            "Hover to read a week"
          )}
        </span>
      </div>
      <svg width={W} height={H} role="img" aria-label="Seven-day energy expenditure with court time split out">
        <defs>
          <pattern id="bo-win" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <line x1="0" y1="0" x2="0" y2="6" stroke="oklch(1 0 0 / 0.06)" strokeWidth="3" />
          </pattern>
        </defs>
        {ticks.map((v) => (
          <g key={v}>
            <line x1={P.l} x2={W - P.r} y1={y(v)} y2={y(v)} className={v === lo ? "td-grid" : "td-week"} />
            <text x={P.l - 8} y={y(v) + 4} textAnchor="end" className="td-tick">
              {v >= 1000 ? `${(v / 1000).toFixed(1)}k` : v}
            </text>
          </g>
        ))}
        {win.map((w) => (
          <g key={w.label}>
            <rect x={w.x0} y={P.t - 18} width={Math.max(2, w.x1 - w.x0)} height={H - P.t - P.b + 18} fill="url(#bo-win)" />
            <text x={(w.x0 + w.x1) / 2} y={P.t - 24} textAnchor="middle" className="td-tick">
              {w.label}
            </text>
          </g>
        ))}
        <motion.path d={court} fill="var(--series-2)" initial={{ opacity: 0 }} animate={{ opacity: 0.28 }} transition={{ duration: 0.9, delay: 0.2 }} />
        <path d={outside} fill="none" stroke="var(--text-dim)" strokeWidth={1.5} strokeDasharray="4 3" />
        <motion.path d={total} fill="none" stroke="var(--series-1)" strokeWidth={2.25} strokeLinejoin="round" strokeLinecap="round" initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ duration: 1.2, ease }} />
        <circle cx={x(end.date)} cy={yEndT} r={4.5} fill="var(--series-1)" className="td-enddot" />
        <text x={W - P.r + 10} y={yEndT + 4} className="td-endlbl" style={{ fill: "var(--series-1)" }}>
          {kcal(end.kcal)} total
        </text>
        <text x={W - P.r + 10} y={yEndO + 4} className="td-endlbl" style={{ fill: "var(--text-dim)" }}>
          {kcal(end.kcal - end.court)} outside
        </text>
        {mt.map((m, i) =>
          i % every === 0 ? (
            <text key={m} x={x(m)} y={H - 8} textAnchor="middle" className="td-tick">
              {monthLbl(m)}
            </text>
          ) : null,
        )}
        {h && <line x1={x(h.date)} x2={x(h.date)} y1={P.t} y2={H - P.b} className="td-ref" />}
        {h && <circle cx={x(h.date)} cy={y(h.kcal)} r={3.5} fill="var(--series-1)" />}
        <rect
          x={P.l}
          y={P.t}
          width={Math.max(0, W - P.l - P.r)}
          height={H - P.t - P.b}
          fill="transparent"
          onMouseMove={(e) => {
            const r = e.currentTarget.getBoundingClientRect();
            const ms = t0 + ((e.clientX - r.left) / r.width) * (t1 - t0);
            let best = 0;
            pts.forEach((p, i) => {
              if (Math.abs(t(p.date) - ms) < Math.abs(t(pts[best].date) - ms)) best = i;
            });
            setHov(best);
          }}
        />
      </svg>
      <p className="td-foot">
        One point a week: WHOOP&apos;s energy per cycle, summed over the week and scaled to a 24-hour day, dated by when the cycle ended (Lab measure <code>{q.data.measure}</code>). The copper band is pickleball sessions over the same week. Shaded weeks are the two windows the change above compares.
      </p>
    </div>
  );
}

// ── 03 Weight and waist ─────────────────────────────────────────────────────

export function WeightRecord() {
  const q = useWeight();
  const st = useDailyState();
  const [ref, W] = useWidth(800);
  if (q.isError || !q.data || !st.data)
    return (
      <div className="bo-chart" ref={ref}>
        {q.isError ? <Err what="the weight record" e={q.error} /> : <Skel h={320} />}
      </div>
    );
  const today = st.data.as_of;
  const all = q.data;
  if (!all.length)
    return (
      <div className="bo-chart" ref={ref}>
        <p className="td-foot">No weigh-ins on record. Log one below.</p>
      </div>
    );
  const last = all[all.length - 1];
  const from = new Date(t(last.date) - 730 * DAY).toISOString().slice(0, 10);
  const pts = all.filter((p) => p.date >= from);
  const P = { l: 44, r: 20, t: 18, b: 28 };
  const t0 = t(pts[0].date);
  const t1 = t(today);
  const x = (iso: string) => P.l + ((t(iso) - t0) / (t1 - t0 || 1)) * (W - P.l - P.r);
  const ticks = niceTicks(Math.min(...pts.map((p) => p.lbs)), Math.max(...pts.map((p) => p.lbs)), 4);
  const lo = ticks[0];
  const hi = ticks[ticks.length - 1];
  // Monthly means, placed mid-month, are the line; every weigh-in is a dot under it.
  const mm = new Map<string, number[]>();
  pts.forEach((p) => mm.set(p.date.slice(0, 7), [...(mm.get(p.date.slice(0, 7)) ?? []), p.lbs]));
  const line = [...mm].map(([m, v]) => ({ d: `${m}-15`, v: v.reduce((a, b) => a + b, 0) / v.length }));
  const gap = ago(last.date, today);
  const gx = x(last.date);
  // Quarter starts on a time axis, thinned to fit; a month with no weigh-in still gets its place.
  const quarters: string[] = [];
  for (let yr = +pts[0].date.slice(0, 4); yr <= +today.slice(0, 4); yr++)
    for (const m of ["01", "04", "07", "10"]) if (t(`${yr}-${m}-01`) > t0 && t(`${yr}-${m}-01`) < t1 - 45 * DAY) quarters.push(`${yr}-${m}`);
  const months = quarters.filter((_, i, a) => i % Math.ceil(a.length / Math.max(2, Math.floor(W / 110))) === 0);
  return (
    <div className="bo-chart bo-fill" ref={ref}>
      <Fill min={280}>
        {(H) => {
          const y = (v: number) => P.t + (1 - (v - lo) / (hi - lo || 1)) * (H - P.t - P.b);
          return (
      <svg width={W} height={H} role="img" aria-label="Weigh-ins over two years, with the stretch since the last one marked">
        <defs>
          <pattern id="bo-hatch" width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <line x1="0" y1="0" x2="0" y2="8" stroke="color-mix(in oklch, var(--neutral) 40%, transparent)" strokeWidth="2" />
          </pattern>
        </defs>
        {ticks.map((v) => (
          <g key={v}>
            <line x1={P.l} x2={W - P.r} y1={y(v)} y2={y(v)} className={v === lo ? "td-grid" : "td-week"} />
            <text x={P.l - 8} y={y(v) + 4} textAnchor="end" className="td-tick">
              {v}
            </text>
          </g>
        ))}
        {gap > 3 && (
          <g>
            <rect x={gx + 4} y={P.t} width={Math.max(0, W - P.r - gx - 4)} height={H - P.t - P.b} fill="url(#bo-hatch)" rx={6} />
            {W - P.r - gx > 120 && (
              <text x={(gx + W - P.r) / 2} y={P.t + (H - P.t - P.b) / 2} textAnchor="middle" className="bo-gap-lbl">
                <tspan x={(gx + W - P.r) / 2}>{gap} days</tspan>
                <tspan x={(gx + W - P.r) / 2} dy={18} className="bo-gap-sub">
                  no weigh-in
                </tspan>
              </text>
            )}
          </g>
        )}
        {pts.map((p) => (
          <circle key={p.date} cx={x(p.date)} cy={y(p.lbs)} r={2.4} fill="var(--series-1)" opacity={0.45} />
        ))}
        {line.length === 1 && <circle cx={x(line[0].d)} cy={y(line[0].v)} r={3} fill="var(--series-1)" />}
        <motion.path d={line.map((p, i) => `${i && monthIdx(p.d) - monthIdx(line[i - 1].d) === 1 ? "L" : "M"}${x(p.d).toFixed(1)},${y(p.v).toFixed(1)}`).join("")} fill="none" stroke="var(--series-1)" strokeWidth={2} strokeLinejoin="round" initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ duration: 1.1, ease }} />
        <circle cx={gx} cy={y(last.lbs)} r={4.5} fill="var(--series-1)" className="td-enddot" />
        <text x={W - P.r - gx > 150 ? gx + 14 : gx - 8} y={P.t + 16} textAnchor={W - P.r - gx > 150 ? "start" : "end"} className="td-endlbl" style={{ fill: "var(--series-1)" }}>
          last {last.lbs.toFixed(1)} lb · {short(last.date)}
        </text>
        {months.map((m) => (
          <text key={m} x={x(`${m}-01`)} y={H - 8} textAnchor="middle" className="td-tick">
            {monthLbl(m)}
          </text>
        ))}
        <text x={W - P.r} y={H - 8} textAnchor="end" className="td-tick today">
          today
        </text>
      </svg>
          );
        }}
      </Fill>
      <p className="td-foot">Every weigh-in from the scale or the check-in, with the monthly mean as the line; it breaks where a month has none. The strap&apos;s profile weight is a setting, not a measurement, so it isn&apos;t drawn.</p>
    </div>
  );
}

const TAPE: { key: TapeField; label: string }[] = [
  { key: "waist_in", label: "Waist" },
  { key: "arm_in", label: "Arm, flexed" },
  { key: "thigh_in", label: "Mid-thigh" },
  { key: "chest_in", label: "Chest" },
];

/** Today's weigh-in and tape in one form; the weight goes through the check-in and its typo guard. */
export function LogReading() {
  const qc = useQueryClient();
  const tape = useTape();
  const w = useWeight();
  const [lbs, setLbs] = useState("");
  const [vals, setVals] = useState<Partial<Record<TapeField, string>>>({});
  const [force, setForce] = useState(false);
  const save = useMutation({
    mutationFn: async () => {
      const v = parseFloat(lbs);
      if (Number.isFinite(v) && v > 0) await api.checkinSubmit({ body_weight_kg: v / 2.20462, ...(force ? { force_weight: true } : {}) });
      const t = Object.fromEntries(
        Object.entries(vals)
          .filter(([, s]) => s)
          .map(([k, s]) => [k, Number(s)]),
      );
      if (Object.keys(t).length) await api.saveTape(t);
    },
    onSuccess: () => {
      setLbs("");
      setVals({});
      setForce(false);
      ["body-trend", "body-tape", "checkin-today", "daily-state"].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
    },
  });
  const lastW = w.data?.[w.data.length - 1];
  const typo = save.error instanceof Error && /off your last|force_weight/.test(save.error.message);
  const dirty = lbs.trim() !== "" || Object.values(vals).some(Boolean);
  const field = (key: string, label: string, unit: string, value: string, set: (v: string) => void, last: string) => (
    <label key={key} className="bo-field">
      <span className="td-label">{label}</span>
      <span className="bo-input">
        <input type="number" step="0.1" inputMode="decimal" value={value} onChange={(e) => set(e.target.value)} placeholder="–" />
        <em>{unit}</em>
      </span>
      <small>{last}</small>
    </label>
  );
  return (
    <div className="bo-log" id="log">
      <div className="bo-log-head">
        <span className="td-label">Log today&apos;s reading</span>
        <b>Weigh in first thing, fasted. Tape the waist at the navel, relaxed.</b>
      </div>
      <div className="bo-fields">
        {field("w", "Weight", "lb", lbs, setLbs, lastW ? `last ${lastW.lbs.toFixed(1)} · ${short(lastW.date)}` : "none yet")}
        {TAPE.map(({ key, label }) => {
          const l = tape.data?.[key];
          return field(key, label, "in", vals[key] ?? "", (v) => setVals((s) => ({ ...s, [key]: v })), l ? `last ${l.inches} · ${short(l.date)}` : "never taped");
        })}
      </div>
      <div className="bo-log-foot">
        <button className="btn btn-primary" onClick={() => save.mutate()} disabled={save.isPending || !dirty}>
          {save.isPending ? "Saving…" : "Save reading"}
        </button>
        {typo && !force && (
          <button className="btn btn-secondary" onClick={() => setForce(true)}>
            It&apos;s real, save anyway
          </button>
        )}
        {save.isError && <span className="bo-msg bad">{save.error instanceof Error ? save.error.message : "Not saved."}</span>}
        {save.isSuccess && <span className="bo-msg good">Saved. The ledger above updates on its own.</span>}
      </div>
    </div>
  );
}

// ── 04 The slow signals ─────────────────────────────────────────────────────

type SLane = { key: string; label: string; unit: string; kind: "line" | "bar" | "dot"; y: (number | null)[]; color: (v: number) => string; fmt: (v: number) => string; ref?: { v: number; label: string }; quiet: number; note?: string; run?: boolean };

const SIX = 182;

export function SlowSignals() {
  const st = useDailyState();
  const rhr = useRhr();
  const steps = useSteps();
  const vo2 = useVo2();
  const air = useAirway();
  const [ref, W] = useWidth(1200);
  const [hov, setHov] = useState<number | null>(null);
  const err = [st, rhr, steps, vo2, air].find((q) => q.isError);
  if (err || !st.data || !rhr.data || !steps.data || !vo2.data || !air.data)
    return (
      <div className="td-tape" ref={ref}>
        {err ? <Err what="the six-month tape" e={err.error} /> : <Skel h={460} />}
      </div>
    );
  const end = t(st.data.as_of);
  const dates = Array.from({ length: SIX }, (_, i) => new Date(end - (SIX - 1 - i) * DAY).toISOString().slice(0, 10));
  const pick = <T extends { date: string }>(rows: T[], f: (r: T) => number | null | undefined) => {
    const m = new Map(rows.map((r) => [r.date, f(r) ?? null]));
    return dates.map((d) => m.get(d) ?? null);
  };
  const lanes: SLane[] = [
    { key: "rhr", label: "Resting HR", unit: "bpm", kind: "line", y: pick(rhr.data, (r) => r.whoop), color: () => "var(--series-2)", fmt: (v) => v.toFixed(0), quiet: 3 },
    { key: "steps", label: "Steps", unit: "/day", kind: "bar", y: pick(steps.data, (r) => r.steps), color: (v) => (v >= 10_000 ? "var(--series-1)" : "var(--series-2)"), fmt: (v) => (v >= 1000 ? `${(v / 1000).toFixed(1)}k` : v.toFixed(0)), ref: { v: 10_000, label: "10k" }, quiet: 3, note: "import paused", run: true },
    { key: "vo2", label: "VO₂ max", unit: "ml/kg", kind: "dot", y: pick(vo2.data.filter((r) => r.source === "apple_watch"), (r) => r.vo2max), color: () => "var(--series-1)", fmt: (v) => v.toFixed(1), quiet: 21, note: "import paused" },
    { key: "spo2", label: "SpO₂, 7-night", unit: "%", kind: "line", y: pick(air.data.nights, (r) => r.spo2_7d), color: () => "var(--series-1)", fmt: (v) => v.toFixed(1), ref: { v: 95, label: "95" }, quiet: 4 },
    { key: "resp", label: "Breathing, 7-night", unit: "br/min", kind: "line", y: pick(air.data.nights, (r) => r.resp_7d), color: () => "var(--series-2)", fmt: (v) => v.toFixed(1), quiet: 4 },
  ];
  const P = { l: 168, r: 64, t: 6, b: 26 };
  const LH = 58;
  const GAP = 18;
  const height = P.t + lanes.length * LH + (lanes.length - 1) * GAP + P.b;
  const step = (W - P.l - P.r) / SIX;
  const cx = (i: number) => P.l + step * (i + 0.5);
  return (
    <div className="td-tape" ref={ref} onMouseLeave={() => setHov(null)}>
      <svg width={W} height={height} role="img" aria-label="Six months of resting heart rate, steps, VO2 max, overnight oxygen and breathing rate">
        <defs>
          <pattern id="bo-quiet" width="7" height="7" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <line x1="0" y1="0" x2="0" y2="7" stroke="oklch(1 0 0 / 0.07)" strokeWidth="2.5" />
          </pattern>
        </defs>
        {dates.map((d, i) => (d.slice(8) === "01" ? <line key={d} x1={cx(i) - step / 2} x2={cx(i) - step / 2} y1={P.t} y2={height - P.b + 4} className="td-week" /> : null))}
        {hov != null && <rect x={cx(hov) - Math.max(step, 3) / 2} y={P.t} width={Math.max(step, 3)} height={height - P.t - P.b} className="td-hovcol" />}
        {lanes.map((ln, li) => {
          const top = P.t + li * (LH + GAP);
          // A `run` lane reads only days inside a run (a neighbour each side), so neither a lone
          // snapshot nor the half-imported last day passes for a current count.
          const last = ln.y.reduce<number | null>((acc, v, i) => (v != null && (!ln.run || (ln.y[i - 1] != null && ln.y[i + 1] != null)) ? i : acc), null);
          const quietFrom = last == null ? 0 : SIX - 1 - last > ln.quiet ? last + 1 : null;
          const vals = [...ln.y, ...(ln.ref ? [ln.ref.v] : [])].filter((v): v is number => v != null);
          let lo = ln.kind === "bar" ? 0 : Math.min(...vals);
          let hi = Math.max(...vals);
          // Bars scale to the 95th percentile so one outlier day can't flatten the rest; it clips at the top.
          if (ln.kind === "bar" && vals.length > 20) hi = Math.max(ln.ref?.v ?? 0, [...vals].sort((a, b) => a - b)[Math.floor(vals.length * 0.95)] * 1.1);
          if (ln.kind !== "bar") {
            const pad = (hi - lo) * 0.14 || 1;
            lo -= pad;
            hi += pad;
          }
          const y = (v: number) => top + LH - ((v - lo) / (hi - lo || 1)) * LH;
          const shown = hov != null ? ln.y[hov] : last != null ? ln.y[last] : null;
          let path = "";
          ln.y.forEach((v, i) => {
            if (v == null) return;
            path += `${path && ln.y[i - 1] != null ? "L" : "M"}${cx(i).toFixed(1)},${y(v).toFixed(1)}`;
          });
          const bw = Math.max(1.5, step * 0.66);
          return (
            <g key={ln.key}>
              <line x1={P.l} x2={W - P.r} y1={top + LH} y2={top + LH} className="td-grid" />
              <text x={0} y={top + 14} className="td-lane-name">
                {ln.label}
              </text>
              <text x={0} y={top + 40} className="td-lane-val" style={{ fill: shown != null ? ln.color(shown) : "var(--text-faint)" }}>
                {shown == null ? "–" : ln.fmt(shown)}
                <tspan className="td-lane-unit"> {ln.unit}</tspan>
              </text>
              {quietFrom != null && (
                <g>
                  <rect x={cx(quietFrom) - step / 2} y={top} width={W - P.r - (cx(quietFrom) - step / 2)} height={LH} rx={6} fill="url(#bo-quiet)" />
                  <text x={cx(quietFrom) + 10} y={top + LH / 2 + 4} className="bo-quiet-lbl">
                    {last == null ? "no readings in six months" : `nothing since ${short(dates[last])}${ln.note ? ` · ${ln.note}` : ""}`}
                  </text>
                </g>
              )}
              {ln.ref && vals.length > 0 && <line x1={P.l} x2={W - P.r} y1={y(ln.ref.v)} y2={y(ln.ref.v)} className="td-ref" />}
              {ln.ref && vals.length > 0 && (
                <text x={W - P.r + 6} y={y(ln.ref.v) + 4} className="td-tick">
                  {ln.ref.label}
                </text>
              )}
              {ln.kind === "bar" &&
                ln.y.map((v, i) =>
                  v == null || v <= 0 || (ln.run && quietFrom != null && i >= quietFrom) ? null : <rect key={i} x={cx(i) - bw / 2} width={bw} y={Math.max(top, y(v))} height={Math.max(1.5, top + LH - Math.max(top, y(v)))} rx={1} fill={ln.color(v)} opacity={hov == null || hov === i ? 0.85 : 0.35} className="td-bar" />,
                )}
              {ln.kind === "line" && path && <motion.path d={path} fill="none" stroke={ln.color(0)} strokeWidth={1.75} strokeLinejoin="round" strokeLinecap="round" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.8, ease }} />}
              {ln.kind === "dot" && ln.y.map((v, i) => (v == null ? null : <circle key={i} cx={cx(i)} cy={y(v)} r={3} fill={ln.color(v)} />))}
              {last != null && ln.kind !== "bar" && <circle cx={cx(last)} cy={y(ln.y[last]!)} r={4} fill={ln.color(ln.y[last]!)} className="td-enddot" />}
              {hov != null && ln.y[hov] != null && ln.kind === "line" && <circle cx={cx(hov)} cy={y(ln.y[hov]!)} r={3.5} fill={ln.color(0)} />}
            </g>
          );
        })}
        {dates.map((d, i) =>
          d.slice(8) === "01" && i < SIX - 12 ? (
            <text key={d} x={cx(i)} y={height - 8} textAnchor="middle" className="td-tick">
              {monthLbl(d)}
            </text>
          ) : null,
        )}
        <text x={cx(SIX - 1)} y={height - 8} textAnchor="end" className="td-tick today">
          today
        </text>
        <rect
          x={P.l}
          y={P.t}
          width={Math.max(0, W - P.l - P.r)}
          height={height - P.t - P.b}
          fill="transparent"
          onMouseMove={(e) => {
            const r = e.currentTarget.getBoundingClientRect();
            const i = Math.floor(((e.clientX - r.left) / r.width) * SIX);
            setHov(i >= 0 && i < SIX ? i : null);
          }}
        />
      </svg>
      <span className="td-tape-day">{hov == null ? `Today · ${short(dates[SIX - 1])}` : new Date(dates[hov] + "T12:00:00").toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" })}</span>
      <p className="td-foot bo-tape-foot">
        Resting HR is the strap&apos;s. Steps and VO₂ max come from Apple Health, whose last import ran through mid-September; steps before May also counted phone and watch together, which is why the older record reads high. Oxygen and breathing are 7-night means of the strap&apos;s nightly averages, not an apnea count.
      </p>
    </div>
  );
}

/** A long panel kept folded until asked for, so it never sets the page's length. */
export function Fold({ label, title, sub, children, id }: { label: string; title: string; sub: string; children: ReactNode; id?: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className={`bo-fold${open ? " open" : ""}`} id={id}>
      <button className="bo-fold-head" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
        <span className="td-label">{label}</span>
        <b>{title}</b>
        <span className="bo-fold-sub">{sub}</span>
        <span className="bo-fold-go">{open ? "Close ↑" : "Open ↓"}</span>
      </button>
      {open && <div className="bo-fold-body">{children}</div>}
    </div>
  );
}

/** A labelled card wrapper for the reused log panels at the foot of the page. */
export function Sheet({ label, title, children, id }: { label: string; title: string; children: ReactNode; id?: string }) {
  return (
    <div className="bo-sheet" id={id}>
      <div className="bo-sheet-head">
        <span className="td-label">{label}</span>
        <b>{title}</b>
      </div>
      {children}
    </div>
  );
}
