"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { api } from "@/lib/api";
import { ease, fmtX, FillBars, FillLines } from "@/components/kit";

/**
 * Training, rebuilt on the kit. Every figure renders its route's values as
 * served: per-muscle sets come from /api/training/muscle-volume (the engine's
 * own weekly_muscle_volume, secondaries credited 1:1), never recounted here.
 */

const pretty = (s: string) => s.replace(/_/g, " ");
const Err = ({ e }: { e: unknown }) => <p className="ts-error">Couldn&apos;t load: {String(e)}</p>;
const Skel = ({ h }: { h: number }) => <div className="ts-skeleton" style={{ height: h }} />;

// ── Growth zones ────────────────────────────────────────────────────────────

const WEEKS_BACK = 6;

function weekLabel(weeksAgo: number, start?: string) {
  if (weeksAgo === 0) return "This week";
  return start ? `wk ${fmtX(start)}` : `${weeksAgo} wk ago`;
}

export function GrowthZones() {
  const [weeksAgo, setWeeksAgo] = useState(1);
  const vol = useQuery({ queryKey: ["muscle-volume", weeksAgo], queryFn: () => api.muscleVolume(weeksAgo), staleTime: 10 * 60 * 1000 });
  const tier = useQuery({ queryKey: ["training-tier"], queryFn: api.trainingTier, staleTime: 60 * 60 * 1000 });
  if (vol.isError) return <Err e={vol.error} />;
  const grow = new Set((tier.data?.muscles ?? []).filter((m) => m.tier === "grow").map((m) => m.muscle));
  const muscles = [...(vol.data?.muscles ?? [])]
    .filter((m) => m.mev != null && m.mrv != null)
    .sort((a, b) => Number(grow.has(b.muscle)) - Number(grow.has(a.muscle)) || a.muscle.localeCompare(b.muscle));
  const max = Math.max(24, ...muscles.map((m) => m.mrv ?? 0), ...muscles.map((m) => m.weekly_sets));
  const pct = (v: number) => `${(Math.min(v, max) / max) * 100}%`;
  const inZone = muscles.filter((m) => m.weekly_sets >= (m.mev ?? 0) && m.weekly_sets <= (m.mrv ?? 0)).length;
  return (
    <div className="gz">
      <div className="gz-top">
        <div className="gz-weeks" role="tablist" aria-label="Week">
          {Array.from({ length: WEEKS_BACK + 1 }, (_, i) => WEEKS_BACK - i).map((w) => (
            <button key={w} role="tab" aria-selected={w === weeksAgo} className={w === weeksAgo ? "on" : ""} onClick={() => setWeeksAgo(w)}>
              {w === weeksAgo && <motion.span layoutId="gz-week" className="gz-pill" transition={{ type: "spring", damping: 28, stiffness: 320 }} />}
              <span>{w === weeksAgo ? weekLabel(w, vol.data?.week_start) : w === 0 ? "This week" : `−${w}`}</span>
            </button>
          ))}
        </div>
        {vol.data && (
          <p className="gz-summary">
            <b>{inZone}</b> of {muscles.length} muscles inside their growth range
          </p>
        )}
      </div>
      {!vol.data ? (
        <Skel h={360} />
      ) : (
        <div className="gz-grid">
          {muscles.map((m, i) => {
            const v = m.weekly_sets;
            const st = v < m.mev! ? "under" : v > m.mrv! ? "over" : v >= (m.mav ?? m.mev!) ? "sweet" : "range";
            return (
              <div key={m.muscle} className="gz-row" title={`${pretty(m.muscle)}: ${v} sets · MEV ${m.mev} · MAV ${m.mav} · MRV ${m.mrv}`}>
                <span className="gz-name">
                  {pretty(m.muscle)}
                  {grow.has(m.muscle) && <em>grow</em>}
                </span>
                <span className="gz-track">
                  <span className="gz-range" style={{ left: pct(m.mev!), width: `calc(${pct(m.mrv!)} - ${pct(m.mev!)})` }} />
                  {m.mav != null && <span className="gz-sweet" style={{ left: pct(m.mav), width: `calc(${pct(m.mrv!)} - ${pct(m.mav)})` }} />}
                  <motion.span className={`gz-bar gz-s-${st}`} initial={{ width: 0 }} animate={{ width: pct(v) }} transition={{ duration: 0.7, delay: i * 0.02, ease }} />
                </span>
                <b className="gz-val">{v % 1 ? v.toFixed(1) : v}</b>
              </div>
            );
          })}
        </div>
      )}
      <div className="gz-legend">
        <span><i className="gz-l-range" />minimum to maximum useful sets (MEV–MRV)</span>
        <span><i className="gz-l-sweet" />sweet spot (MAV–MRV)</span>
        <span><i style={{ background: "var(--positive)" }} />in the sweet spot</span>
        <span><i style={{ background: "var(--neutral)" }} />in range</span>
        <span><i style={{ background: "var(--negative)" }} />under minimum or over maximum</span>
      </div>
    </div>
  );
}

