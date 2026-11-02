"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { Eyebrow } from "@/components/ui/metric";

const STATUS_COLOR: Record<string, string> = {
  "on track": "var(--positive)",
  review: "var(--warn)",
  "not measured": "var(--text-muted)",
};

/** The six pre-committed checks on whether the engine is helping (docs/evaluation.md). */
export function EngineScorecard() {
  const { data, isError, isLoading } = useQuery({
    queryKey: ["engine-scorecard"],
    queryFn: api.engineScorecard,
    refetchInterval: 30 * 60_000,
  });

  return (
    <div className="shc-card shc-enter p-6">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <Eyebrow>Monthly scorecard</Eyebrow>
        {data && (
          <span className="text-[11px] text-[var(--text-muted)]">
            Last 90 days · first review {data.first_review}
          </span>
        )}
      </div>
      {isError && <p className="mt-3 text-sm text-[var(--negative)]">Scorecard unavailable.</p>}
      {isLoading && <div className="shc-skeleton h-[150px] mt-3" />}
      {data && (
        <ul className="mt-3 divide-y divide-[var(--hairline)]">
          {data.metrics.map((m) => (
            <li key={m.key} className="flex items-baseline justify-between gap-3 py-2 text-[13px]">
              <span className="min-w-0">{m.label}</span>
              <span className="flex items-baseline gap-3 tabular-nums whitespace-nowrap">
                <span>{m.value == null ? "—" : `${m.value}${m.unit}`}</span>
                <span className="text-[11px] w-[80px] text-right" style={{ color: STATUS_COLOR[m.status] }}>
                  {m.status}
                </span>
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
