"use client";

import { createContext, useContext, useId, useLayoutEffect, useRef, useState, useSyncExternalStore, type ReactNode } from "react";
import { motion } from "framer-motion";
import { ExploreButton, type MetricKey } from "@/components/metric-explorer";
import { ErrorBoundary } from "@/components/error-boundary";
import type { Span } from "@/lib/sections";

/**
 * The visual kit the approved overhaul mockup was built from: a page question,
 * numbered sections, flat panels with an open reading guide, and SVG charts
 * drawn at their container's true pixel width (never a stretched viewBox, so
 * text stays 11px and lines stay 2px at any size).
 *
 * Exit animations are deliberately absent: AnimatePresence never completes an
 * exit under React 19 StrictMode.
 */

export const ease = [0.22, 1, 0.36, 1] as const;
export const stagger = { hidden: {}, show: { transition: { staggerChildren: 0.06 } } };
export const rise = { hidden: { opacity: 0.001, y: 14 }, show: { opacity: 1, y: 0, transition: { duration: 0.5, ease } } };

// ── Reading guides ──────────────────────────────────────────────────────────

export interface GuideText {
  what: string;
  read: string;
  why: string;
  /** "Your numbers": optional, may be built from live data. */
  ctx?: ReactNode;
}

// `version` counts flips of the global switch, so a component with its own
// open/closed state can tell "the reader just asked for everything" from its
// own last toggle.
const GuideCtx = createContext<{ on: boolean; flip: () => void; version: number }>({ on: true, flip: () => {}, version: 0 });

/** The global reading-guides switch, for components that keep their own open state. */
export const useGuides = () => useContext(GuideCtx);
const GUIDE_KEY = "shc-guides";

const subscribeStorage = (cb: () => void) => {
  window.addEventListener("storage", cb);
  return () => window.removeEventListener("storage", cb);
};
const readGuidePref = () => {
  try {
    return localStorage.getItem(GUIDE_KEY);
  } catch {
    return null; // storage blocked: guides stay on
  }
};

export function GuideProvider({ children }: { children: ReactNode }) {
  const stored = useSyncExternalStore(subscribeStorage, readGuidePref, () => null);
  const [override, setOverride] = useState<boolean | null>(null);
  const [version, setVersion] = useState(0);
  const on = override ?? stored !== "off";
  const flip = () => {
    setOverride(!on);
    setVersion((v) => v + 1);
    try {
      localStorage.setItem(GUIDE_KEY, on ? "off" : "on");
    } catch {
      /* storage blocked: toggle still works for this visit */
    }
  };
  return (
    <GuideCtx.Provider value={{ on, flip, version }}>
      {children}
      <button className="k-guide-toggle" onClick={flip} aria-pressed={on}>
        {on ? "Hide reading guides" : "Show reading guides"}
      </button>
    </GuideCtx.Provider>
  );
}

export function Guide({ g }: { g: GuideText }) {
  const { on } = useContext(GuideCtx);
  if (!on) return null;
  return (
    <dl className="k-guide">
      {(
        [
          ["What it measures", g.what],
          ["How to read it", g.read],
          ["Why it matters", g.why],
          ["Your numbers", g.ctx],
        ] as const
      ).map(([k, v]) =>
        v ? (
          <div key={k}>
            <dt>{k}</dt>
            <dd>{v}</dd>
          </div>
        ) : null,
      )}
    </dl>
  );
}

// ── Page structure ──────────────────────────────────────────────────────────

export function PageHead({ eyebrow, question, lede }: { eyebrow: string; question: string; lede?: ReactNode }) {
  return (
    <motion.header className="k-page-head" initial={{ opacity: 0.001, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.6, ease }}>
      <p className="k-eyebrow">{eyebrow}</p>
      <h1 className="k-question">{question}</h1>
      {lede && <p className="k-lede">{lede}</p>}
    </motion.header>
  );
}

export function Section({ n, title, children }: { n: string; title: string; children: ReactNode }) {
  return (
    <section className="k-section">
      <h2 className="k-section-title">
        <span>{n}</span>
        {title}
      </h2>
      <motion.div className="k-grid" variants={stagger} initial="hidden" animate="show">
        {children}
      </motion.div>
    </section>
  );
}

