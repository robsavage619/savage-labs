"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { api, type FeatureInfo, type NotebookEntry, type ResearchBelief, type ResearchHypothesis } from "@/lib/api";
import { Fill, useWidth } from "@/components/kit";

/**
 * The research floor: the Lab redrawn as a team at work. Forecast desk first
 * (can the team predict you?), then what it believes as probability curves,
 * the questions moving through review, the agents' own back-and-forth, where
 * the forecast is wrong, and what the team can see. Every value renders as
 * the research routes serve it.
 */

const STALE = 5 * 60 * 1000;
const ease = [0.22, 1, 0.36, 1] as const;
const signed = (v: number, d = 1) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(d)}`;
const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const short = (iso: string) => `${MON[+iso.slice(5, 7) - 1]} ${+iso.slice(8, 10)}`;
const when = (iso: string) => new Date(iso).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });

const useBeliefs = () => useQuery({ queryKey: ["research-beliefs"], queryFn: api.researchBeliefs, staleTime: STALE });
const useHyps = () => useQuery({ queryKey: ["research-hypotheses"], queryFn: api.researchHypotheses, staleTime: STALE });
const useNotes = () => useQuery({ queryKey: ["research-notebook", 120], queryFn: () => api.researchNotebook(120), staleTime: STALE });

const Skel = ({ h }: { h: number }) => <div className="ts-skeleton" style={{ height: h }} />;

// ── Masthead and roster ─────────────────────────────────────────────────────

const ROLES = [
  { key: "specialists", name: "Specialists", does: "Four researchers chasing their own leads", cadence: "One a day, Mon–Thu", authors: ["hypertrophy", "recovery", "conditioning", "metabolic", "analyst"] },
  { key: "methodologist", name: "Methodologist", does: "Reviews every proposal and new measure blind", cadence: "After each specialist", authors: ["methodologist"] },
  { key: "forecaster", name: "Forecaster", does: "Bets on each morning before it happens", cadence: "Nightly 04:50", authors: ["forecaster"] },
  { key: "runner", name: "Runner", does: "Re-runs every live question", cadence: "Nightly 04:50", authors: ["nightly", "runner"] },
] as const;

export function Masthead() {
  const notes = useNotes();
  const hyps = useHyps();
  const beliefs = useBeliefs();
  const last = (authors: readonly string[]) => notes.data?.find((n) => authors.includes(n.author.toLowerCase()))?.written_at;
  const h = hyps.data ?? [];
  const stats = [
    { v: beliefs.data?.length ?? "–", l: "beliefs held" },
    { v: h.filter((x) => x.status === "active").length, l: "questions live" },
    { v: h.filter((x) => x.status === "proposed").length, l: "awaiting review" },
    { v: h.filter((x) => x.result?.verdict === "supported").length, l: "supported" },
    { v: h.filter((x) => x.status === "rejected").length, l: "rejected blind" },
  ];
  return (
    <header className="lf-mast">
      <div className="lf-mast-l">
        <span className="lf-eyebrow">The Lab · research floor</span>
        <h1>Learning you, one question at a time.</h1>
        <p>A four-agent research team works your data every week: it proposes questions, reviews them blind, runs what survives, and is graded on whether it can predict your next morning.</p>
        <div className="lf-stats">
          {stats.map((s) => (
            <div key={s.l}>
              <b>{s.v}</b>
              <span>{s.l}</span>
            </div>
          ))}
        </div>
      </div>
      <ol className="lf-roster">
        {ROLES.map((r, i) => {
          const at = last(r.authors);
          return (
            <motion.li key={r.key} initial={{ opacity: 0.001, x: 16 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: 0.08 * i, duration: 0.5, ease }}>
              <span className={`lf-av lf-av-${r.key}`}>{r.name[0]}</span>
              <div>
                <b>{r.name}</b>
                <span>{r.does}</span>
              </div>
              <small>
                <i className={at ? "on" : ""} />
                {at ? `last ${when(at)}` : "not yet run"}
                <em>{r.cadence}</em>
              </small>
            </motion.li>
          );
        })}
      </ol>
    </header>
  );
}

const gauss = (x: number, m: number, s: number) => Math.exp(-0.5 * ((x - m) / s) ** 2) / s;

// ── Forecast desk ───────────────────────────────────────────────────────────

const HRV = "lnhrv_dev_pct";
const STRENGTH = "strength_emphasis_pct14";

/** Lead with the subject's goal: strength once it has a scored forecast, HRV until then. */
export function useDefaultTarget(): string {
  const s = useQuery({ queryKey: ["research-forecast", STRENGTH], queryFn: () => api.researchForecast(STRENGTH), staleTime: STALE });
  return s.data?.backtest?.skill != null ? STRENGTH : HRV;
}
/** Copy and axis floors per forecast target; the server owns which targets exist. */
const DESK: Record<string, { tab: string; points: string; subject: string; bet: string; tag: string; sub: string; floor: number; ext: number; base: string; foot: string }> = {
  [HRV]: {
    tab: "HRV",
    points: "mornings",
    subject: "your HRV",
    bet: "Tomorrow's bet",
    tag: "tomorrow",
    sub: "HRV against your baseline",
    floor: 25,
    ext: 50,
    base: "baseline",
    foot: "Logged for real at 04:50, before the reading exists, then scored when it lands.",
  },
  strength_emphasis_pct14: {
    tab: "Strength",
    points: "weeks",
    subject: "your biceps and glutes strength",
    bet: "Next week's bet",
    tag: "next week",
    sub: "Biceps and glutes e1RM, last 14 days vs the 14 before",
    floor: 6,
    ext: 15,
    base: "no change",
    foot: "A week-ahead bet, scored once that week is over. Only beliefs that act a week or more ahead can move it.",
  },
};
const deskOf = (metric: string, label?: string) => DESK[metric] ?? { ...DESK[HRV], tab: label ?? metric, subject: label ?? metric, sub: label ?? metric, tag: "next" };

function Ribbon({ series, bet, miss, height, floor, tag }: { series: { date: string; actual: number; predicted: number }[]; bet: { date: string; v: number } | null; miss: number; height: number; floor: number; tag: string }) {
  const [ref, W] = useWidth();
  const [hov, setHov] = useState<number | null>(null);
  const pts = series.slice(-90);
  const n = pts.length + (bet ? 2 : 0);
  const P = { l: 44, r: 16, t: 14, b: 26 };
  const lim = Math.min(60, Math.max(floor, ...pts.map((p) => Math.abs(p.actual))));
  const x = (i: number) => P.l + (i / Math.max(1, n - 1)) * (W - P.l - P.r);
  const y = (v: number) => P.t + ((lim - Math.max(-lim, Math.min(lim, v))) / (2 * lim)) * (height - P.t - P.b);
  const line = pts.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.predicted).toFixed(1)}`).join("");
  const band = `${pts.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.predicted + miss).toFixed(1)}`).join("")}${pts
    .map((p, i) => `L${x(pts.length - 1 - i).toFixed(1)},${y(pts[pts.length - 1 - i].predicted - miss).toFixed(1)}`)
    .join("")}Z`;
  const bx = x(n - 1);
  const ticks = [-lim, -lim / 2, 0, lim / 2, lim].map((t) => Math.round(t));
  const hp = hov != null ? pts[hov] : null;
  return (
    <div ref={ref} className="lf-ribbon" style={{ height }} onMouseLeave={() => setHov(null)}>
      <svg width={W} height={height}>
        <defs>
          <linearGradient id="lf-band" x1="0" x2="1">
            <stop offset="0" stopColor="var(--series-1)" stopOpacity="0.02" />
            <stop offset="1" stopColor="var(--series-1)" stopOpacity="0.16" />
          </linearGradient>
        </defs>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={P.l} x2={W - P.r} y1={y(t)} y2={y(t)} className={t === 0 ? "lf-axis0" : "lf-grid"} />
            <text x={P.l - 8} y={y(t) + 4} textAnchor="end" className="lf-tick">
              {t > 0 ? "+" : ""}
              {t}%
            </text>
          </g>
        ))}
        <path d={band} fill="url(#lf-band)" />
        {pts.map((p, i) => (
          <circle key={p.date} cx={x(i)} cy={y(p.actual)} r={hov === i ? 4 : 2.4} className={Math.abs(p.actual - p.predicted) > miss ? "lf-dot out" : "lf-dot"} />
        ))}
        <motion.path d={line} fill="none" stroke="var(--series-1)" strokeWidth={2} initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ duration: 1.4, ease }} />
        {bet && (
          <g>
            <line x1={x(pts.length - 1)} x2={bx} y1={y(pts[pts.length - 1]?.predicted ?? 0)} y2={y(bet.v)} stroke="var(--series-1)" strokeDasharray="3 4" strokeWidth={1.5} />
            <line x1={bx} x2={bx} y1={y(bet.v + miss)} y2={y(bet.v - miss)} className="lf-betbar" />
            <motion.circle cx={bx} cy={y(bet.v)} r={6} className="lf-bet" initial={{ scale: 0 }} animate={{ scale: [0, 1.4, 1] }} transition={{ delay: 1.2, duration: 0.6 }} />
            <text x={bx - 10} y={y(bet.v) - 12} textAnchor="end" className="lf-betlabel">
              {tag}
            </text>
          </g>
        )}
        {[0, Math.floor(pts.length / 2), pts.length - 1].filter((i) => pts[i]).map((i) => (
          <text key={i} x={x(i)} y={height - 6} textAnchor="middle" className="lf-tick">
            {short(pts[i].date)}
          </text>
        ))}
        <rect
          x={P.l}
          y={P.t}
          width={Math.max(0, W - P.l - P.r)}
          height={height - P.t - P.b}
          fill="transparent"
          onMouseMove={(e) => {
            const r = (e.currentTarget as SVGRectElement).getBoundingClientRect();
            const i = Math.round(((e.clientX - r.left) / r.width) * (n - 1));
            setHov(i >= 0 && i < pts.length ? i : null);
          }}
        />
      </svg>
      {hp && (
        <div className="lf-tip" style={{ left: Math.min(x(hov!) + 12, W - 170), top: 8 }}>
          <b>{short(hp.date)}</b>
          <span>
            Forecast <em>{signed(hp.predicted)}%</em>
          </span>
          <span>
            Actual <em>{signed(hp.actual)}%</em>
          </span>
        </div>
      )}
    </div>
  );
}

export function ForecastDesk() {
  const fallback = useDefaultTarget();
  const [picked, setMetric] = useState<string | null>(null);
  const metric = picked ?? fallback;
  const arg = metric === HRV ? undefined : metric;
  const f = useQuery({ queryKey: ["research-forecast", metric], queryFn: () => api.researchForecast(arg), staleTime: STALE });
  const p = useQuery({ queryKey: ["research-preview", metric], queryFn: () => api.researchPreview(arg), staleTime: STALE });
  const [deskRef, deskW] = useWidth(900);
  const targets = f.data?.targets ?? [];
  const cfg = deskOf(metric, f.data?.target?.label);
  const switcher =
    targets.length > 1 ? (
      <div className="lf-switch" role="tablist" aria-label="Forecast target">
        {targets.map((t) => (
          <button key={t.metric} role="tab" aria-selected={metric === t.metric} title={t.label} className={metric === t.metric ? "on" : ""} onClick={() => setMetric(t.metric)}>
            {deskOf(t.metric, t.label).tab}
          </button>
        ))}
      </div>
    ) : null;
  if (!f.data || !p.data) return <Skel h={420} />;
  const bt = f.data.backtest;
  if (!bt || bt.skill == null) {
    return (
      <div className="lf-desk lf-desk-none">
        <div className="lf-desk-chart">
          {switcher}
          <span className="lf-label">No forecast skill to show yet</span>
          <p className="lf-none-why">
            {bt?.reason ?? "The forecaster has not backtested this target yet."}
            {bt ? ` ${bt.n} ${cfg.points} were scorable.` : ""} The lab won&apos;t claim skill it hasn&apos;t earned on {cfg.points} it never saw.
          </p>
        </div>
      </div>
    );
  }
  const miss = bt.rmse_lab ?? cfg.floor;
  const max = Math.max(1, ...p.data.terms.map((t) => Math.abs(t.contribution)));
  const live = p.data.terms.filter((t) => t.contribution !== 0);
  const quiet = p.data.terms.filter((t) => t.contribution === 0);
  return (
    <div className="lf-desk" ref={deskRef}>
      <div className="lf-desk-chart">
        {switcher}
        <div className="lf-desk-top">
          <div>
            <span className="lf-label">Forecast skill on {cfg.points} it never saw</span>
            <b className={`lf-big ${bt.skill > 0 ? "up" : "down"}`}>{signed(bt.skill * 100, 1)}%</b>
          </div>
          <p>
            Better than guessing &quot;{cfg.base}&quot; across {bt.n} {cfg.points}. The line is the lab&apos;s forecast, the band its typical miss of ±{miss.toFixed(miss < 10 ? 1 : 0)}%, the dots what {cfg.subject} actually did; copper dots landed outside the band.
          </p>
        </div>
        <Fill min={deskW < 760 ? 240 : 280}>{(h) => <Ribbon series={bt.series} bet={{ date: p.data!.target_date, v: p.data!.predicted }} miss={miss} height={h} floor={cfg.floor} tag={cfg.tag} />}</Fill>
      </div>
      <div className="lf-bet-card">
        <span className="lf-label">
          {cfg.bet} · {short(p.data.target_date)}
        </span>
        <b className="lf-bet-v">{signed(p.data.predicted)}%</b>
        <span className="lf-bet-sub">
          {cfg.sub}, give or take {miss.toFixed(miss < 10 ? 1 : 0)}%
        </span>
        <Fill min={110}>{(h) => <BetCurve v={p.data!.predicted} miss={miss} height={h} ext={cfg.ext} base={cfg.base} />}</Fill>
        <div className="lf-drivers">
          <span className="lf-label">Why</span>
          {live.length === 0 && <p className="lf-quiet">No belief applies to the data so far, so the lab bets on {cfg.base}.</p>}
          {live.map((t) => (
            <div key={t.belief_id} className="lf-drv">
              <span>{t.claim}</span>
              <span className="lf-drv-track">
                <span className="lf-drv-mid" />
                <motion.i
                  initial={{ scaleX: 0 }}
                  animate={{ scaleX: 1 }}
                  transition={{ delay: 0.4, duration: 0.8, ease }}
                  style={t.contribution >= 0 ? { left: "50%", width: `${(t.contribution / max) * 50}%`, transformOrigin: "left" } : { right: "50%", width: `${(-t.contribution / max) * 50}%`, transformOrigin: "right" }}
                />
              </span>
              <b>{signed(t.contribution)}%</b>
            </div>
          ))}
          {quiet.length > 0 && <p className="lf-quiet">Silent today: {quiet.map((t) => t.claim.toLowerCase()).join("; ")}.</p>}
        </div>
        <p className="lf-foot">{cfg.foot}</p>
      </div>
    </div>
  );
}

/** Where tomorrow's reading will probably land: the bet as a distribution, with
 *  the middle half and 80% of outcomes shaded. */
function BetCurve({ v, miss, height, ext, base }: { v: number; miss: number; height: number; ext: number; base: string }) {
  const [ref, W] = useWidth(320);
  const X = (x: number) => ((x + ext) / (2 * ext)) * W;
  const sh = height - 20; // the caption takes the rest
  const H = sh - 16;
  const xs = Array.from({ length: 161 }, (_, i) => -ext + (i / 160) * 2 * ext);
  const pk = gauss(v, v, miss);
  const Y = (x: number) => H - (gauss(x, v, miss) / pk) * (H - 8);
  const area = (lo: number, hi: number) => {
    const seg = xs.filter((x) => x >= lo && x <= hi);
    return `M${X(lo)},${H}${seg.map((x) => `L${X(x).toFixed(1)},${Y(x).toFixed(1)}`).join("")}L${X(hi)},${H}Z`;
  };
  const q50 = 0.674 * miss;
  const q80 = 1.2816 * miss;
  return (
    <div ref={ref} className="lf-betcurve">
      <svg width={W} height={sh}>
        <path d={area(v - q80, v + q80)} className="lf-b80" />
        <path d={area(v - q50, v + q50)} className="lf-b50" />
        <path d={xs.map((x, i) => `${i ? "L" : "M"}${X(x).toFixed(1)},${Y(x).toFixed(1)}`).join("")} className="lf-bline" />
        <line x1={X(0)} x2={X(0)} y1={0} y2={H} className="lf-axis0" />
        <text x={X(0)} y={sh - 3} textAnchor="middle" className="lf-tick">{base}</text>
        <text x={X(-ext) + 2} y={sh - 3} className="lf-tick">−{ext}%</text>
        <text x={X(ext) - 2} y={sh - 3} textAnchor="end" className="lf-tick">+{ext}%</text>
      </svg>
      <span className="lf-betcap">Half of bets like this land in {signed(v - q50, 0)} to {signed(v + q50, 0)}%, eight in ten in {signed(v - q80, 0)} to {signed(v + q80, 0)}%.</span>
    </div>
  );
}

// ── Belief lenses ───────────────────────────────────────────────────────────


function useMorph(target: { m: number; s: number }, from: { m: number; s: number }) {
  const [v, setV] = useState(from);
  const raf = useRef(0);
  useEffect(() => {
    const t0 = performance.now();
    const step = (t: number) => {
      const k = Math.min(1, (t - t0) / 1100);
      const e = 1 - (1 - k) ** 3;
      setV({ m: from.m + (target.m - from.m) * e, s: from.s + (target.s - from.s) * e });
      if (k < 1) raf.current = requestAnimationFrame(step);
    };
    raf.current = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf.current);
  }, [target.m, target.s, from.m, from.s]);
  return v;
}

/** A value in a belief's own unit: "+3.0%", "+0.40 kg". */
const inUnit = (v: number, unit: string | null, ext: number) => {
  const s = signed(v, ext < 3 ? 2 : 1);
  return unit === "%" ? `${s}%` : unit ? `${s} ${unit}` : s;
};
const tickOf = (v: number, unit: string | null) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v)}${unit === "%" ? "%" : ""}`;

