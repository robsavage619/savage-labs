"use client";

import { useQuery } from "@tanstack/react-query";
import {
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  YAxis,
} from "recharts";
import { api } from "@/lib/api";
import { Eyebrow } from "@/components/ui/metric";

const KEY_LIFT_KEYWORDS = [
  "squat",
  "bench press",
  "deadlift",
  "overhead press",
  "military press",
  "row",
  "lat pulldown",
  "pull-up",
  "pullup",
];

function trendMeta(trend: string | null): {
  color: string;
  bg: string;
  border: string;
  arrow: string;
  label: string;
} {
  if (trend === "improving")
    return {
      color: "var(--positive)",
      bg: "oklch(0.62 0.18 145 / 0.08)",
      border: "oklch(0.62 0.18 145 / 0.25)",
      arrow: "↑",
      label: "climbing",
    };
  if (trend === "declining")
    return {
      color: "var(--negative)",
      bg: "oklch(0.55 0.22 25 / 0.08)",
      border: "oklch(0.55 0.22 25 / 0.25)",
      arrow: "↓",
      label: "declining",
    };
  return {
    color: "var(--text-dim)",
    bg: "transparent",
    border: "transparent",
    arrow: "→",
    label: "holding",
  };
}

// Shorten a long tournament name to its core identity
function shortEventName(name: string | null): string {
  if (!name) return "Unknown event";
  // Strip the long division/age suffix after " - "
  const trimmed = name.split(" by ")[0].split(" - ")[0].trim();
  // Also strip year prefix if it appears as "YYYY EventName"
  return trimmed.replace(/^\d{4}\s+/, "");
}

