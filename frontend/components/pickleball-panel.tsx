"use client";

import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import {
  Bar,
  BarChart,
  Cell,
  Line,
  ComposedChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "@/lib/api";
import { Eyebrow } from "@/components/ui/metric";

function freshnessColor(recovery: number | null): string {
  if (recovery == null) return "var(--hairline-strong)";
  if (recovery >= 67) return "oklch(0.62 0.18 145 / 0.8)";
  if (recovery >= 34) return "oklch(0.65 0.16 80 / 0.8)";
  return "oklch(0.55 0.22 25 / 0.8)";
}

function HRVDeltaTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: { value: number | null }[];
  label?: string;
}) {
  if (!active || !payload?.length) return null;
  const delta = payload[0]?.value ?? null;
  if (delta == null) return null;
  return (
    <div
      style={{
        background: "var(--card-hover)",
        border: "1px solid var(--hairline-strong)",
        borderRadius: 8,
        padding: "8px 12px",
        fontSize: 11,
      }}
    >
      <div style={{ color: "var(--text-muted)", fontSize: 10.5, marginBottom: 3 }}>{label}</div>
      <div style={{ color: delta >= 0 ? "var(--positive)" : "var(--negative)" }}>
        HRV delta {delta >= 0 ? "+" : ""}{delta.toFixed(1)} ms
      </div>
      <div style={{ color: "var(--text-faint)", fontSize: 10 }}>next morning vs day-of</div>
    </div>
  );
}

