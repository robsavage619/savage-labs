"use client";

import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { api } from "@/lib/api";
import { readinessCommand } from "@/components/athlete-os-panel";
import { ease, Lines } from "@/components/kit";

/**
 * The answer to "should I push today?", above everything else: the reconciled
 * verdict and why, what the gates lock, the session at a glance, and 28 days
 * of HRV against your own normal band. All values as served by DailyState,
 * /api/workout/next and /api/hrv/trend.
 */

const TONE = { positive: "var(--positive)", neutral: "var(--neutral)", negative: "var(--negative)" } as const;

export function TodayHero() {
  const state = useQuery({ queryKey: ["daily-state"], queryFn: api.dailyState, staleTime: 5 * 60_000 });
  const plan = useQuery({ queryKey: ["workout-next"], queryFn: () => api.workoutNext(false), staleTime: 5 * 60_000 });
  const hrv = useQuery({ queryKey: ["hrv-trend", 28], queryFn: () => api.hrvTrend(28), staleTime: 10 * 60_000 });

  if (state.isError) return <p className="ts-error">Couldn&apos;t load today&apos;s state: {String(state.error)}</p>;
  const s = state.data;
  const cmd = readinessCommand(s, plan.data);
  const g = s?.gates;
  const locked = [
    ...(g?.forbid_muscle_groups ?? []).map((x) => ({ t: x, hard: true })),
    ...(g?.forbid_muscles ?? []).map((x) => ({ t: x, hard: false })),
    ...(g && g.max_intensity !== "high" ? [{ t: `ceiling: ${g.max_intensity}`, hard: false }] : []),
    ...(g?.deload_required ? [{ t: "deload", hard: true }] : []),
  ];
  const p = plan.data;
  const exercises = p?.blocks.flatMap((b) => b.exercises) ?? [];
  const sets = exercises.reduce((n, e) => n + e.sets, 0);
  const r = s?.readiness;
  const pts = hrv.data ?? [];

  return (
    <div className="th">
      <div className="th-verdict">
        <motion.div className="th-call" style={{ color: TONE[cmd.tone] }} initial={{ opacity: 0.001, x: -10 }} animate={{ opacity: 1, x: 0 }} transition={{ duration: 0.6, ease }}>
          {cmd.label}
        </motion.div>
        {/* `recommendation.rationale` is the planner's audit trail and must never
            reach the dashboard; `summary` is the plain-English sentence. */}
        <p className="th-why">{p?.recommendation.summary ?? g?.deload_reason ?? g?.reasons[0] ?? p?.readiness_summary ?? cmd.detail}</p>
        <div className="th-locks">
          {locked.length === 0 ? (
            <span className="th-chip th-clear">Nothing locked today</span>
          ) : (
            locked.map((l) => (
              <span key={l.t} className={`th-chip ${l.hard ? "th-hard" : "th-soft"}`}>
                {l.t.replace(/_/g, " ")}
              </span>
            ))
          )}
        </div>
        {p && (
          <a className="th-session" href="#session">
            <span className="th-session-focus">{p.recommendation.focus.split(" — ")[0]}</span>
            <span className="th-session-meta">
              {exercises.length} lifts · {sets} sets
              {p.recommendation.estimated_duration_min ? ` · ~${p.recommendation.estimated_duration_min} min` : ""}
              {p.recommendation.target_rpe ? ` · RPE ${p.recommendation.target_rpe}` : ""}
            </span>
            <span className="th-session-go">See the session ↓</span>
          </a>
        )}
      </div>

      <div className="th-numbers">
        <div className="th-stat">
          <span>Readiness</span>
          <b style={{ color: r?.tier ? TONE[r.tier === "green" ? "positive" : r.tier === "red" ? "negative" : "neutral"] : undefined }}>{r?.score ?? "–"}</b>
          <small>{r?.tier ? `${r.tier[0].toUpperCase()}${r.tier.slice(1)}` : "no data"}</small>
        </div>
        <div className="th-stat">
          <span>HRV</span>
          <b>{s?.recovery.hrv_ms != null ? Math.round(s.recovery.hrv_ms) : "–"}</b>
          <small>{s?.recovery.hrv_sigma != null ? `${s.recovery.hrv_sigma > 0 ? "+" : ""}${s.recovery.hrv_sigma.toFixed(1)}σ vs 28 d` : "ms"}</small>
        </div>
        <div className="th-stat">
          <span>Resting HR</span>
          <b>{s?.recovery.rhr ?? "–"}</b>
          <small>{s?.recovery.rhr_baseline_28d != null ? `baseline ${Math.round(s.recovery.rhr_baseline_28d)}` : "bpm"}</small>
        </div>
        <div className="th-stat">
          <span>Sleep</span>
          <b>{s?.sleep.last_hours != null ? s.sleep.last_hours.toFixed(1) : "–"}</b>
          <small>{s?.sleep.sleep_needed_min_last ? `needed ${(s.sleep.sleep_needed_min_last / 60).toFixed(1)} h` : "hours"}</small>
        </div>
      </div>

      <div className="th-chart">
        <p className="th-chart-label">HRV, last 28 days, against your normal band</p>
        {pts.length > 1 ? (
          <Lines
            labels={pts.map((x) => x.date)}
            series={[{ name: "HRV ms", color: "var(--series-1)", y: pts.map((x) => x.hrv) }]}
            band={pts.map((x) => [x.avg - x.sd, x.avg + x.sd] as [number, number])}
            height={170}
          />
        ) : (
          <div className="ts-skeleton" style={{ height: 170 }} />
        )}
      </div>
    </div>
  );
}