export function GoalScorecard() {
  const stateQ = useQuery({
    queryKey: ["daily-state"],
    queryFn: api.dailyState,
    refetchInterval: 5 * 60_000,
  });

  const dupr = useQuery({
    queryKey: ["pickleball-dupr"],
    queryFn: () => api.pickleballDupr(),
    refetchInterval: 60 * 60_000,
  });

  const matches = useQuery({
    queryKey: ["pickleball-matches"],
    queryFn: () => api.pickleballMatches(),
    refetchInterval: 60 * 60_000,
  });

  const progression = useQuery({
    queryKey: ["training-progression-all-8"],
    queryFn: () => api.trainingProgressionAll(8),
    refetchInterval: 30 * 60_000,
  });

  // ── DUPR ──────────────────────────────────────────────────────────────────
  const duprData = dupr.data;
  const current = duprData?.current?.doubles ?? null;
  const baseline = duprData?.baseline_doubles ?? null;
  const target = duprData?.target_doubles ?? 5.0;
  const snapshots = duprData?.snapshots ?? [];
  const sparkData = snapshots
    .filter((s) => s.doubles != null)
    .map((s) => ({ d: s.date.slice(5), v: s.doubles as number }));
  const gapClosed =
    current != null && baseline != null && target > baseline
      ? Math.max(0, Math.min(100, ((current - baseline) / (target - baseline)) * 100))
      : null;

  // Latest tournament context
  const allMatches = matches.data?.matches ?? [];
  const latestDate = allMatches[0]?.event_date ?? null;
  const tourneyMatches = allMatches.filter((m) => m.event_date === latestDate);
  const tourneyWins = tourneyMatches.filter((m) => m.won).length;
  const tourneyLosses = tourneyMatches.filter((m) => !m.won).length;
  const tourneyName = shortEventName(tourneyMatches[0]?.event_name ?? null);
  const tourneyRecovery = tourneyMatches[0]?.recovery_score ?? null;

  // ── Strength ──────────────────────────────────────────────────────────────
  const exercises = progression.data?.exercises ?? [];
  const keyLifts = exercises
    .filter((ex) =>
      KEY_LIFT_KEYWORDS.some((kw) => ex.exercise.toLowerCase().includes(kw)),
    )
    .slice(0, 5);

  // ── Body weight ──────────────────────────────────────────────────────────
  const state = stateQ.data;
  const bwKg = state?.checkin?.body_weight_kg ?? null;
  const bwLbs = bwKg != null ? bwKg * 2.20462 : null;
  const trendKgPerWk = state?.checkin?.body_weight_trend_4wk ?? null;
  const trendLbsPerWk = trendKgPerWk != null ? trendKgPerWk * 2.20462 : null;
  const bwStatus =
    trendLbsPerWk == null
      ? null
      : Math.abs(trendLbsPerWk) < 0.5
      ? {
          color: "var(--positive)",
          text: "Stable — concurrent training composition window open.",
        }
      : trendLbsPerWk > 0
      ? {
          color: "var(--text-muted)",
          text: "Gaining — muscle gain is fine; monitor if unintended fat gain.",
        }
      : {
          color: "var(--negative)",
          text: "Losing — protect muscle with adequate protein and kcal during heavy pickleball load.",
        };

  return (
    <div className="space-y-4">
      <p className="shc-helptext">
        Three north-star metrics for 2026: DUPR doubles toward 5.0, key compound e1RMs holding or
        climbing, bodyweight stable for concurrent training.
      </p>

      {/* ── DUPR Track ─────────────────────────────────────────────────────── */}
      <div
        className="rounded-lg border border-l-[3px] p-4 space-y-3"
        style={{
          borderColor: "var(--hairline)",
          borderLeftColor: "oklch(0.6 0.2 270)",
          background: "oklch(0.6 0.2 270 / 0.04)",
        }}
      >
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 mb-1">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src="/dupr-wordmark.png"
                alt="DUPR"
                className="h-[14px] w-auto"
                style={{ filter: "brightness(0) invert(1) opacity(0.55)" }}
              />
              <span className="text-[9px] uppercase tracking-widest text-[var(--text-faint)]">doubles · target 5.0</span>
            </div>
            <div className="flex items-baseline gap-3 mt-1.5">
              <span
                className="text-[32px] font-bold tabular-nums leading-none"
                style={{
                  color: "oklch(0.82 0.12 270)",
                  textShadow: "0 0 20px oklch(0.6 0.2 270 / 0.4)",
                }}
              >
                {current != null ? current.toFixed(3) : "—"}
              </span>
              <div className="flex flex-col gap-0.5">
                <span className="text-[12px] text-[var(--text-faint)]">
                  → {target.toFixed(1)} target
                </span>
                {current != null && (
                  <span className="text-[11px] font-medium" style={{ color: "oklch(0.6 0.2 270)" }}>
                    {(target - current).toFixed(3)} remaining
                  </span>
                )}
              </div>
            </div>
          </div>

          {sparkData.length > 1 && (
            <div className="h-[48px] w-[120px] shrink-0">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={sparkData} margin={{ top: 3, right: 3, left: 3, bottom: 3 }}>
                  <Line
                    type="monotone"
                    dataKey="v"
                    dot={false}
                    stroke="oklch(0.6 0.2 270)"
                    strokeWidth={2}
                    isAnimationActive={false}
                  />
                  <ReferenceLine
                    y={target}
                    stroke="oklch(0.6 0.2 270 / 0.3)"
                    strokeDasharray="3 3"
                  />
                  <YAxis
                    domain={[
                      (dataMin: number) => Math.max(0, dataMin - 0.05),
                      target + 0.1,
                    ]}
                    hide
                  />
                  <Tooltip
                    contentStyle={{
                      background: "var(--card-hover)",
                      border: "1px solid var(--hairline-strong)",
                      borderRadius: 6,
                      fontSize: 10,
                    }}
                    formatter={(v: number) => [v.toFixed(3), "DUPR"]}
                    labelFormatter={(l: string) => l}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>

        {/* Progress bar */}
        {gapClosed != null && (
          <div>
            <div className="flex justify-between text-[9.5px] text-[var(--text-faint)] mb-1.5">
              <span>baseline {baseline?.toFixed(3)}</span>
              <span>target {target.toFixed(1)}</span>
            </div>
            <div className="h-[6px] rounded-full bg-[var(--hairline-strong)] overflow-hidden">
              <div
                className="h-full rounded-full transition-all duration-700"
                style={{
                  width: `${gapClosed}%`,
                  background:
                    "linear-gradient(to right, oklch(0.55 0.2 270), oklch(0.7 0.18 200))",
                  minWidth: gapClosed > 0 ? "4px" : "0px",
                }}
              />
            </div>
            <div className="text-[9.5px] mt-1.5 text-right" style={{ color: "oklch(0.6 0.2 270)" }}>
              {gapClosed.toFixed(1)}% of gap closed
            </div>
          </div>
        )}

        {/* Latest tournament context */}
        {tourneyMatches.length > 0 && latestDate && (
          <div
            className="rounded-md px-3 py-2 flex items-center justify-between gap-2"
            style={{
              background: "oklch(0.6 0.2 270 / 0.07)",
              border: "1px solid oklch(0.6 0.2 270 / 0.2)",
            }}
          >
            <div>
              <div className="text-[10px] font-medium" style={{ color: "oklch(0.75 0.1 270)" }}>
                {shortEventName(tourneyMatches[0]?.event_name ?? null)}
              </div>
              <div className="text-[9.5px] text-[var(--text-faint)] mt-0.5">
                {new Date(latestDate + "T12:00:00").toLocaleDateString("en-US", {
                  month: "short",
                  day: "numeric",
                  year: "numeric",
                })}{" "}
                · {tourneyMatches[0]?.venue ?? ""}
              </div>
            </div>
            <div className="flex items-center gap-3 shrink-0 text-[11px] tabular-nums">
              <span style={{ color: "var(--positive)" }}>{tourneyWins}W</span>
              <span style={{ color: "var(--text-faint)" }}>·</span>
              <span style={{ color: "var(--negative)" }}>{tourneyLosses}L</span>
              {tourneyRecovery != null && (
                <>
                  <span style={{ color: "var(--text-faint)" }}>·</span>
                  <span
                    className="text-[10.5px]"
                    style={{
                      color:
                        tourneyRecovery >= 67
                          ? "var(--positive)"
                          : tourneyRecovery >= 34
                          ? "oklch(0.65 0.16 80)"
                          : "var(--negative)",
                    }}
                  >
                    {tourneyRecovery.toFixed(0)}% recovery
                  </span>
                </>
              )}
            </div>
          </div>
        )}

        {snapshots.length === 1 && (
          <p className="text-[10px] text-[var(--text-faint)] border-t border-[var(--hairline)] pt-2">
            First snapshot captured today. Trajectory builds as daily syncs accumulate.
          </p>
        )}
      </div>

      {/* ── Strength Hold Track ─────────────────────────────────────────────── */}
      <div className="rounded-lg border border-[var(--hairline)] overflow-hidden">
        <div className="px-4 pt-3 pb-2">
          <Eyebrow>Key compound e1RM · hold or climb</Eyebrow>
        </div>

        {progression.isLoading ? (
          <div className="shc-skeleton h-[80px] mx-4 mb-4 rounded" />
        ) : keyLifts.length === 0 ? (
          <p className="text-[11px] text-[var(--text-dim)] px-4 pb-4">
            No key compound lifts in the last 8 weeks.
          </p>
        ) : (
          <div>
            {keyLifts.map((ex, i) => {
              const { color, bg, border, arrow, label } = trendMeta(ex.trend);
              return (
                <div
                  key={ex.exercise}
                  className="flex items-center justify-between px-4 py-2.5"
                  style={{
                    background: bg,
                    borderTop: i === 0 ? "1px solid var(--hairline)" : "1px solid var(--hairline)",
                    borderLeft: `3px solid ${border}`,
                  }}
                >
                  <div className="text-[12px] text-[var(--text-muted)] leading-tight flex-1 min-w-0 truncate pr-3">
                    {ex.exercise}
                  </div>
                  <div className="flex items-center gap-3 shrink-0">
                    <span className="text-[16px] font-semibold tabular-nums text-[var(--text-primary)]">
                      {ex.e1rm_lbs != null ? `${ex.e1rm_lbs}` : "—"}
                      <span className="text-[10px] font-normal text-[var(--text-faint)] ml-0.5">
                        lbs
                      </span>
                    </span>
                    <span
                      className="text-[11px] font-medium tabular-nums w-[64px] text-right"
                      style={{ color }}
                    >
                      {arrow} {label}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* ── Body Weight Track ───────────────────────────────────────────────── */}
      {bwLbs != null && (
        <div
          className="rounded-lg border border-l-[3px] p-4 space-y-2"
          style={{
            borderColor: "var(--hairline)",
            borderLeftColor: bwStatus
              ? bwStatus.color
              : "var(--hairline)",
          }}
        >
          <Eyebrow>Body weight · concurrent training target: maintain</Eyebrow>
          <div className="flex items-baseline gap-3">
            <span className="text-[26px] font-bold tabular-nums text-[var(--text-primary)]">
              {bwLbs.toFixed(1)}
              <span className="text-[13px] font-normal text-[var(--text-faint)] ml-1">lbs</span>
            </span>
            {trendLbsPerWk != null && (
              <span
                className="text-[12px] tabular-nums font-medium"
                style={{ color: bwStatus?.color }}
              >
                {trendLbsPerWk >= 0 ? "+" : ""}
                {trendLbsPerWk.toFixed(1)} lbs/wk · 4wk trend
              </span>
            )}
          </div>
          {bwStatus && (
            <p className="text-[10.5px] leading-relaxed text-[var(--text-faint)]">
              {bwStatus.text}
            </p>
          )}
        </div>
      )}

      <p className="text-[10px] text-[var(--text-faint)] pt-1 border-t border-[var(--hairline)]">
        DUPR syncs daily at 05:30 from api.dupr.gg · Strength from Hevy · Body weight from morning check-in
      </p>
    </div>
  );
}