export function Panel({
  id,
  span = 1,
  title,
  question,
  explore,
  tag,
  guide,
  bare = false,
  fill = false,
  children,
}: {
  id?: string;
  span?: Span;
  title: string;
  question?: ReactNode;
  explore?: MetricKey;
  tag?: string;
  guide?: GuideText;
  /** For panels that bring their own card chrome: no surface, keeps the header and guide. */
  bare?: boolean;
  /** Stretch to the row's height and let the body (e.g. a Clamp) take exactly the free space. */
  fill?: boolean;
  children: ReactNode;
}) {
  return (
    <motion.article id={id} variants={rise} className={`k-panel k-span-${span}${bare ? " k-bare" : ""}${fill ? " k-fill" : ""} scroll-mt-24`}>
      <header className="k-panel-head">
        <div>
          <h3 className="k-panel-title">
            {title}
            {tag && <em className="k-tag">{tag}</em>}
          </h3>
          {question && <p className="k-panel-q">{question}</p>}
        </div>
        {explore && <ExploreButton metric={explore} />}
      </header>
      <div className="k-body">
        <ErrorBoundary label={title}>{children}</ErrorBoundary>
      </div>
      {guide && <Guide g={guide} />}
    </motion.article>
  );
}

// ── Charts ──────────────────────────────────────────────────────────────────

export function useWidth(initial = 560) {
  const ref = useRef<HTMLDivElement>(null);
  const [w, setW] = useState(initial);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    setW(Math.max(160, Math.round(el.getBoundingClientRect().width)));
    const ro = new ResizeObserver(([e]) => setW(Math.max(160, Math.round(e.contentRect.width))));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, w] as const;
}

/**
 * A chart that takes whatever vertical space its panel has spare (at least
 * `min` px). This is how stretched panels stay gap-free: slack becomes chart,
 * never empty space. The chart is absolutely positioned so its own height
 * can't feed back into the space it's measuring.
 */
export function Fill({ min = 110, children }: { min?: number; children: (height: number) => ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  const [h, setH] = useState(min);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setH(Math.max(min, Math.floor(e.contentRect.height))));
    ro.observe(el);
    return () => ro.disconnect();
  }, [min]);
  return (
    <div ref={ref} className="k-fillchart" style={{ minHeight: min }}>
      <div className="k-fillchart-inner">{children(h)}</div>
    </div>
  );
}

export function FillLines({ min = 110, ...props }: Omit<Parameters<typeof Lines>[0], "height"> & { min?: number }) {
  // Multi-series charts draw a legend under the plot; keep it inside the box.
  return <Fill min={min}>{(h) => <Lines {...props} height={props.series.length > 1 ? Math.max(min - 26, h - 26) : h} />}</Fill>;
}

export function FillBars({ min = 110, ...props }: Omit<Parameters<typeof Bars>[0], "height"> & { min?: number }) {
  return <Fill min={min}>{(h) => <Bars {...props} height={h} />}</Fill>;
}