function Lens({ b, ext }: { b: ResearchBelief; ext: number }) {
  const [ref, W] = useWidth(240);
  const H = 96;
  const post = useMorph({ m: b.post_mean, s: b.post_sd }, { m: b.prior_mean, s: b.prior_sd });
  const xs = Array.from({ length: 121 }, (_, i) => -ext + (i / 120) * 2 * ext);
  const peak = gauss(0, 0, Math.min(b.post_sd, b.prior_sd));
  const X = (v: number) => (v + ext) / (2 * ext) * W;
  const Y = (d: number) => H - 4 - (d / peak) * (H - 12);
  const path = (m: number, s: number) => xs.map((v, i) => `${i ? "L" : "M"}${X(v).toFixed(1)},${Y(gauss(v, m, s)).toFixed(1)}`).join("");
  const lo = b.post_mean - 1.645 * b.post_sd;
  const hi = b.post_mean + 1.645 * b.post_sd;
  const clear = lo > 0 || hi < 0;
  const g = b.forecast_gain;
  const verdict = g == null ? { t: "not in the forecast", c: "" } : g > 0.0005 ? { t: "sharpens the forecast", c: "up" } : g < -0.0005 ? { t: "hurts the forecast · demote?", c: "down" } : { t: "no effect on forecast", c: "" };
  return (
    <motion.article className="lf-lens" whileHover={{ y: -3 }} transition={{ duration: 0.2 }}>
      <header>
        <h3>{b.claim}</h3>
        <span className={`lf-chip ${verdict.c}`}>{verdict.t}</span>
      </header>
      <div ref={ref} className="lf-curve">
        <svg width={W} height={H}>
          <defs>
            <linearGradient id={`lf-g-${b.id}`} x1="0" x2="0" y1="0" y2="1">
              <stop offset="0" stopColor={clear ? (b.post_mean < 0 ? "var(--series-2)" : "var(--series-1)") : "var(--text-dim)"} stopOpacity="0.55" />
              <stop offset="1" stopColor={clear ? (b.post_mean < 0 ? "var(--series-2)" : "var(--series-1)") : "var(--text-dim)"} stopOpacity="0" />
            </linearGradient>
          </defs>
          <line x1={X(0)} x2={X(0)} y1={0} y2={H} className="lf-axis0" />
          <text x={2} y={11} className="lf-tick">{tickOf(-ext, b.unit)}</text>
          <text x={W - 2} y={11} textAnchor="end" className="lf-tick">{tickOf(ext, b.unit)}</text>
          <path d={path(b.prior_mean, b.prior_sd)} fill="none" className="lf-prior" />
          <path d={`${path(post.m, post.s)}L${W},${H}L0,${H}Z`} fill={`url(#lf-g-${b.id})`} />
          <path d={path(post.m, post.s)} fill="none" className={`lf-post${clear ? (b.post_mean < 0 ? " neg" : " pos") : ""}`} />
        </svg>
      </div>
      <footer>
        <div>
          <b>{inUnit(b.post_mean, b.unit, ext)}</b>
          <span>
            90%: {inUnit(lo, b.unit, ext)} to {inUnit(hi, b.unit, ext)}
          </span>
        </div>
        <div className="lf-learned">
          <svg width="34" height="34" viewBox="0 0 34 34">
            <circle cx="17" cy="17" r="14" className="lf-ring-bg" />
            <motion.circle cx="17" cy="17" r="14" className="lf-ring" initial={{ pathLength: 0 }} animate={{ pathLength: Math.max(0, b.learned ?? 0) }} transition={{ duration: 1.1, ease }} transform="rotate(-90 17 17)" />
          </svg>
          <span>
            {Math.round(Math.max(0, b.learned ?? 0) * 100)}%<small>learned</small>
          </span>
        </div>
      </footer>
      <p className="lf-src" title={b.prior_source}>
        Started from {b.prior_source.split(";")[0].split("(")[0].trim()} · {b.n_results} result{b.n_results === 1 ? "" : "s"}
      </p>
    </motion.article>
  );
}