// ── Lift scoreboard ─────────────────────────────────────────────────────────

const TREND_ORDER: Record<string, number> = { progressing: 0, stalled: 1, regressing: 2 };

export function LiftBoard() {
  const all = useQuery({ queryKey: ["progression-all", 12], queryFn: () => api.trainingProgressionAll(12), staleTime: 10 * 60 * 1000 });
  const lifts = [...(all.data?.exercises ?? [])]
    .filter((e) => e.trend)
    .sort((a, b) => (TREND_ORDER[a.trend!] ?? 3) - (TREND_ORDER[b.trend!] ?? 3) || a.exercise.localeCompare(b.exercise));
  const [picked, setPicked] = useState<string | null>(null);
  const sel = picked ?? lifts[0]?.exercise ?? null;
  const hist = useQuery({
    queryKey: ["progression", sel],
    queryFn: () => api.trainingProgression(sel!, 30),
    enabled: !!sel,
    staleTime: 10 * 60 * 1000,
  });
  if (all.isError) return <Err e={all.error} />;
  if (!all.data) return <Skel h={380} />;
  const count = (t: string) => lifts.filter((l) => l.trend === t).length;
  const pts = [...(hist.data?.history ?? [])].reverse();
  return (
    <div className="lb">
      <div className="lb-left">
        <div className="lb-counts">
          {(
            [
              ["progressing", "var(--positive)"],
              ["stalled", "var(--neutral)"],
              ["regressing", "var(--negative)"],
            ] as const
          ).map(([t, c]) => (
            <div key={t}>
              <b style={{ color: c }}>{count(t)}</b>
              <span>{t}</span>
            </div>
          ))}
        </div>
        <div className="lb-list" role="listbox" aria-label="Lifts">
          {lifts.map((l) => (
            <button key={l.exercise} role="option" aria-selected={l.exercise === sel} className={`lb-item${l.exercise === sel ? " on" : ""}`} onClick={() => setPicked(l.exercise)}>
              <i className={`lb-dot lb-${l.trend}`} />
              <span className="lb-name">{l.exercise}</span>
              <b>{l.e1rm_lbs ?? "–"}</b>
            </button>
          ))}
        </div>
      </div>
      <div className="lb-right">
        <p className="lb-chart-title">
          {sel} <span>top set per session, lb{sel?.includes("Dumbbell") ? " per hand" : ""}</span>
        </p>
        {hist.isError ? (
          <Err e={hist.error} />
        ) : pts.length > 1 ? (
          <FillLines labels={pts.map((p) => p.date)} series={[{ name: "Top set lb", color: "var(--series-1)", y: pts.map((p) => p.max_lbs) }]} min={260} />
        ) : (
          <Skel h={260} />
        )}
      </div>
    </div>
  );
}

// ── Fitness, fatigue, form ──────────────────────────────────────────────────

function useLoadCurve(days: number) {
  return useQuery({ queryKey: ["load-curve", days], queryFn: () => api.loadCurve(days), staleTime: 10 * 60 * 1000 });
}

