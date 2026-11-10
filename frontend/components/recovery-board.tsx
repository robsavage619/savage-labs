"use client";

import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { api } from "@/lib/api";
import { ease, fmtX, FillBars, FillLines, FillStackBars } from "@/components/kit";

/**
 * Recovery, rebuilt on the kit: every chart is read against your own normal,
 * and every value renders as served by its route.
 */

const Err = ({ e }: { e: unknown }) => <p className="ts-error">Couldn&apos;t load: {String(e)}</p>;
const Skel = ({ h }: { h: number }) => <div className="ts-skeleton" style={{ height: h }} />;
const useState28 = () => useQuery({ queryKey: ["daily-state"], queryFn: api.dailyState, staleTime: 5 * 60 * 1000 });

// ── Nervous system ──────────────────────────────────────────────────────────

export function HrvBand() {
  const q = useQuery({ queryKey: ["hrv-trend", 90], queryFn: () => api.hrvTrend(90), staleTime: 10 * 60 * 1000 });
  if (q.isError) return <Err e={q.error} />;
  const p = q.data ?? [];
  if (p.length < 2) return <Skel h={260} />;
  const last = p[p.length - 1];
  return (
    <div className="ts-card">
      <p className="ts-lede">
        Last night <b>{Math.round(last.hrv)} ms</b> against a 28-day average of <b>{Math.round(last.avg)}</b>; the average itself was{" "}
        <b>{Math.round(p[0].avg)}</b> three months ago.
      </p>
      <FillLines
        labels={p.map((x) => x.date)}
        series={[
          { name: "HRV ms", color: "var(--series-1)", y: p.map((x) => x.hrv) },
          { name: "28-day average", color: "var(--series-2)", y: p.map((x) => x.avg) },
        ]}
        band={p.map((x) => [x.avg - x.sd, x.avg + x.sd] as [number, number])}
        min={260}
      />
    </div>
  );
}

function useRecovery90() {
  return useQuery({ queryKey: ["recovery-trend", 90], queryFn: () => api.recoveryTrend(90), staleTime: 10 * 60 * 1000 });
}

export function RhrTrend() {
  const q = useRecovery90();
  const s = useState28();
  if (q.isError) return <Err e={q.error} />;
  const p = q.data ?? [];
  if (p.length < 2) return <Skel h={260} />;
  const base = s.data?.recovery.rhr_baseline_28d ?? null;
  return (
    <div className="ts-card">
      <p className="ts-lede">
        Today <b>{p[p.length - 1].rhr} bpm</b>
        {base != null ? `, baseline ${Math.round(base)}` : ""}. Lower is better.
      </p>
      <FillLines labels={p.map((x) => x.date)} series={[{ name: "Resting HR", color: "var(--series-1)", y: p.map((x) => x.rhr) }]} refs={base != null ? [{ y: base, label: `baseline ${Math.round(base)}` }] : []} min={220} />
    </div>
  );
}

export function RecoveryScoreTrend() {
  const q = useRecovery90();
  if (q.isError) return <Err e={q.error} />;
  const p = q.data ?? [];
  if (p.length < 2) return <Skel h={260} />;
  const green = p.filter((x) => x.score >= 67).length;
  return (
    <div className="ts-card">
      <p className="ts-lede">
        <b>{green}</b> green mornings in the last {p.length}.
      </p>
      <FillLines
        labels={p.map((x) => x.date)}
        series={[{ name: "Recovery", color: "var(--series-1)", y: p.map((x) => x.score) }]}
        refs={[
          { y: 67, label: "green 67" },
          { y: 34, label: "red 34" },
        ]}
        min={220}
      />
    </div>
  );
}

// ── Sleep ───────────────────────────────────────────────────────────────────

interface Night {
  date: string;
  deep: number;
  rem: number;
  light: number;
  awake: number;
}