/** Stacked columns: one column per label, segments bottom-up, 2px surface gaps. */
export function StackBars({
  labels,
  segments,
  height = 180,
  fmt = (v) => String(Math.round(v)),
  tip,
}: {
  labels: string[];
  segments: { name: string; color: string; values: number[] }[];
  height?: number;
  fmt?: (v: number) => string;
  tip?: (i: number) => ReactNode;
}) {
  const [ref, W] = useWidth();
  const [hov, setHov] = useState<number | null>(null);
  const totals = labels.map((_, i) => segments.reduce((s, g) => s + (g.values[i] ?? 0), 0));
  const ticks = niceTicks(0, Math.max(...totals, 1), height < 130 ? 2 : 3);
  const hi = ticks[ticks.length - 1];
  const P = { l: Math.max(...ticks.map((t) => fmt(t).length)) * 6.6 + 12, r: 6, t: 12, b: 24 };
  const n = labels.length;
  const slot = (W - P.l - P.r) / Math.max(1, n);
  const bw = Math.min(18, Math.max(4, slot - 3));
  const y = lin(0, hi, height - P.b, P.t);
  const cx = (i: number) => P.l + slot * (i + 0.5);
  const every = Math.ceil(n / Math.max(2, Math.floor((W - P.l) / 64)));
  return (
    <div className="k-chart" ref={ref} onMouseLeave={() => setHov(null)}>
      <svg width={W} height={height} viewBox={`0 0 ${W} ${height}`}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={P.l} x2={W - P.r} y1={y(t)} y2={y(t)} className={t === 0 ? "k-axis" : "k-gridline"} />
            <text x={P.l - 8} y={y(t) + 3.5} className="k-tick" textAnchor="end">
              {fmt(t)}
            </text>
          </g>
        ))}
        {labels.map((_, i) => {
          let acc = 0;
          const x0 = cx(i) - bw / 2;
          return (
            <motion.g key={i} onMouseEnter={() => setHov(i)} initial={{ opacity: 0, y: 8 }} animate={{ opacity: hov == null || hov === i ? 1 : 0.45, y: 0 }} transition={{ delay: i * 0.015, ease }}>
              <rect x={cx(i) - slot / 2} y={P.t} width={slot} height={height - P.b - P.t} fill="transparent" />
              {segments.map((g, si) => {
                const v = g.values[i] ?? 0;
                const y1 = y(acc);
                const y2 = y(acc + v);
                acc += v;
                const top = si === segments.length - 1;
                const h = Math.max(0, y1 - y2 - (top ? 0 : 2));
                if (h <= 0) return null;
                const r = top ? Math.min(3, h) : 0;
                return (
                  <path
                    key={g.name}
                    d={`M${x0},${y2 + h}V${y2 + r}Q${x0},${y2} ${x0 + r},${y2}H${x0 + bw - r}Q${x0 + bw},${y2} ${x0 + bw},${y2 + r}V${y2 + h}Z`}
                    fill={g.color}
                  />
                );
              })}
            </motion.g>
          );
        })}
        {labels.map((l, i) =>
          i % every === 0 ? (
            <text key={i} x={cx(i)} y={height - 6} className="k-tick" textAnchor="middle">
              {fmtX(l)}
            </text>
          ) : null,
        )}
      </svg>
      {hov != null && tip && (
        <div className="k-tip" style={cx(hov) > W * 0.6 ? { right: W - cx(hov) + 12 } : { left: cx(hov) + 12 }}>
          {tip(hov)}
        </div>
      )}
      <div className="k-legend">
        {segments.map((g) => (
          <span key={g.name}>
            <i style={{ background: g.color }} />
            {g.name}
          </span>
        ))}
      </div>
    </div>
  );
}

export function FillStackBars({ min = 160, ...props }: Omit<Parameters<typeof StackBars>[0], "height"> & { min?: number }) {
  return <Fill min={min}>{(h) => <StackBars {...props} height={Math.max(min - 26, h - 26)} />}</Fill>;
}

export function Bars({
  labels,
  values,
  height = 160,
  color = () => "var(--series-1)",
  fmt = (v) => String(Math.round(v)),
  refs = [],
  tip,
  max,
}: {
  labels: string[];
  values: number[];
  height?: number;
  color?: (v: number, i: number) => string;
  fmt?: (v: number) => string;
  refs?: { y: number; label: string }[];
  tip?: (i: number) => ReactNode;
  max?: number;
}) {
  const [ref, W] = useWidth();
  const [hov, setHov] = useState<number | null>(null);
  const ticks = niceTicks(0, Math.max(max ?? 0, ...values, ...refs.map((r) => r.y), 1), height < 130 ? 2 : 3);
  const hi = ticks[ticks.length - 1];
  const P = { l: Math.max(...ticks.map((t) => fmt(t).length)) * 6.6 + 12, r: 6, t: 12, b: 24 };
  const n = values.length;
  const slot = (W - P.l - P.r) / Math.max(1, n);
  const bw = Math.min(24, Math.max(4, slot - 2));
  const y = lin(0, hi, height - P.b, P.t);
  const cx = (i: number) => P.l + slot * (i + 0.5);
  const every = Math.ceil(n / Math.max(2, Math.floor((W - P.l) / 64)));
  return (
    <div className="k-chart" ref={ref} onMouseLeave={() => setHov(null)}>
      <svg width={W} height={height} viewBox={`0 0 ${W} ${height}`}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={P.l} x2={W - P.r} y1={y(t)} y2={y(t)} className={t === 0 ? "k-axis" : "k-gridline"} />
            <text x={P.l - 8} y={y(t) + 3.5} className="k-tick" textAnchor="end">
              {fmt(t)}
            </text>
          </g>
        ))}
        {values.map((v, i) => {
          const top = y(v);
          const x0 = cx(i) - bw / 2;
          const hgt = y(0) - top;
          const r = Math.min(4, bw / 2, Math.max(0, hgt));
          const d = hgt <= 0 ? "" : `M${x0},${y(0)}V${top + r}Q${x0},${top} ${x0 + r},${top}H${x0 + bw - r}Q${x0 + bw},${top} ${x0 + bw},${top + r}V${y(0)}Z`;
          return (
            <g key={i} onMouseEnter={() => setHov(i)}>
              <rect x={cx(i) - slot / 2} y={P.t} width={slot} height={height - P.b - P.t} fill="transparent" />
              <motion.path
                d={d}
                fill={color(v, i)}
                opacity={hov == null || hov === i ? 1 : 0.45}
                initial={{ scaleY: 0 }}
                animate={{ scaleY: 1 }}
                style={{ transformOrigin: `0px ${y(0)}px` }}
                transition={{ duration: 0.55, delay: i * 0.02, ease }}
              />
            </g>
          );
        })}
        {refs.map((r) => (
          <g key={r.label}>
            <line x1={P.l} x2={W - P.r} y1={y(r.y)} y2={y(r.y)} className="k-ref k-ref-bad" />
            <text x={P.l + 4} y={y(r.y) - 5} className="k-tick k-ref-bad-t">
              {r.label}
            </text>
          </g>
        ))}
        {labels.map((l, i) =>
          i % every === 0 ? (
            <text key={i} x={cx(i)} y={height - 6} className="k-tick" textAnchor="middle">
              {fmtX(l)}
            </text>
          ) : null,
        )}
      </svg>
      {hov != null && tip && (
        <div className="k-tip" style={cx(hov) > W * 0.6 ? { right: W - cx(hov) + 14 } : { left: cx(hov) + 14 }}>
          {tip(hov)}
        </div>
      )}
    </div>
  );
}