export function FitnessFatigue() {
  const q = useLoadCurve(90);
  if (q.isError) return <Err e={q.error} />;
  const pts = q.data?.points ?? [];
  if (pts.length < 2) return <Skel h={240} />;
  return (
    <FillLines
      labels={pts.map((p) => p.date)}
      series={[
        { name: "Fitness (42-day)", color: "var(--series-1)", y: pts.map((p) => p.ctl) },
        { name: "Fatigue (7-day)", color: "var(--series-2)", y: pts.map((p) => p.atl) },
      ]}
      min={240}
      fmt={(v) => v.toFixed(0)}
    />
  );
}

export function FormChart() {
  const q = useLoadCurve(90);
  if (q.isError) return <Err e={q.error} />;
  const pts = q.data?.points ?? [];
  if (pts.length < 2) return <Skel h={200} />;
  const last = pts[pts.length - 1].tsb;
  return (
    <div className="ts-card">
      <p className="ts-lede">
        Today <b>{last > 0 ? "+" : ""}{last.toFixed(1)}</b>: {last > 5 ? "fresh, room to push" : last < -10 ? "carrying real fatigue" : "balanced"}.
      </p>
      <FillLines labels={pts.map((p) => p.date)} series={[{ name: "Form", color: "var(--series-1)", y: pts.map((p) => p.tsb) }]} refs={[{ y: 0, label: "0" }]} min={180} fmt={(v) => v.toFixed(0)} />
    </div>
  );
}

export function MonotonyBars() {
  const q = useQuery({ queryKey: ["training-monotony", 12], queryFn: () => api.trainingMonotony(12), staleTime: 10 * 60 * 1000 });
  if (q.isError) return <Err e={q.error} />;
  const d = q.data;
  if (!d) return <Skel h={200} />;
  return (
    <div className="ts-card">
      <p className="ts-lede">
        {d.weeks_above_heuristic === 0 ? `No week crossed ${d.heuristic_reference.toFixed(1)}. Your days are ${d.verdict}.` : `${d.weeks_above_heuristic} of ${d.weeks.length} weeks crossed ${d.heuristic_reference.toFixed(1)}.`}
      </p>
      <FillBars
        labels={d.weeks.map((w) => w.week_start)}
        values={d.weeks.map((w) => w.monotony ?? 0)}
        refs={[{ y: d.heuristic_reference, label: `${d.heuristic_reference.toFixed(1)} warning` }]}
        max={d.heuristic_reference * 1.1}
        fmt={(v) => v.toFixed(1)}
        color={(v) => (v >= d.heuristic_reference ? "var(--negative)" : "var(--series-1)")}
        tip={(i) => (
          <>
            <div className="k-tip-date">week of {fmtX(d.weeks[i].week_start)}</div>
            <div>
              monotony <b>{d.weeks[i].monotony?.toFixed(2) ?? "–"}</b>
            </div>
            <div>{d.weeks[i].training_days} training days</div>
          </>
        )}
        min={180}
      />
    </div>
  );
}

// ── The block and the balance ───────────────────────────────────────────────