export function BeliefLenses() {
  const q = useBeliefs();
  if (!q.data) return <Skel h={260} />;
  const rows = [...q.data].sort((a, b) => (b.learned ?? 0) - (a.learned ?? 0));
  // Beliefs in the same unit share the widest of their scales, so their curves compare at a glance.
  const ext = new Map<string, number>();
  for (const b of rows) ext.set(b.unit ?? "", Math.max(ext.get(b.unit ?? "") ?? 0, b.scale));
  return (
    <>
      <div className="lf-lenses">
        {rows.map((b) => (
          <Lens key={b.id} b={b} ext={ext.get(b.unit ?? "") ?? b.scale} />
        ))}
      </div>
      <p className="lf-foot">
        Each curve is a belief about how much a thing moves its outcome, drawn in that outcome&apos;s own unit on a scale symmetric about zero; beliefs in the same unit share a scale. The dashed curve is where the literature started the team; the filled one is where your data has moved it. Narrow and away from the centre line means the team is sure.
      </p>
    </>
  );
}

// ── Pipeline ────────────────────────────────────────────────────────────────

type Stage = "proposed" | "running" | "answered" | "rejected";
const stageOf = (h: ResearchHypothesis): Stage =>
  h.status === "proposed" ? "proposed" : h.status === "rejected" || h.status === "retired" ? "rejected" : ["supported", "against", "ruled_out"].includes(h.result?.verdict ?? "") ? "answered" : "running";
