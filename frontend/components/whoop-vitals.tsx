"use client";

import { useQuery } from "@tanstack/react-query";
import { api, type DailyState, type OAuthStatus } from "@/lib/api";

function timeAgo(iso: string | null | undefined): string {
  if (!iso) return "—";
  const ts = new Date(iso).getTime();
  if (Number.isNaN(ts)) return "—";
  const mins = Math.max(0, Math.floor((Date.now() - ts) / 60_000));
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

function tone(score: number | null | undefined): string {
  if (score == null) return "var(--neutral)";
  if (score >= 67) return "var(--positive)";
  if (score >= 34) return "var(--neutral)";
  return "var(--negative)";
}

function strainColor(min: number | null): string {
  if (min == null) return "var(--text-faint)";
  if (min >= 90) return "var(--negative)";
  if (min >= 45) return "var(--neutral)";
  return "var(--positive)";
}

export function WhoopVitals() {
  const stateQ = useQuery({
    queryKey: ["daily-state"],
    queryFn: api.dailyState,
    staleTime: 5 * 60 * 1000,
  });
  const oauthQ = useQuery({
    queryKey: ["oauth-status"],
    queryFn: api.oauthStatus,
    refetchInterval: 60_000,
  });

  const state: DailyState | undefined = stateQ.data;
  const whoop: OAuthStatus | undefined = (oauthQ.data ?? []).find((s) => s.source === "whoop");

  const recovery = state?.recovery.score ?? null;
  const hrv = state?.recovery.hrv_ms ?? null;
  const rhr = state?.recovery.rhr ?? null;
  const sleepH = state?.sleep.last_hours ?? null;
  const deepPct = state?.sleep.deep_pct_last ?? null;
  const remMin = state?.sleep.rem_min_last ?? null;
  const cardioMin = state?.training_load.cardio_min_28d ?? null;
  const z2Min = state?.training_load.cardio_z2_min_7d ?? null;

  return (
    <div
      className="shc-card shc-enter overflow-hidden relative"
      style={{
        background:
          "linear-gradient(135deg, oklch(0.155 0 0) 0%, oklch(0.115 0 0) 60%, oklch(0.135 0.02 250) 100%)",
        borderColor: "oklch(1 0 0 / 0.10)",
      }}
    >
      {/* Subtle radial glow */}
      <div
        aria-hidden
        className="absolute -top-24 -right-24 w-[280px] h-[280px] rounded-full pointer-events-none"
        style={{
          background:
            "radial-gradient(circle, oklch(0.72 0.18 145 / 0.12) 0%, transparent 60%)",
        }}
      />

      <div className="relative px-5 pt-4 pb-5">
        {/* Header band */}
        <div className="flex items-center justify-between gap-4 mb-4">
          <div className="flex items-center gap-3">
            <span
              className="inline-block h-1.5 w-1.5 rounded-full animate-pulse"
              style={{ background: "var(--positive)" }}
            />
            <span
              className="text-[9.5px] tracking-[0.28em] uppercase"
              style={{
                fontFamily: "var(--font-orbitron)",
                color: "oklch(0.72 0 0)",
              }}
            >
              Powered by
            </span>
            <img
              src="/whoop-wordmark.svg"
              alt="WHOOP"
              className="h-[14px] w-auto"
              style={{ color: "var(--text-primary)", filter: "drop-shadow(0 0 12px oklch(0.72 0.18 145 / 0.25))" }}
            />
          </div>
          <div className="flex items-center gap-3 text-[10px] tabular-nums">
            <span
              className="px-2 py-0.5 rounded-sm border"
              style={{
                borderColor: whoop?.needs_reauth ? "var(--negative)" : "oklch(1 0 0 / 0.12)",
                color: whoop?.needs_reauth ? "var(--negative)" : "var(--text-muted)",
                background: whoop?.needs_reauth
                  ? "var(--negative-soft)"
                  : "oklch(1 0 0 / 0.02)",
              }}
            >
              {whoop?.needs_reauth ? "Reauth needed" : "Live"}
            </span>
            <span className="text-[var(--text-dim)]">
              synced{" "}
              <span className="text-[var(--text-muted)]">
                {timeAgo(whoop?.last_sync_at)}
              </span>
            </span>
          </div>
        </div>

        {/* KPI strip — Recovery / Strain / Sleep / Z2 */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          <div>
            <p
              className="text-[9px] uppercase tracking-[0.18em] text-[var(--text-dim)] mb-1"
              style={{ fontFamily: "var(--font-orbitron)" }}
            >
              Recovery
            </p>
            <div className="flex items-baseline gap-1">
              <span
                className="text-[36px] leading-none font-light tabular-nums"
                style={{
                  fontFamily: "var(--font-orbitron)",
                  color: tone(recovery),
                  textShadow: `0 0 24px ${tone(recovery)}40`,
                }}
              >
                {recovery != null ? Math.round(recovery) : "—"}
              </span>
              <span className="text-[11px] text-[var(--text-faint)]">/100</span>
            </div>
            <p className="text-[10px] text-[var(--text-faint)] mt-0.5 tabular-nums">
              {hrv != null ? `${hrv.toFixed(0)}ms HRV · ${rhr ?? "—"}bpm RHR` : "no data today"}
            </p>
          </div>

          <div>
            <p
              className="text-[9px] uppercase tracking-[0.18em] text-[var(--text-dim)] mb-1"
              style={{ fontFamily: "var(--font-orbitron)" }}
            >
              Strain · 7d
            </p>
            <div className="flex items-baseline gap-1">
              <span
                className="text-[36px] leading-none font-light tabular-nums"
                style={{
                  fontFamily: "var(--font-orbitron)",
                  color: strainColor(cardioMin),
                }}
              >
                {cardioMin != null ? Math.round(cardioMin / 4) : "—"}
              </span>
              <span className="text-[11px] text-[var(--text-faint)]">min/wk</span>
            </div>
            <p className="text-[10px] text-[var(--text-faint)] mt-0.5 tabular-nums">
              {z2Min != null ? `${Math.round(z2Min)} min in Z2 this week` : "—"}
            </p>
          </div>

          <div>
            <p
              className="text-[9px] uppercase tracking-[0.18em] text-[var(--text-dim)] mb-1"
              style={{ fontFamily: "var(--font-orbitron)" }}
            >
              Sleep
            </p>
            <div className="flex items-baseline gap-1">
              <span
                className="text-[36px] leading-none font-light tabular-nums"
                style={{
                  fontFamily: "var(--font-orbitron)",
                  color:
                    sleepH == null
                      ? "var(--text-faint)"
                      : sleepH >= 7.5
                        ? "var(--positive)"
                        : sleepH >= 6.5
                          ? "var(--neutral)"
                          : "var(--negative)",
                }}
              >
                {sleepH != null ? sleepH.toFixed(1) : "—"}
              </span>
              <span className="text-[11px] text-[var(--text-faint)]">h</span>
            </div>
            <p className="text-[10px] text-[var(--text-faint)] mt-0.5 tabular-nums">
              {deepPct != null
                ? `deep ${(deepPct * 100).toFixed(0)}% · REM ${remMin ?? "—"}m`
                : "no sleep data"}
            </p>
          </div>

          <div>
            <p
              className="text-[9px] uppercase tracking-[0.18em] text-[var(--text-dim)] mb-1"
              style={{ fontFamily: "var(--font-orbitron)" }}
            >
              HRV trend
            </p>
            <div className="flex items-baseline gap-1">
              <span
                className="text-[36px] leading-none font-light tabular-nums"
                style={{
                  fontFamily: "var(--font-orbitron)",
                  color:
                    state?.recovery.hrv_sigma == null
                      ? "var(--text-faint)"
                      : state.recovery.hrv_sigma >= 0
                        ? "var(--positive)"
                        : state.recovery.hrv_sigma >= -1
                          ? "var(--neutral)"
                          : "var(--negative)",
                }}
              >
                {state?.recovery.hrv_sigma != null
                  ? `${state.recovery.hrv_sigma >= 0 ? "+" : ""}${state.recovery.hrv_sigma.toFixed(1)}`
                  : "—"}
              </span>
              <span className="text-[11px] text-[var(--text-faint)]">σ</span>
            </div>
            <p className="text-[10px] text-[var(--text-faint)] mt-0.5 tabular-nums">
              {state?.recovery.hrv_baseline_28d != null
                ? `vs ${state.recovery.hrv_baseline_28d.toFixed(0)}ms baseline`
                : "—"}
              {state?.readiness.beta_blocker_adjusted && (
                <span className="text-[var(--neutral)] ml-1">· β-adj</span>
              )}
            </p>
          </div>
        </div>

        {/* Footer interpretation */}
        <p className="mt-4 pt-3 text-[10.5px] text-[var(--text-dim)] leading-snug border-t border-[oklch(1_0_0/0.06)]">
          <span className="text-[var(--text-muted)]">How to read this. </span>
          Recovery 67+ green-lights intensity. Strain (cardio min/wk) builds aerobic base; aim 150+ with ≥45 min in Z2. HRV σ tracks autonomic balance — look at the trend, not the absolute, especially on β-blocker days.
        </p>
      </div>
    </div>
  );
}
