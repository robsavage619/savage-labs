"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { Eyebrow } from "@/components/ui/metric";

const VERDICT_STYLE: Record<string, { color: string; arrow: string; label: string }> = {
  drop: { color: "var(--negative)", arrow: "↓", label: "drop" },
  progress: { color: "var(--positive)", arrow: "↑", label: "progress" },
  repeat: { color: "var(--text-primary)", arrow: "→", label: "repeat" },
  no_plan_target: { color: "var(--text-muted)", arrow: "·", label: "—" },
};

export function AfterActionPanel() {
  const { data, isLoading } = useQuery({
    queryKey: ["after-action"],
    queryFn: api.afterAction,
    refetchInterval: 5 * 60_000,
  });

  if (isLoading) {
    return (
      <div className="shc-card shc-enter p-5">
        <Eyebrow>After-action · last session</Eyebrow>
        <div className="shc-skeleton h-[120px] mt-3" />
      </div>
    );
  }

  if (!data || !data.session_date || data.exercises.length === 0) {
    return (
      <div className="shc-card shc-enter p-5">
        <Eyebrow>After-action · last session</Eyebrow>
        <p className="text-[12px] text-[var(--text-dim)] mt-3">
          No completed sets in Hevy yet. After your next session syncs, this surface will
          show per-exercise RPE/rep results vs. plan and the suggested next-session weights.
        </p>
      </div>
    );
  }

  const sessionLabel =
    data.days_ago === 0
      ? "today"
      : data.days_ago === 1
      ? "yesterday"
      : `${data.days_ago}d ago`;

  return (
    <div className="shc-card shc-enter p-5">
      <div className="flex items-baseline justify-between flex-wrap gap-3">
        <Eyebrow>After-action · last session</Eyebrow>
        <span className="text-[10.5px] text-[var(--text-dim)] tabular-nums">
          {data.session_date} · {sessionLabel}
          {!data.has_plan && (
            <span className="ml-2 text-[var(--text-faint)]">no plan on file — log RPE in Hevy for full autoreg</span>
          )}
        </span>
      </div>

      <div className="mt-3 overflow-x-auto">
        <table className="w-full text-[12px]">
          <thead>
            <tr className="text-[10px] text-[var(--text-dim)] uppercase tracking-wider">
              <th className="text-left py-1.5 font-normal">Exercise</th>
              <th className="text-right py-1.5 font-normal">Sets</th>
              <th className="text-right py-1.5 font-normal">Reps</th>
              <th className="text-right py-1.5 font-normal">Load</th>
              <th className="text-right py-1.5 font-normal">RPE</th>
              <th className="text-right py-1.5 font-normal">Next session</th>
            </tr>
          </thead>
          <tbody>
            {data.exercises.map((ex) => {
              const v = VERDICT_STYLE[ex.verdict] ?? VERDICT_STYLE.repeat;
              return (
                <tr
                  key={ex.exercise}
                  className="border-t border-[var(--hairline)] hover:bg-[oklch(1_0_0/0.02)]"
                  title={ex.reason}
                >
                  <td className="py-1.5 text-[var(--text-primary)]">
                    {ex.exercise}
                    {ex.block && (
                      <span className="text-[10px] text-[var(--text-dim)] ml-2 uppercase tracking-wider">
                        {ex.block}
                      </span>
                    )}
                  </td>
                  <td className="text-right py-1.5 tabular-nums text-[var(--text-muted)]">
                    {ex.sets}
                    {ex.target_reps != null && (
                      <span className="text-[var(--text-faint)]"> / {ex.target_reps}</span>
                    )}
                  </td>
                  <td className="text-right py-1.5 tabular-nums text-[var(--text-muted)]">
                    {ex.min_reps != null && ex.avg_reps != null && ex.min_reps !== Math.round(ex.avg_reps)
                      ? `${ex.min_reps}–${Math.round(ex.avg_reps)}`
                      : ex.avg_reps != null
                      ? Math.round(ex.avg_reps)
                      : "—"}
                  </td>
                  <td className="text-right py-1.5 tabular-nums text-[var(--text-muted)]">
                    {ex.actual_weight_lbs != null ? Math.round(ex.actual_weight_lbs) : "—"}
                    {ex.target_weight_lbs != null && ex.actual_weight_lbs != null && Math.abs(ex.actual_weight_lbs - ex.target_weight_lbs) >= 2.5 && (
                      <span className="text-[10px] text-[var(--text-faint)] ml-1">/ {ex.target_weight_lbs}</span>
                    )}
                    <span className="text-[10px] text-[var(--text-faint)]"> lbs</span>
                  </td>
                  <td className="text-right py-1.5 tabular-nums">
                    {ex.avg_rpe != null ? (
                      <span style={{
                        color: ex.target_rpe != null && ex.avg_rpe > ex.target_rpe + 1
                          ? "var(--negative)"
                          : ex.target_rpe != null && ex.avg_rpe < ex.target_rpe - 1
                          ? "var(--positive)"
                          : "var(--text-muted)",
                      }}>
                        {ex.avg_rpe.toFixed(1)}
                      </span>
                    ) : (
                      <span className="text-[var(--text-faint)]">—</span>
                    )}
                    {ex.target_rpe != null && (
                      <span className="text-[10px] text-[var(--text-faint)]"> / {ex.target_rpe}</span>
                    )}
                  </td>
                  <td className="text-right py-1.5 tabular-nums">
                    <span style={{ color: v.color }} className="font-medium">
                      {v.arrow}{" "}
                      {ex.next_session_lbs != null
                        ? `${ex.next_session_lbs}`
                        : ex.target_weight_lbs ?? ex.actual_weight_lbs ?? "—"}
                    </span>
                    {ex.delta_pct !== 0 && (
                      <span className="text-[10px] text-[var(--text-faint)] ml-1">
                        ({ex.delta_pct > 0 ? "+" : ""}{ex.delta_pct}%)
                      </span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <p className="mt-4 pt-3 text-[10.5px] text-[var(--text-dim)] leading-snug border-t border-[var(--hairline)]">
        <span className="text-[var(--text-muted)]">How to read this. </span>
        Reads what you logged in Hevy and emits a next-session suggestion per exercise. Avg RPE ≥ target+2 cuts
        10%; RPE ≥ target+1 cuts 5%; rep miss ≥2 cuts 5%; RPE ≤ target−2 adds 2.5%. Hover any row for the reason.
        Logging RPE on every Hevy set unlocks the full signal — without it the suggestion falls back to plan-vs-actual reps only.
      </p>
    </div>
  );
}