const STAGES: { key: Stage; label: string }[] = [
  { key: "proposed", label: "Awaiting review" },
  { key: "running", label: "Running" },
  { key: "answered", label: "Answered" },
  { key: "rejected", label: "Rejected blind" },
];
const VERDICT: Record<string, string> = { supported: "supported", against: "runs the other way", ruled_out: "ruled out", inconclusive: "not clear yet", insufficient: "too few days" };

function QuestionCard({ h }: { h: ResearchHypothesis }) {
  const st = stageOf(h);
  const r = h.result;
  const need = h.power?.needed_per_arm ?? 0;
  const have = r ? Math.min(r.n_a, r.n_b) : 0;
  const prog = need ? Math.min(1, have / need) : 0;
  const unit = h.spec.unit === "week" ? "weeks" : "days";
  return (
    <motion.article layout className={`lf-q lf-q-${st}`} initial={{ opacity: 0.001, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4, ease }}>
      <div className="lf-q-ring">
        <svg width="46" height="46" viewBox="0 0 46 46">
          <circle cx="23" cy="23" r="19" className="lf-ring-bg" />
          <motion.circle cx="23" cy="23" r="19" className="lf-ring" initial={{ pathLength: 0 }} animate={{ pathLength: st === "rejected" ? 0 : prog }} transition={{ duration: 1, ease }} transform="rotate(-90 23 23)" />
        </svg>
        <span>{st === "rejected" ? "—" : `${Math.round(prog * 100)}%`}</span>
      </div>
      <div className="lf-q-body">
        <h4>{h.question}</h4>
        <p>
          {r?.effect != null && r.ci_low != null && r.ci_high != null && st !== "rejected" ? (
            <>
              <b>{signed(r.effect)}%</b> ({signed(r.ci_low)} to {signed(r.ci_high)}) · {VERDICT[r.verdict] ?? r.verdict} ·{" "}
            </>
          ) : null}
          {need ? `${have}/${need} ${unit} a side` : "unsized"} · value {h.value_score?.toFixed(2) ?? "–"} · {h.author}
        </p>
      </div>
    </motion.article>
  );
}

