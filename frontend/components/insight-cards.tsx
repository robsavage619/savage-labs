"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";

/** Quarterly pickleball HR cost, oldest first, with the first-to-latest change spelled out. */
export function PickleballHrCost() {
  const { data } = useQuery({ queryKey: ["pickleball-hr-cost"], queryFn: api.pickleballHrCost });
  if (!data) return null;
  if (data.length < 2) return <p className="wk-rpe">Needs two quarters with 8+ sessions each.</p>;
  const a = data[0];
  const b = data[data.length - 1];
  type Q = (typeof data)[number];
  const cols: [string, (q: Q) => string][] = [
    ["Sessions", (q) => `${q.sessions}`],
    ["Session HR", (q) => `${q.avg_hr}`],
    ["Peak HR", (q) => (q.peak_hr == null ? "–" : `${q.peak_hr}`)],
    ["Minutes", (q) => (q.minutes == null ? "–" : `${q.minutes}`)],
    ["kcal/min", (q) => (q.kcal_per_min == null ? "–" : q.kcal_per_min.toFixed(1))],
  ];
  return (
    <section className="wk-card">
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", fontSize: 13, borderCollapse: "collapse" }}>
          <thead>
            <tr>
              <th style={{ textAlign: "left" }} className="wk-label">Quarter</th>
              {cols.map(([h]) => (
                <th key={h} style={{ textAlign: "right" }} className="wk-label">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.map((q) => (
              <tr key={q.quarter}>
                <td>{q.quarter}</td>
                {cols.map(([h, f]) => (
                  <td key={h} style={{ textAlign: "right", fontVariantNumeric: "tabular-nums" }}>{f(q)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="wk-rpe">
        {a.quarter} to {b.quarter}: session HR {b.avg_hr - a.avg_hr >= 0 ? "+" : ""}
        {b.avg_hr - a.avg_hr} bpm
        {a.peak_hr != null && b.peak_hr != null && (
          <>, peak HR {b.peak_hr - a.peak_hr >= 0 ? "+" : ""}{b.peak_hr - a.peak_hr} bpm</>
        )}
        . A peak that falls this far is more often the drug, easier games or the strap than fitness.
      </p>
    </section>
  );
}

/** Which surfaces get opened. After 30 days, one never opened is a delete candidate. */
export function ScreenViews() {
  const { data } = useQuery({ queryKey: ["views"], queryFn: api.views });
  if (!data) return null;
  if (!data.surfaces.length) return <p className="wk-rpe">Counting starts with the next screen you open.</p>;
  return (
    <section className="wk-card">
      <div className="wk-grid">
        {data.surfaces.map((s) => (
          <div key={s.path} className="wk-cell">
            <span className="wk-label">{s.path === "/" ? "Today" : s.path.slice(1)}</span>
            <b className="wk-value">{s.opens}</b>
            <span className="wk-status">
              {s.days_opened} of {data.days} days · last {s.last}
            </span>
          </div>
        ))}
      </div>
      <p className="wk-rpe">Counting since {data.counting_since}. A surface missing here has not been opened.</p>
    </section>
  );
}