/** WHOOP stages arrive as a Python-repr dict string; nights with two main sleeps keep the longer. */
function parseNights(rows: { date: string; stages: string | null }[]): Night[] {
  const best = new Map<string, Night>();
  for (const r of rows) {
    if (!r.stages) continue;
    let s: Record<string, number>;
    try {
      s = JSON.parse(r.stages.replace(/'/g, '"'));
    } catch {
      continue;
    }
    const min = (k: string) => Math.round((s[k] ?? 0) / 60000);
    const n = { date: r.date, deep: min("total_slow_wave_sleep_time_milli"), rem: min("total_rem_sleep_time_milli"), light: min("total_light_sleep_time_milli"), awake: min("total_awake_time_milli") };
    const prev = best.get(r.date);
    if (!prev || n.deep + n.rem + n.light > prev.deep + prev.rem + prev.light) best.set(r.date, n);
  }
  return [...best.values()].sort((a, b) => a.date.localeCompare(b.date));
}

export function SleepStages() {
  const q = useQuery({ queryKey: ["sleep-trend", 28], queryFn: () => api.sleepTrend(28), staleTime: 10 * 60 * 1000 });
  if (q.isError) return <Err e={q.error} />;
  const nights = parseNights(q.data ?? []);
  if (nights.length < 2) return <Skel h={260} />;
  const avg = (k: keyof Omit<Night, "date">) => Math.round(nights.reduce((s, n) => s + n[k], 0) / nights.length);
  return (
    <div className="ts-card">
      <p className="ts-lede">
        Average night: <b>{avg("deep")}</b> min deep, <b>{avg("rem")}</b> REM, <b>{avg("light")}</b> light.
      </p>
      <FillStackBars
        labels={nights.map((n) => n.date)}
        segments={[
          { name: "Deep", color: "var(--stage-deep)", values: nights.map((n) => n.deep / 60) },
          { name: "REM", color: "var(--stage-rem)", values: nights.map((n) => n.rem / 60) },
          { name: "Light", color: "var(--stage-light)", values: nights.map((n) => n.light / 60) },
          { name: "Awake", color: "var(--stage-awake)", values: nights.map((n) => n.awake / 60) },
        ]}
        fmt={(v) => `${v}h`}
        tip={(i) => (
          <>
            <div className="k-tip-date">night of {fmtX(nights[i].date)}</div>
            <div>
              deep <b>{nights[i].deep}</b> · REM <b>{nights[i].rem}</b> · light <b>{nights[i].light}</b> · awake <b>{nights[i].awake}</b> min
            </div>
          </>
        )}
        min={240}
      />
    </div>
  );
}

export function SleepNeed() {
  const q = useState28();
  if (q.isError) return <Err e={q.error} />;
  const s = q.data?.sleep;
  if (!s) return <Skel h={260} />;
  const parts: [string, number][] = [
    ["Baseline need", s.sleep_need_baseline_min_last ?? 0],
    ["+ sleep debt", s.sleep_need_debt_min_last ?? 0],
    ["+ yesterday's strain", s.sleep_need_strain_min_last ?? 0],
    ["− naps", -(s.sleep_need_nap_min_last ?? 0)],
  ];
  const need = s.sleep_needed_min_last;
  const got = s.last_hours != null ? s.last_hours * 60 : null;
  const scale = Math.max(need ?? 0, got ?? 0, 1) * 1.05;
  let run = 0;
  return (
    <div className="ts-card">
      <div className="sn-rows sn-fill">
        {parts
          .filter(([, v]) => v !== 0)
          .map(([label, v], i) => {
            const left = run;
            run += v;
            return (
              <div key={label} className="sn-row">
                <span>{label}</span>
                <span className="sn-track">
                  <motion.i
                    style={{ left: `${((v < 0 ? run : left) / scale) * 100}%`, background: v < 0 ? "var(--positive)" : "var(--series-2)" }}
                    initial={{ width: 0 }}
                    animate={{ width: `${(Math.abs(v) / scale) * 100}%` }}
                    transition={{ duration: 0.6, delay: i * 0.12, ease }}
                  />
                </span>
                <b>{Math.round(v)}m</b>
              </div>
            );
          })}
        <div className="sn-row sn-total">
          <span>You slept</span>
          <span className="sn-track">{got != null && <motion.i style={{ left: 0, background: "var(--series-1)" }} initial={{ width: 0 }} animate={{ width: `${(got / scale) * 100}%` }} transition={{ duration: 0.6, delay: 0.5, ease }} />}</span>
          <b>{got == null ? "–" : `${Math.round(got)}m`}</b>
        </div>
      </div>
      <p className="ts-foot">
        {need != null && got != null ? (got >= need ? `${Math.round(got - need)} min more than you needed.` : `${Math.round(need - got)} min short of what you needed.`) : "WHOOP hasn't served a need breakdown for last night."}
      </p>
    </div>
  );
}

export function SleepTiming() {
  const q = useState28();
  const t = useQuery({ queryKey: ["sleep-trend", 28], queryFn: () => api.sleepTrend(28), staleTime: 10 * 60 * 1000 });
  if (q.isError) return <Err e={q.error} />;
  const s = q.data?.sleep;
  if (!s) return <Skel h={260} />;
  const nights = parseNights(t.data ?? []);
  const off = s.midpoint_vs_optimal_h;
  return (
    <div className="ts-card">
      <div className="st-stats">
        <div>
          <span>Consistency</span>
          <b>{s.consistency_pct_last != null ? `${Math.round(s.consistency_pct_last)}%` : "–"}</b>
        </div>
        <div>
          <span>Midpoint vs ideal</span>
          <b>{off != null ? `${off > 0 ? "+" : ""}${off.toFixed(1)}h` : "–"}</b>
        </div>
        <div>
          <span>Efficiency</span>
          <b>{s.efficiency_pct_last != null ? `${Math.round(s.efficiency_pct_last)}%` : "–"}</b>
        </div>
        <div>
          <span>Wake-ups</span>
          <b>{s.disturbance_count_last ?? "–"}</b>
        </div>
      </div>
      <p className="ls-mini-label">Hours asleep, last {nights.length} nights</p>
      {nights.length > 1 ? (
        <FillLines labels={nights.map((n) => n.date)} series={[{ name: "Asleep h", color: "var(--series-1)", y: nights.map((n) => +((n.deep + n.rem + n.light) / 60).toFixed(2)) }]} refs={[{ y: 7, label: "7 h" }]} fmt={(v) => v.toFixed(0)} min={130} />
      ) : (
        <Skel h={130} />
      )}
    </div>
  );
}

// ── The week ────────────────────────────────────────────────────────────────

export function WeekOverWeek() {
  const q = useQuery({ queryKey: ["momentum"], queryFn: api.momentum, staleTime: 10 * 60 * 1000 });
  if (q.isError) return <Err e={q.error} />;
  const d = q.data;
  if (!d) return <Skel h={200} />;
  const rows: [string, number | null, number | null, string, boolean][] = [
    ["Recovery", d.this_week.recovery_avg, d.last_week.recovery_avg, "", true],
    ["Sleep", d.this_week.sleep_avg_h, d.last_week.sleep_avg_h, "h", true],
    ["Sessions", d.this_week.sessions, d.last_week.sessions, "", true],
  ];
  return (
    <div className="ts-card">
      <div className="wk-grid">
        {rows.map(([label, now, prev, unit]) => {
          const delta = now != null && prev != null ? now - prev : null;
          return (
            <div key={label} className="wk-tile">
              <span>{label}</span>
              <b>
                {now ?? "–"}
                {unit}
              </b>
              <small className={delta == null || delta === 0 ? "" : delta > 0 ? "up" : "down"}>
                {delta == null ? "no prior week" : `${delta > 0 ? "▲" : delta < 0 ? "▼" : "="} ${Math.abs(+delta.toFixed(1))}${unit} vs ${prev}${unit}`}
              </small>
            </div>
          );
        })}
      </div>
      <RecoveryFortnight thisWeek={d.this_week.recovery_avg} lastWeek={d.last_week.recovery_avg} />
      <p className="ts-foot">Last 7 days against the 7 before. Two weeks down in a row is the signal, not one.</p>
    </div>
  );
}

/** Daily recovery across the two weeks being compared, with each week's average. */
function RecoveryFortnight({ thisWeek, lastWeek }: { thisWeek: number | null; lastWeek: number | null }) {
  const q = useQuery({ queryKey: ["recovery-trend", 14], queryFn: () => api.recoveryTrend(14), staleTime: 10 * 60 * 1000 });
  const p = q.data ?? [];
  const refs = [
    ...(thisWeek != null ? [{ y: thisWeek, label: `this week ${thisWeek}` }] : []),
    ...(lastWeek != null ? [{ y: lastWeek, label: `last week ${lastWeek}` }] : []),
  ];
  return (
    <div className="ls-mini">
      <p className="ls-mini-label">Daily recovery, last 14 days</p>
      {p.length > 1 ? <FillLines labels={p.map((x) => x.date)} series={[{ name: "Recovery", color: "var(--series-1)", y: p.map((x) => x.score) }]} refs={refs} min={150} /> : <Skel h={150} />}
    </div>
  );
}

const Z2_DOSE_MIN = 180;

export function AerobicBase() {
  const q = useState28();
  if (q.isError) return <Err e={q.error} />;
  const t = q.data?.training_load;
  if (!t) return <Skel h={260} />;
  const base = t.cardio_aerobic_base_min_7d ?? null;
  const zones = Object.entries(t.cardio_zone_min_7d ?? {}).sort(([a], [b]) => a.localeCompare(b));
  const r = 70;
  const arc = Math.PI * r;
  const pct = base == null ? 0 : Math.min(base / Z2_DOSE_MIN, 1);
  return (
    <div className="ts-card">
      <div className="ab-gauge">
        <svg width={180} height={104} viewBox="0 0 180 104" role="img" aria-label={`${base ?? 0} of ${Z2_DOSE_MIN} aerobic-base minutes`}>
          <path d="M20 94 A70 70 0 0 1 160 94" fill="none" stroke="oklch(1 0 0 / 0.07)" strokeWidth={12} strokeLinecap="round" />
          <path d="M20 94 A70 70 0 0 1 160 94" fill="none" stroke={pct >= 1 ? "var(--positive)" : "var(--neutral)"} strokeWidth={12} strokeLinecap="round" strokeDasharray={`${arc * pct} ${arc}`} className="ts-ring-fill" />
          <text x={90} y={80} textAnchor="middle" className="ab-num">
            {base ?? "–"}
          </text>
          <text x={90} y={98} textAnchor="middle" className="ab-sub">
            of {Z2_DOSE_MIN} min
          </text>
        </svg>
      </div>
      <FillBars
        labels={zones.map(([k]) => k.toUpperCase())}
        values={zones.map(([, v]) => Math.round(v))}
        color={(_, i) => (zones[i][0] === "z2" || zones[i][0] === "z3" ? "var(--series-1)" : "var(--hairline-strong)")}
        tip={(i) => (
          <>
            <div className="k-tip-date">{zones[i][0].toUpperCase()}</div>
            <div>
              <b>{Math.round(zones[i][1])}</b> min this week
            </div>
          </>
        )}
        min={120}
      />
    </div>
  );
}

export function Spo2Burden() {
  const q = useQuery({ queryKey: ["sleep-airway", 28], queryFn: () => api.sleepAirway(28), staleTime: 10 * 60 * 1000 });
  if (q.isError) return <Err e={q.error} />;
  const d = q.data;
  if (!d) return <Skel h={260} />;
  const nights = d.nights.filter((n) => n.spo2 != null);
  return (
    <div className="ts-card">
      <p className="ts-lede">
        <b>{d.spo2.below_95}</b> of {d.spo2.n} nights averaged under 95%.
      </p>
      {nights.length > 1 ? (
        <FillLines labels={nights.map((n) => n.date)} series={[{ name: "SpO₂ %", color: "var(--series-1)", y: nights.map((n) => n.spo2) }]} refs={[{ y: 95, label: "95%" }]} fmt={(v) => v.toFixed(0)} min={160} />
      ) : (
        <Skel h={160} />
      )}
      <p className="ts-foot">A nightly average from a strap sensor, not a sleep study: a reason to ask, not a diagnosis.</p>
    </div>
  );
}

// ── Patterns ────────────────────────────────────────────────────────────────

function usePatterns() {
  return useQuery({ queryKey: ["whoop-patterns"], queryFn: api.whoopPatterns, staleTime: 30 * 60 * 1000 });
}

export function DayOfWeek() {
  const q = usePatterns();
  if (q.isError) return <Err e={q.error} />;
  const d = q.data?.by_day_of_week ?? [];
  if (!d.length) return <Skel h={240} />;
  const best = [...d].sort((a, b) => b.avg_recovery - a.avg_recovery);
  return (
    <div className="ts-card">
      <p className="ts-lede">
        Best on <b>{best[0].day}</b> ({best[0].avg_recovery}), worst on <b>{best[best.length - 1].day}</b> ({best[best.length - 1].avg_recovery}).
      </p>
      <FillBars
        labels={d.map((x) => x.day)}
        values={d.map((x) => x.avg_recovery)}
        color={(v) => (v >= 67 ? "var(--positive)" : v >= 60 ? "var(--series-1)" : "var(--series-2)")}
        tip={(i) => (
          <>
            <div className="k-tip-date">{d[i].day}</div>
            <div>
              average <b>{d[i].avg_recovery}</b> over {d[i].n} mornings
            </div>
          </>
        )}
        min={200}
      />
    </div>
  );
}

const BUCKET_COLOR: [RegExp, string][] = [
  [/green/i, "var(--positive)"],
  [/yellow/i, "var(--neutral)"],
  [/red/i, "var(--negative)"],
];

export function RecoveryMix() {
  const q = usePatterns();
  if (q.isError) return <Err e={q.error} />;
  const d = q.data?.distribution ?? [];
  if (!d.length) return <Skel h={240} />;
  const order = ["green", "yellow", "red"];
  const rows = [...d].sort((a, b) => order.findIndex((o) => a.bucket.toLowerCase().includes(o)) - order.findIndex((o) => b.bucket.toLowerCase().includes(o)));
  const total = rows.reduce((s, x) => s + x.n, 0);
  return (
    <div className="ts-card">
      <div className="mix-bar" role="img" aria-label="Share of green, yellow and red mornings">
        {rows.map((x) => (
          <motion.i key={x.bucket} style={{ background: BUCKET_COLOR.find(([re]) => re.test(x.bucket))?.[1] }} initial={{ width: 0 }} animate={{ width: `${(x.n / total) * 100}%` }} transition={{ duration: 0.8, ease }} />
        ))}
      </div>
      <div className="mix-list">
        {rows.map((x) => (
          <div key={x.bucket} className="mix-row">
            <i style={{ background: BUCKET_COLOR.find(([re]) => re.test(x.bucket))?.[1] }} />
            <span>{x.bucket}</span>
            <b>{x.n}</b>
            <small>{Math.round((x.n / total) * 100)}%</small>
          </div>
        ))}
      </div>
      <p className="ts-foot">Every morning WHOOP has scored, all time: {total} of them.</p>
    </div>
  );
}