export function PickleballPane() {
  const trend = useQuery({
    queryKey: ["pickleball-trend-90"],
    queryFn: () => api.pickleballTrend(90),
    refetchInterval: 15 * 60_000,
  });

  const data = trend.data;

  const { hrvDeltaSeries, freshnessData } = useMemo(() => {
    const sessions = data?.sessions ?? [];
    const hrv = sessions
      .filter((s) => s.hrv_delta != null)
      .map((s) => ({ date: s.date.slice(5), delta: s.hrv_delta }))
      .reverse();
    const freshness = sessions
      .filter((s) => s.recovery_day_of != null)
      .map((s) => ({
        date: s.date.slice(5),
        recovery: s.recovery_day_of,
        duration: s.duration_min,
      }))
      .reverse();
    return { hrvDeltaSeries: hrv, freshnessData: freshness };
  }, [data]);

  const avgHRVDelta = useMemo(() => {
    const deltas = data?.sessions.map((s) => s.hrv_delta).filter((d) => d != null) as number[];
    if (!deltas?.length) return null;
    return deltas.reduce((a, b) => a + b, 0) / deltas.length;
  }, [data]);

  if (trend.isLoading) {
    return (
      <div className="space-y-4">
        <div className="shc-skeleton h-[120px] rounded-lg" />
        <div className="shc-skeleton h-[80px] rounded-lg" />
      </div>
    );
  }

  const noData = !data || data.sessions.length === 0;

  return (
    <div className="space-y-6">
      <p className="shc-helptext">
        <span className="text-[var(--text-muted)]">4.5 → 5.0 lens. </span>
        The primary rate limiter isn't power — it's reset consistency and decision-making under
        fatigue. This panel tracks whether you're playing fresh or degraded, and whether your
        autonomic recovery is improving after pickleball sessions over time.
      </p>

      {/* Summary stats */}
      <div className="grid grid-cols-3 gap-2">
        {[
          {
            label: "Sessions",
            value: data?.total_sessions?.toString() ?? "—",
            sub: "last 90d",
          },
          {
            label: "Court time",
            value: data?.total_duration_min
              ? `${Math.round(data.total_duration_min / 60)}h`
              : "—",
            sub: "last 90d",
          },
          {
            label: "Play freshness",
            value: data?.avg_recovery_on_play_days?.toFixed(0) ?? "—",
            sub: "avg recovery on play days",
          },
        ].map((s) => (
          <div key={s.label} className="rounded-lg border border-[var(--hairline)] p-3 text-center">
            <Eyebrow>{s.label}</Eyebrow>
            <div className="mt-1 text-[18px] font-medium tabular-nums text-[var(--text-primary)]">
              {s.value}
            </div>
            <div className="text-[9.5px] text-[var(--text-faint)] mt-0.5">{s.sub}</div>
          </div>
        ))}
      </div>

      {noData ? (
        <div className="rounded-lg border border-[var(--hairline)] p-6 text-center">
          <p className="text-[12px] text-[var(--text-dim)]">
            No pickleball sessions in the last 90 days.
          </p>
          <p className="text-[10.5px] text-[var(--text-faint)] mt-1">
            Sessions are pulled from WHOOP workouts with "pickleball" modality.
          </p>
        </div>
      ) : (
        <>
          {/* Play freshness (recovery on court days) */}
          {freshnessData.length > 0 && (
            <div>
              <div className="flex items-baseline justify-between mb-2">
                <Eyebrow>Play freshness · recovery on court days</Eyebrow>
                {data?.avg_recovery_on_play_days != null && (
                  <span className="text-[10.5px] tabular-nums text-[var(--text-dim)]">
                    avg {data.avg_recovery_on_play_days.toFixed(0)}
                  </span>
                )}
              </div>
              <div className="h-[80px]">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={freshnessData} margin={{ top: 4, right: 8, left: -22, bottom: 0 }}>
                    <Bar dataKey="recovery" isAnimationActive={false} radius={[2, 2, 0, 0]}>
                      {freshnessData.map((entry, i) => (
                        <Cell key={i} fill={freshnessColor(entry.recovery)} />
                      ))}
                    </Bar>
                    <ReferenceLine y={67} stroke="oklch(0.62 0.16 145 / 0.4)" strokeDasharray="3 3" />
                    <ReferenceLine y={34} stroke="oklch(0.65 0.16 80 / 0.4)" strokeDasharray="3 3" />
                    <XAxis
                      dataKey="date"
                      tick={{ fontSize: 9.5, fill: "var(--text-faint)" }}
                      axisLine={false}
                      tickLine={false}
                      interval={Math.floor(freshnessData.length / 5) || 1}
                    />
                    <YAxis
                      domain={[0, 100]}
                      tick={{ fontSize: 9.5, fill: "var(--text-faint)" }}
                      axisLine={false}
                      tickLine={false}
                      width={30}
                    />
                    <Tooltip
                      contentStyle={{
                        background: "var(--card-hover)",
                        border: "1px solid var(--hairline-strong)",
                        borderRadius: 8,
                        fontSize: 11,
                      }}
                      formatter={(v: number) => [v.toFixed(0), "recovery"]}
                      cursor={false}
                    />
                  </BarChart>
                </ResponsiveContainer>
              </div>
              <div className="flex justify-between text-[8.5px] text-[var(--text-faint)] mt-1 px-[30px]">
                <span>34 yellow</span>
                <span>67 green</span>
              </div>
            </div>
          )}

          {/* HRV delta (next-day recovery after play) */}
          {hrvDeltaSeries.length > 0 && (
            <div>
              <div className="flex items-baseline justify-between mb-2">
                <Eyebrow>Post-play HRV delta · next-morning vs day-of</Eyebrow>
                {avgHRVDelta != null && (
                  <span
                    className="text-[10.5px] tabular-nums"
                    style={{ color: avgHRVDelta >= 0 ? "var(--positive)" : "var(--negative)" }}
                  >
                    avg {avgHRVDelta >= 0 ? "+" : ""}{avgHRVDelta.toFixed(1)} ms
                  </span>
                )}
              </div>
              <p className="shc-helptext mb-2">
                Positive = HRV recovered overnight (autonomic resilience improving).
                Consistently negative = pickleball volume is accumulating faster than you recover.
              </p>
              <div className="h-[100px]">
                <ResponsiveContainer width="100%" height="100%">
                  <ComposedChart data={hrvDeltaSeries} margin={{ top: 4, right: 8, left: -22, bottom: 0 }}>
                    <Bar dataKey="delta" isAnimationActive={false} radius={[2, 2, 0, 0]}>
                      {hrvDeltaSeries.map((entry, i) => (
                        <Cell
                          key={i}
                          fill={
                            (entry.delta ?? 0) >= 0
                              ? "oklch(0.62 0.18 145 / 0.75)"
                              : "oklch(0.55 0.22 25 / 0.75)"
                          }
                        />
                      ))}
                    </Bar>
                    <ReferenceLine y={0} stroke="var(--hairline-strong)" />
                    <XAxis
                      dataKey="date"
                      tick={{ fontSize: 9.5, fill: "var(--text-faint)" }}
                      axisLine={false}
                      tickLine={false}
                      interval={Math.floor(hrvDeltaSeries.length / 5) || 1}
                    />
                    <YAxis
                      tick={{ fontSize: 9.5, fill: "var(--text-faint)" }}
                      axisLine={false}
                      tickLine={false}
                      width={30}
                    />
                    <Tooltip content={<HRVDeltaTooltip />} cursor={false} />
                  </ComposedChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}
        </>
      )}

      {/* Tournament tracker */}
      <div>
        <div className="flex items-baseline justify-between mb-2">
          <Eyebrow>Tournament results · DUPR tracking</Eyebrow>
        </div>
        {!data?.tournaments || data.tournaments.length === 0 ? (
          <div
            className="rounded-lg border border-[var(--hairline)] p-4 text-center"
            style={{ borderStyle: "dashed" }}
          >
            <p className="text-[11px] text-[var(--text-dim)]">No tournaments logged yet.</p>
            <p className="text-[10px] text-[var(--text-faint)] mt-1">
              Add entries to the <code className="text-[var(--text-muted)]">tournament_events</code> table to track DUPR over time.
            </p>
          </div>
        ) : (
          <div className="rounded-lg border border-[var(--hairline)] overflow-hidden">
            <table className="w-full text-[12px] tabular-nums">
              <thead className="text-[10px] text-[var(--text-dim)] uppercase tracking-wider">
                <tr className="border-b border-[var(--hairline)]">
                  <th className="px-3 py-2 text-left font-normal">Date</th>
                  <th className="px-3 py-2 text-left font-normal">Event</th>
                  <th className="px-3 py-2 text-right font-normal">DUPR before</th>
                  <th className="px-3 py-2 text-right font-normal">DUPR after</th>
                  <th className="px-3 py-2 text-right font-normal">Δ</th>
                </tr>
              </thead>
              <tbody>
                {data.tournaments.map((t) => (
                  <tr key={t.id} className="border-b border-[var(--hairline)] last:border-b-0">
                    <td className="px-3 py-2 text-[var(--text-faint)]">{t.date.slice(5)}</td>
                    <td className="px-3 py-2 text-[var(--text-muted)]">{t.name}</td>
                    <td className="px-3 py-2 text-right">{t.dupr_before?.toFixed(2) ?? "—"}</td>
                    <td className="px-3 py-2 text-right">{t.dupr_after?.toFixed(2) ?? "—"}</td>
                    <td
                      className="px-3 py-2 text-right font-medium"
                      style={{
                        color:
                          t.dupr_delta == null
                            ? "var(--text-faint)"
                            : t.dupr_delta >= 0
                            ? "var(--positive)"
                            : "var(--negative)",
                      }}
                    >
                      {t.dupr_delta != null
                        ? `${t.dupr_delta >= 0 ? "+" : ""}${t.dupr_delta.toFixed(2)}`
                        : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <p className="text-[10px] text-[var(--text-faint)] leading-relaxed pt-2 border-t border-[var(--hairline)]">
        4.5→5.0 research: the primary physical separator at this level is hand speed (NVZ firefights)
        and reset consistency under pressure — not power or aerobic capacity. This panel tracks
        whether you're playing in a recovered state and whether autonomic resilience improves over time.
      </p>
    </div>
  );
}