export function Pipeline() {
  const q = useHyps();
  const [stage, setStage] = useState<Stage | "all">("all");
  if (!q.data) return <Skel h={300} />;
  const counts = Object.fromEntries(STAGES.map((s) => [s.key, q.data.filter((h) => stageOf(h) === s.key).length])) as Record<Stage, number>;
  const shown = q.data.filter((h) => stage === "all" || stageOf(h) === stage).sort((a, b) => STAGES.findIndex((s) => s.key === stageOf(a)) - STAGES.findIndex((s) => s.key === stageOf(b)));
  return (
    <div className="lf-pipe">
      <div className="lf-line" role="tablist" aria-label="Filter questions by stage">
        {STAGES.map((s, i) => (
          <button key={s.key} role="tab" aria-selected={stage === s.key} className={`lf-stop lf-stop-${s.key}${stage === s.key ? " on" : ""}`} onClick={() => setStage(stage === s.key ? "all" : s.key)}>
            <span className="lf-node">{counts[s.key]}</span>
            <span>{s.label}</span>
            {i < STAGES.length - 1 && <i className="lf-rail" />}
          </button>
        ))}
      </div>
      <div className="lf-qs">
        {shown.map((h) => (
          <QuestionCard key={h.slug} h={h} />
        ))}
      </div>
      <p className="lf-foot">The ring fills toward the days each question needs to see its effect. Click a stage to filter.</p>
    </div>
  );
}

