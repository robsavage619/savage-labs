"use client";

import { useEffect } from "react";
import { XIcon } from "@/components/ui/icons";
import { useQuery } from "@tanstack/react-query";
import {
  ComposedChart,
  Line,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
} from "recharts";
import { api } from "@/lib/api";
import { Eyebrow } from "@/components/ui/metric";

function epleyKg(weightKg: number, reps: number): number {
  return weightKg * (1 + reps / 30);
}

interface Props {
  exercise: string | null;
  onClose: () => void;
}

export function ProgressionDrawer({ exercise, onClose }: Props) {
  useEffect(() => {
    if (!exercise) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [exercise, onClose]);

  const { data, isLoading } = useQuery({
    queryKey: ["progression", exercise],
    queryFn: () => api.trainingProgression(exercise!, 30),
    enabled: !!exercise,
    staleTime: 5 * 60 * 1000,
  });

  if (!exercise) return null;

  const sessions = (data?.history ?? []).slice().reverse();
  const points = sessions.map((s) => {
    // Average reps per set is the right number to plug into Epley.
    const avgReps = s.work_sets > 0 ? Math.max(1, Math.round(s.total_reps / s.work_sets)) : 5;
    return {
      date: s.date.slice(5),
      max_lbs: s.max_lbs,
      vol_lbs: +(s.volume_kg * 2.20462).toFixed(0),
      est_1rm_lbs: +(epleyKg(s.max_kg, avgReps) * 2.20462).toFixed(1),
      avg_rpe: s.avg_rpe,
      raw: s,
    };
  });

  const latest = points.at(-1);
  const ago90 = points.find((_, i) => i === Math.max(0, points.length - 8));
  const delta90 =
    latest && ago90 ? latest.est_1rm_lbs - ago90.est_1rm_lbs : null;

  return (
    <div
      className="fixed inset-0 z-50 flex justify-end"
      style={{ background: "oklch(0 0 0 / 0.55)" }}
      onClick={onClose}
    >
      <aside
        className="h-full w-full max-w-[560px] overflow-y-auto p-6 space-y-5"
        style={{ background: "var(--card)", borderLeft: "1px solid var(--hairline-strong)" }}
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-start justify-between gap-3">
          <div>
            <Eyebrow>Progression</Eyebrow>
            <h2 className="text-[16px] font-semibold text-[var(--text-primary)] mt-0.5">{exercise}</h2>
            {latest && (
              <p className="text-[11px] text-[var(--text-muted)] tabular-nums mt-1">
                est-1RM <span className="text-[var(--text-primary)] font-medium">{latest.est_1rm_lbs.toFixed(0)} lbs</span>
                {delta90 != null && (
                  <span
                    className="ml-2 font-medium"
                    style={{
                      color:
                        delta90 > 5 ? "var(--positive)"
                          : delta90 < -5 ? "var(--negative)"
                            : "var(--neutral)",
                    }}
                  >
                    {delta90 >= 0 ? "+" : ""}{delta90.toFixed(0)} lbs vs 8 sessions ago
                  </span>
                )}
              </p>
            )}
          </div>
          <button
            onClick={onClose}
            className="rounded-md p-1.5 text-[var(--text-faint)] hover:text-[var(--text-primary)] hover:bg-[var(--card-hover)] transition-colors"
            aria-label="Close"
          >
            <XIcon size={14} />
          </button>
        </header>

        {isLoading && (
          <div className="space-y-3">
            <div className="h-[200px] shc-skeleton rounded" />
            <div className="h-[140px] shc-skeleton rounded" />
          </div>
        )}

        {!isLoading && points.length === 0 && (
          <p className="text-[12px] text-[var(--text-muted)]">No history found for this exercise.</p>
        )}

        {!isLoading && points.length > 0 && (
          <>
            <section>
              <div className="flex items-baseline justify-between mb-2">
                <Eyebrow>Estimated 1RM · last {points.length} sessions</Eyebrow>
                <span className="text-[10px] text-[var(--text-faint)]">Epley formula</span>
              </div>
              <div className="h-[220px]">
                <ResponsiveContainer width="100%" height="100%">
                  <ComposedChart data={points} margin={{ top: 8, right: 12, left: -10, bottom: 0 }}>
                    <defs>
                      <linearGradient id="prog-fill" x1="0" x2="0" y1="0" y2="1">
                        <stop offset="0%" stopColor="var(--chart-line)" stopOpacity="0.3" />
                        <stop offset="100%" stopColor="var(--chart-line)" stopOpacity="0" />
                      </linearGradient>
                    </defs>
                    <XAxis dataKey="date" tick={{ fontSize: 9.5, fill: "var(--text-faint)" }} axisLine={false} tickLine={false} />
                    <YAxis tick={{ fontSize: 9.5, fill: "var(--text-faint)" }} axisLine={false} tickLine={false} width={36} />
                    <Tooltip
                      contentStyle={{ background: "var(--card-hover)", border: "1px solid var(--hairline-strong)", borderRadius: 8, fontSize: 11 }}
                      cursor={{ stroke: "var(--hairline-strong)" }}
                    />
                    <Area dataKey="est_1rm_lbs" stroke="var(--chart-line)" strokeWidth={1.8} fill="url(#prog-fill)" dot={false} isAnimationActive={false} name="est 1RM (lbs)" />
                    <Line dataKey="max_lbs" stroke="var(--neutral)" strokeWidth={1.2} strokeDasharray="3 3" dot={false} isAnimationActive={false} name="top set (lbs)" />
                  </ComposedChart>
                </ResponsiveContainer>
              </div>
            </section>

            <section>
              <Eyebrow>Recent sessions</Eyebrow>
              <div className="mt-2 rounded-lg border border-[var(--hairline)] overflow-hidden">
                <table className="w-full text-[12px]">
                  <thead className="text-[10px] text-[var(--text-faint)] uppercase tracking-wider" style={{ borderBottom: "1px solid var(--hairline)" }}>
                    <tr>
                      <th className="px-3 py-2 text-left font-normal">Date</th>
                      <th className="px-3 py-2 text-right font-normal">Top set</th>
                      <th className="px-3 py-2 text-right font-normal">Sets</th>
                      <th className="px-3 py-2 text-right font-normal">Volume</th>
                      <th className="px-3 py-2 text-right font-normal">RPE</th>
                      <th className="px-3 py-2 text-right font-normal">est 1RM</th>
                    </tr>
                  </thead>
                  <tbody>
                    {points.slice().reverse().map((p, i) => (
                      <tr key={i} style={{ borderBottom: i < points.length - 1 ? "1px solid var(--hairline)" : "none" }}>
                        <td className="px-3 py-2 text-[var(--text-muted)]">{p.date}</td>
                        <td className="px-3 py-2 text-right tabular-nums text-[var(--text-primary)] font-medium">{p.max_lbs.toFixed(0)} <span className="text-[var(--text-faint)] font-normal text-[10px]">lbs</span></td>
                        <td className="px-3 py-2 text-right tabular-nums text-[var(--text-muted)]">{p.raw.work_sets}</td>
                        <td className="px-3 py-2 text-right tabular-nums text-[var(--text-muted)]">{(p.vol_lbs / 1000).toFixed(1)}k</td>
                        <td className="px-3 py-2 text-right tabular-nums text-[var(--text-muted)]">{p.avg_rpe ? p.avg_rpe.toFixed(1) : "—"}</td>
                        <td className="px-3 py-2 text-right tabular-nums text-[var(--text-primary)]">{p.est_1rm_lbs.toFixed(0)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          </>
        )}
      </aside>
    </div>
  );
}