export function niceTicks(lo: number, hi: number, n = 4): number[] {
  const span = hi - lo || Math.abs(hi) || 1;
  const raw = span / n;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const e = raw / mag;
  const step = (e >= 7.5 ? 10 : e >= 3.5 ? 5 : e >= 1.5 ? 2 : 1) * mag;
  const out: number[] = [];
  for (let v = Math.floor(lo / step) * step; v <= Math.ceil(hi / step) * step + step / 1e6; v += step) out.push(+v.toFixed(6));
  return out;
}

const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
/** "2026-09-10" → "Sep 10"; "2026-09" → "Sep ’26"; anything else unchanged. */
export function fmtX(s: string): string {
  if (/^\d{4}-\d{2}-\d{2}/.test(s)) return `${MON[+s.slice(5, 7) - 1]} ${+s.slice(8, 10)}`;
  if (/^\d{4}-\d{2}$/.test(s)) return `${MON[+s.slice(5, 7) - 1]} ’${s.slice(2, 4)}`;
  return s;
}

const lin = (d0: number, d1: number, r0: number, r1: number) => (v: number) => r0 + ((v - d0) / (d1 - d0 || 1)) * (r1 - r0);

export interface Series {
  name: string;
  color: string;
  y: (number | null)[];
}

export function Lines({
  labels,
  series,
  band,
  height = 180,
  fmt = (v) => String(Math.round(v)),
  refs = [],
}: {
  labels: string[];
  series: Series[];
  band?: [number, number][];
  height?: number;
  fmt?: (v: number) => string;
  refs?: { y: number; label: string }[];
}) {
  const [ref, W] = useWidth();
  const gid = useId().replace(/:/g, "");
  const [hov, setHov] = useState<number | null>(null);
  const vals = [...series.flatMap((s) => s.y), ...(band ?? []).flat(), ...refs.map((r) => r.y)].filter((v): v is number => v != null);
  if (!vals.length || labels.length < 2) return <div ref={ref} className="k-empty">Not enough data yet.</div>;
  const ticks = niceTicks(Math.min(...vals), Math.max(...vals), height < 120 ? 2 : 4);
  const lo = ticks[0];
  const hi = ticks[ticks.length - 1];
  const P = { l: Math.max(...ticks.map((t) => fmt(t).length)) * 6.6 + 12, r: 40, t: 12, b: 24 };
  const n = labels.length;
  const x = lin(0, n - 1, P.l, W - P.r);
  const y = lin(lo, hi, height - P.b, P.t);
  const path = (ys: (number | null)[]) => {
    let d = "";
    let pen = false;
    ys.forEach((v, i) => {
      if (v == null) return void (pen = false);
      d += `${pen ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`;
      pen = true;
    });
    return d;
  };
  const first = series[0];
  const firstIdx = first.y.findIndex((v) => v != null);
  const area = series.length === 1 && !band ? `${path(first.y)}L${x(n - 1).toFixed(1)},${y(lo)}L${x(firstIdx).toFixed(1)},${y(lo)}Z` : null;
  const bandPath = band
    ? band.map((b, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(b[1]).toFixed(1)}`).join("") +
      band.map((_, j) => band.length - 1 - j).map((i) => `L${x(i).toFixed(1)},${y(band[i][0]).toFixed(1)}`).join("") +
      "Z"
    : null;
  const k = Math.max(2, Math.min(6, Math.floor(W / 110)));
  const xTicks = [...new Set(Array.from({ length: k }, (_, i) => Math.round((i * (n - 1)) / (k - 1))))];
  return (
    <div className="k-chart" ref={ref} onMouseLeave={() => setHov(null)}>
      <svg
        width={W}
        height={height}
        viewBox={`0 0 ${W} ${height}`}
        onMouseMove={(e) => {
          const r = e.currentTarget.getBoundingClientRect();
          setHov(Math.max(0, Math.min(n - 1, Math.round(((e.clientX - r.left - P.l) / (W - P.l - P.r)) * (n - 1)))));
        }}
      >
        <defs>
          <linearGradient id={gid} x1="0" x2="0" y1="0" y2="1">
            <stop offset="0" stopColor={first.color} stopOpacity="0.22" />
            <stop offset="1" stopColor={first.color} stopOpacity="0" />
          </linearGradient>
        </defs>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={P.l} x2={W - P.r} y1={y(t)} y2={y(t)} className={t === lo ? "k-axis" : "k-gridline"} />
            <text x={P.l - 8} y={y(t) + 3.5} className="k-tick" textAnchor="end">
              {fmt(t)}
            </text>
          </g>
        ))}
        {xTicks.map((i, j) => (
          <text key={i} x={x(i)} y={height - 6} className="k-tick" textAnchor={j === 0 ? "start" : j === xTicks.length - 1 ? "end" : "middle"}>
            {fmtX(labels[i])}
          </text>
        ))}
        {bandPath && <motion.path d={bandPath} fill="var(--series-band)" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.8 }} />}
        {area && <motion.path d={area} fill={`url(#${gid})`} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 1, delay: 0.4 }} />}
        {refs.map((r) => (
          <g key={r.label}>
            <line x1={P.l} x2={W - P.r} y1={y(r.y)} y2={y(r.y)} className="k-ref" />
            <text x={P.l + 4} y={y(r.y) - 5} className="k-tick">
              {r.label}
            </text>
          </g>
        ))}
        {series.map((s, i) => (
          <motion.path
            key={s.name}
            d={path(s.y)}
            fill="none"
            stroke={s.color}
            strokeWidth={2}
            strokeLinejoin="round"
            strokeLinecap="round"
            initial={{ pathLength: 0 }}
            animate={{ pathLength: 1 }}
            transition={{ duration: 1.2, delay: 0.12 * i, ease }}
          />
        ))}
        {series.map((s, si) => {
          const i = s.y.length - 1 - [...s.y].reverse().findIndex((v) => v != null);
          const v = s.y[i];
          return v == null ? null : (
            <g key={s.name}>
              <circle cx={x(i)} cy={y(v)} r={4.5} fill={s.color} stroke="var(--card)" strokeWidth={2} />
              {si === 0 && (
                <text x={x(i) + 9} y={y(v) + 4} className="k-end">
                  {fmt(v)}
                </text>
              )}
            </g>
          );
        })}
        {hov != null && <line x1={x(hov)} x2={x(hov)} y1={P.t} y2={height - P.b} className="k-cross" />}
        {hov != null &&
          series.map((s) => {
            const v = s.y[hov];
            return v == null ? null : <circle key={s.name} cx={x(hov)} cy={y(v)} r={4.5} fill={s.color} stroke="var(--card)" strokeWidth={2} />;
          })}
      </svg>
      {hov != null && (
        <div className="k-tip" style={x(hov) > W * 0.6 ? { right: W - x(hov) + 12 } : { left: x(hov) + 12 }}>
          <div className="k-tip-date">{fmtX(labels[hov])}</div>
          {series.map((s) => (
            <div key={s.name}>
              <i style={{ background: s.color }} />
              {s.name} <b>{s.y[hov] == null ? "–" : fmt(s.y[hov]!)}</b>
            </div>
          ))}
          {band && (
            <div className="k-tip-dim">
              normal range {fmt(band[hov][0])}–{fmt(band[hov][1])}
            </div>
          )}
        </div>
      )}
      {series.length > 1 && (
        <div className="k-legend">
          {series.map((s) => (
            <span key={s.name}>
              <i style={{ background: s.color }} />
              {s.name}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