// ── Conversation ────────────────────────────────────────────────────────────

const SPECIALISTS = ["hypertrophy", "recovery", "conditioning", "metabolic"] as const;

const roleOf = (author: string) => {
  const a = author.toLowerCase();
  const sp = SPECIALISTS.find((k) => a.includes(k));
  if (sp) return sp;
  if (a.includes("method")) return "methodologist";
  if (a.includes("forecast")) return "forecaster";
  if (a.includes("night") || a.includes("runner")) return "runner";
  return "analyst";
};

export function Threads() {
  const notes = useNotes();
  const hyps = useHyps();
  const [open, setOpen] = useState<string | null>(null);
  const threads = useMemo(() => {
    if (!notes.data || !hyps.data) return [];
    const byRef = new Map<string, NotebookEntry[]>();
    for (const n of notes.data) if (n.ref) byRef.set(n.ref, [...(byRef.get(n.ref) ?? []), n]);
    return hyps.data
      .filter((h) => byRef.has(h.id) && (byRef.get(h.id)!.length > 1 || h.status !== "active"))
      .map((h) => ({ h, entries: [...byRef.get(h.id)!].reverse() }))
      .sort((a, b) => b.entries[b.entries.length - 1].written_at.localeCompare(a.entries[a.entries.length - 1].written_at))
      .slice(0, 4);
  }, [notes.data, hyps.data]);
  if (!notes.data || !hyps.data) return <Skel h={320} />;
  return (
    <div className="lf-threads">
      {threads.map(({ h, entries }) => {
        const isOpen = open === h.id;
        return (
          <article key={h.id} className="lf-thread">
            <header>
              <span className={`lf-status lf-q-${stageOf(h)}`}>{STAGES.find((s) => s.key === stageOf(h))?.label}</span>
              <h4>{h.question}</h4>
            </header>
            <ol>
              {entries.map((e) => (
                <li key={e.id} className={`lf-msg lf-msg-${roleOf(e.author)}`}>
                  <span className={`lf-av lf-av-${roleOf(e.author)}`}>{roleOf(e.author)[0].toUpperCase()}</span>
                  <div>
                    <div className="lf-msg-top">
                      <b>{roleOf(e.author)}</b>
                      <span>{e.kind}</span>
                      <time>{when(e.written_at)}</time>
                    </div>
                    <p className={isOpen ? "" : "clamp"}>{e.body || e.title}</p>
                  </div>
                </li>
              ))}
            </ol>
            <button className="lf-more no-tactile" onClick={() => setOpen(isOpen ? null : h.id)}>
              {isOpen ? "Show less" : "Read the full exchange"}
            </button>
          </article>
        );
      })}
      {threads.length === 0 && <p className="lf-quiet">No exchanges yet. The first weekly cycle runs Sunday at 1 PM.</p>}
    </div>
  );
}

