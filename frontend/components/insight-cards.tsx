"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";

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