export function BlockStrip() {
  const meso = useQuery({ queryKey: ["mesocycle"], queryFn: api.mesocycle, staleTime: 10 * 60 * 1000 });
  const weekly = useQuery({ queryKey: ["training-weekly", 12], queryFn: () => api.trainingWeekly(12), staleTime: 10 * 60 * 1000 });
  if (meso.isError) return <Err e={meso.error} />;
  const m = meso.data;
  if (!m) return <Skel h={300} />;
  const blockWeeks = (weekly.data ?? []).filter((w) => w.week >= m.started_on.slice(0, 10));
  return (
    <div className="ts-card">
      <div className="bk-strip">
        {Array.from({ length: m.planned_weeks + 1 }, (_, i) => {
          const deload = i === m.planned_weeks;
          const state = deload ? "deload" : i < m.week_number - 1 ? "done" : i === m.week_number - 1 ? "now" : "";
          return (
            <motion.span key={i} className={`bk-week ${state}`} initial={{ scaleY: 0 }} animate={{ scaleY: 1 }} transition={{ delay: i * 0.04, ease }}>
              {deload ? "DL" : `W${i + 1}`}
            </motion.span>
          );
        })}
      </div>
      <p className="ts-lede">
        Week {m.week_number} of {m.planned_weeks}
        {m.is_deload_week ? ", deload week" : m.week_number >= m.planned_weeks ? ", deload is next" : `, ${m.planned_weeks - m.week_number} more before the deload`}. Started {fmtX(m.started_on)}.
      </p>
      <p className="ls-mini-label">Working sets per week in this block</p>
      {blockWeeks.length ? (
        <FillBars labels={blockWeeks.map((w) => w.week)} values={blockWeeks.map((w) => w.sets)} tip={(i) => <><div className="k-tip-date">week of {fmtX(blockWeeks[i].week)}</div><div><b>{blockWeeks[i].sets}</b> sets · {blockWeeks[i].sessions} sessions</div></>} min={150} />
      ) : (
        <Skel h={150} />
      )}
    </div>
  );
}

const GROUP_COLOR: Record<string, string> = { push: "var(--series-1)", pull: "var(--series-2)", legs: "var(--positive)", core: "var(--neutral)", other: "var(--hairline-strong)" };

export function BalanceBars() {
  const q = useQuery({ queryKey: ["muscle-balance", 4], queryFn: () => api.trainingMuscleBalance(4), staleTime: 10 * 60 * 1000 });
  if (q.isError) return <Err e={q.error} />;
  const d = q.data;
  if (!d) return <Skel h={300} />;
  const max = Math.max(...d.groups.map((g) => g.weekly_sets), 1);
  const push = d.groups.find((g) => g.group === "push")?.weekly_sets ?? 0;
  const pull = d.groups.find((g) => g.group === "pull")?.weekly_sets ?? 0;
  return (
    <div className="ts-card">
      <div className="bl-list">
        {d.groups.map((g, i) => (
          <div key={g.group} className="bl-row">
            <span className="bl-name">{g.group}</span>
            <span className="bl-track">
              <motion.i style={{ background: GROUP_COLOR[g.group] ?? "var(--series-1)" }} initial={{ width: 0 }} animate={{ width: `${(g.weekly_sets / max) * 100}%` }} transition={{ duration: 0.7, delay: i * 0.05, ease }} />
            </span>
            <b>{g.weekly_sets.toFixed(1)}</b>
            <small>{g.share_pct.toFixed(0)}%</small>
          </div>
        ))}
      </div>
      <p className="ts-foot">
        Sets per week over the last 4 weeks. Push to pull is {pull ? (push / pull).toFixed(2) : "–"} : 1; direct back work is {d.direct_back_weekly_sets.toFixed(1)} sets a week.
      </p>
    </div>
  );
}

// ── Consistency ─────────────────────────────────────────────────────────────

export function WeeklyVolume() {
  const q = useQuery({ queryKey: ["training-weekly", 26], queryFn: () => api.trainingWeekly(26), staleTime: 10 * 60 * 1000 });
  if (q.isError) return <Err e={q.error} />;
  const w = q.data ?? [];
  if (!w.length) return <Skel h={200} />;
  const avg = w.reduce((s, x) => s + x.sets, 0) / w.length;
  return (
    <div className="ts-card">
      <p className="ts-lede">
        Averaging <b>{Math.round(avg)}</b> working sets and <b>{(w.reduce((s, x) => s + x.sessions, 0) / w.length).toFixed(1)}</b> sessions a week over 26 weeks.
      </p>
      <FillBars
        labels={w.map((x) => x.week)}
        values={w.map((x) => x.sets)}
        tip={(i) => (
          <>
            <div className="k-tip-date">week of {fmtX(w[i].week)}</div>
            <div>
              <b>{w[i].sets}</b> sets · {w[i].sessions} sessions
            </div>
          </>
        )}
        min={200}
      />
    </div>
  );
}