// ── Where the lab is wrong ──────────────────────────────────────────────────

export function Misses() {
  const metric = useDefaultTarget();
  const q = useQuery({ queryKey: ["research-misses", metric], queryFn: () => api.researchMisses(metric === HRV ? undefined : metric), staleTime: STALE });
  if (!q.data) return <Skel h={300} />;
  const wd = q.data.by_weekday ?? [];
  const worst = (q.data.worst_mornings ?? []).slice(0, 6);
  const m = Math.max(4, ...wd.map((d) => Math.abs(d.mean_residual)));
  const wm = Math.max(1, ...worst.map((w) => Math.abs(w.residual)));
  const ctx = (w: Record<string, number | string | null>) =>
    [
      w.sleep_hours != null && `${w.sleep_hours}h in bed`,
      w.resp_rate != null && `${w.resp_rate} breaths/min`,
      w.strain == null ? "no strain logged" : `strain ${w.strain}`,
      w.steps != null && `${Math.round(Number(w.steps)).toLocaleString()} steps`,
    ].filter(Boolean) as string[];
  return (
    <div className="lf-misses">
      <div className="lf-week">
        <span className="lf-label">Average miss by morning</span>
        <div className="lf-days">
          {wd.map((d) => {
            const k = Math.min(1, Math.abs(d.mean_residual) / m);
            return (
              <div key={d.day} className="lf-day">
                <b>{signed(d.mean_residual)}%</b>
                <span className="lf-dcol">
                  <span className="lf-dmid" />
                  <motion.i
                    initial={{ scaleY: 0 }}
                    whileInView={{ scaleY: 1 }}
                    viewport={{ once: true }}
                    transition={{ duration: 0.7, ease }}
                    style={
                      d.mean_residual >= 0
                        ? { bottom: "50%", height: `${k * 50}%`, background: "var(--series-1)", transformOrigin: "bottom" }
                        : { top: "50%", height: `${k * 50}%`, background: "var(--series-2)", transformOrigin: "top" }
                    }
                  />
                </span>
                <span>{d.day}</span>
                <small>{d.n} mornings</small>
              </div>
            );
          })}
        </div>
        <p className="lf-foot">
          Positive: your HRV came in higher than the lab expected. The weekend pattern is the open question the analyst keeps circling.
          {q.data.last_30_days_bias != null && ` Over the last 30 days the forecast has run ${Math.abs(q.data.last_30_days_bias).toFixed(1)}% too ${q.data.last_30_days_bias < 0 ? "high" : "low"}.`}
        </p>
      </div>
      <div className="lf-worst">
        <span className="lf-label">The mornings it got most wrong</span>
        {worst.map((w) => (
          <div key={w.date} className="lf-wrow">
            <time>{short(w.date)}</time>
            <span className="lf-wbar">
              <i style={{ width: `${(Math.abs(w.residual) / wm) * 100}%`, background: w.residual < 0 ? "var(--series-2)" : "var(--series-1)" }} />
            </span>
            <b>{signed(w.residual, 0)}%</b>
            <div className="lf-ctx">
              {ctx(w).map((c) => (
                <span key={c}>{c}</span>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── What the team can see ───────────────────────────────────────────────────

export function Coverage() {
  const q = useQuery({ queryKey: ["research-features"], queryFn: api.researchFeatures, staleTime: STALE });
  const [ref, W] = useWidth(900);
  if (!q.data) return <Skel h={300} />;
  const rows = q.data.filter((f) => f.first && !f.name.startsWith("journal:") && f.name !== "weekend").sort((a, b) => a.first!.localeCompare(b.first!));
  const t0 = new Date("2014-01-01").getTime();
  // The axis ends at the newest reading, not the wall clock, so render stays pure.
  const end = rows.reduce((m, f) => (f.last! > m ? f.last! : m), "2014-01-02");
  const t1 = new Date(end).getTime();
  const X = (iso: string) => ((new Date(iso).getTime() - t0) / (t1 - t0)) * 100;
  const years = Array.from({ length: +end.slice(0, 4) - 2013 }, (_, i) => 2014 + i).filter((y) => W > 700 || y % 2 === 0);
  const tip = (f: FeatureInfo) => `${f.label}: ${f.days.toLocaleString()} days, ${short(f.first!)} ${f.first!.slice(0, 4)} to ${short(f.last!)} ${f.last!.slice(0, 4)}`;
  return (
    <div className="lf-cov" ref={ref}>
      <div className="lf-years">
        {years.map((y) => (
          <span key={y} style={{ left: `${X(`${y}-01-01`)}%` }}>
            {y}
          </span>
        ))}
      </div>
      {rows.map((f, i) => (
        <div key={f.name} className={`lf-crow${f.stale ? " stale" : ""}`} title={tip(f)}>
          <span className="lf-cname">{f.label}</span>
          <span className="lf-ctrack">
            <motion.i
              initial={{ scaleX: 0 }}
              whileInView={{ scaleX: 1 }}
              viewport={{ once: true }}
              transition={{ delay: 0.02 * i, duration: 0.7, ease }}
              style={{ left: `${X(f.first!)}%`, width: `${X(f.last!) - X(f.first!)}%` }}
            />
          </span>
          <span className="lf-cdays">{f.stale ? `quiet since ${short(f.last!)}` : `${f.days.toLocaleString()} days`}</span>
        </div>
      ))}
      <p className="lf-foot">Every stream the team can study, from the first reading to the latest. Copper streams have gone quiet; questions on them can&apos;t run until they resume.</p>
    </div>
  );
}
