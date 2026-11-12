"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";

const WORD: Record<string, string> = {
  better: "better",
  worse: "worse",
  steady: "steady",
  moved: "moved",
  unknown: "not enough data",
};

/** The last 7 days against the prior 28, each call made inside your own noise. */
export function WeekCard() {
  const { data } = useQuery({ queryKey: ["week-card"], queryFn: api.weekCard });
  if (!data) return null;
  const gap = data.rpe_gap;
  const latest = gap.sessions.find((s) => s.missing > 0);
  return (
    <section className="wk-card">
      <div className="wk-grid">
        {data.domains.map((d) => (
          <div key={d.key} className="wk-cell" data-status={d.status}>
            <span className="wk-label">{d.label}</span>
            <b className="wk-value">{d.value == null ? "–" : d.value.toFixed(d.key === "sleep_h" || d.key === "work_sets" ? 1 : 0)}</b>
            <span className="wk-status">
              {WORD[d.status]}
              {d.baseline != null && d.status !== "unknown" && <> · was {d.baseline.toFixed(d.key === "sleep_h" || d.key === "work_sets" ? 1 : 0)}</>}
            </span>
          </div>
        ))}
      </div>
      {gap.pct_missing != null && gap.pct_missing >= 10 && latest && (
        <p className="wk-rpe">
          {gap.missing} of {gap.sets} working sets in the last 14 days have no RPE
          {" "}({gap.pct_missing}%). Latest gap: {latest.date}, {latest.missing} sets. Add them in Hevy;
          the engine reads effort from there.
        </p>
      )}
    </section>
  );
}
