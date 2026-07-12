"use client";

import { useQuery } from "@tanstack/react-query";
import { api, type DailyState, type OAuthStatus } from "@/lib/api";
import { WarningIcon } from "@/components/ui/icons";

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
  const skinTempDeltaF = state?.recovery.skin_temp_delta ?? null;
  const spo2Recovery = state?.recovery.spo2_pct ?? null;
  const userCalibrating = state?.recovery.user_calibrating ?? false;

  const sleepH = state?.sleep.last_hours ?? null;
  const deepPct = state?.sleep.deep_pct_last ?? null;
  const remMin = state?.sleep.rem_min_last ?? null;
  const efficiency = state?.sleep.efficiency_pct_last ?? null;
  const performance = state?.sleep.performance_pct_last ?? null;
  const consistency = state?.sleep.consistency_pct_last ?? null;
  const disturbances = state?.sleep.disturbance_count_last ?? null;
  const cycleCount = state?.sleep.sleep_cycle_count_last ?? null;
  const respRate = state?.sleep.respiratory_rate_last ?? null;
  const sleepDebtMin = state?.sleep.sleep_need_debt_min_last ?? null;

  const cardioMin = state?.training_load.cardio_min_28d ?? null;
  const z2Min = state?.training_load.cardio_z2_min_7d ?? null;

  // skin_temp_delta is already °F from the API.

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
              className="h-[18px] w-auto"
              style={{ filter: "drop-shadow(0 0 14px oklch(0.72 0.18 145 / 0.30))" }}
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

        {/* KPI strip — Strain + Sleep only; Recovery + HRV Trend are in header HUD and Recovery pillar */}
        <div className="grid grid-cols-2 gap-4">
          <div>
            <p
              className="text-[9px] uppercase tracking-[0.18em] text-[var(--text-dim)] mb-1"
              style={{ fontFamily: "var(--font-orbitron)" }}
            >
              Cardio volume · 7d avg
            </p>
            <div className="flex items-baseline gap-1">
              <span
                className="text-[36px] leading-none font-light tabular-nums"
                style={{ fontFamily: "var(--font-orbitron)", color: strainColor(cardioMin) }}
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
        </div>

        {/* Sleep architecture detail row — only shown when sleep data exists */}
        {sleepH != null && (
          <div className="mt-4 pt-3 border-t border-[oklch(1_0_0/0.06)]">
            <p
              className="text-[9px] uppercase tracking-[0.18em] text-[var(--text-dim)] mb-2"
              style={{ fontFamily: "var(--font-orbitron)" }}
            >
              Sleep Architecture
            </p>
            <div className="grid grid-cols-3 sm:grid-cols-6 gap-x-4 gap-y-2 text-[10.5px] tabular-nums">
              <SleepStat
                label="Performance"
                value={performance != null ? `${performance.toFixed(0)}%` : "—"}
                tone={performance != null && performance >= 85 ? "good" : performance != null && performance < 60 ? "bad" : "neutral"}
              />
              <SleepStat
                label="Efficiency"
                value={efficiency != null ? `${efficiency.toFixed(0)}%` : "—"}
                tone={efficiency != null && efficiency >= 85 ? "good" : efficiency != null && efficiency < 75 ? "bad" : "neutral"}
              />
              <SleepStat
                label="Consistency"
                value={consistency != null ? `${consistency.toFixed(0)}%` : "—"}
                tone={consistency != null && consistency >= 70 ? "good" : consistency != null && consistency < 50 ? "bad" : "neutral"}
              />
              <SleepStat
                label="Disturbances"
                value={disturbances != null ? `${disturbances}` : "—"}
                tone={disturbances != null && disturbances >= 12 ? "bad" : disturbances != null && disturbances <= 5 ? "good" : "neutral"}
              />
              <SleepStat
                label="Cycles"
                value={cycleCount != null ? `${cycleCount}` : "—"}
                tone="neutral"
              />
              <SleepStat
                label="Resp rate"
                value={respRate != null ? `${respRate.toFixed(1)}` : "—"}
                unit="bpm"
                tone="neutral"
              />
            </div>
            {(deepPct != null || remMin != null) && (
              <p className="mt-2 text-[10px] text-[var(--text-dim)] tabular-nums">
                Stages: deep {deepPct != null ? `${(deepPct * 100).toFixed(0)}%` : "—"}
                {" · "}REM {remMin != null ? `${remMin}m` : "—"}
                {sleepDebtMin != null && sleepDebtMin > 0 && (
                  <span className="ml-2 text-[var(--neutral)]">
                    · sleep debt {(sleepDebtMin / 60).toFixed(1)}h
                  </span>
                )}
              </p>
            )}
          </div>
        )}

        {/* Body / autonomic chips */}
        {(skinTempDeltaF != null || spo2Recovery != null || userCalibrating) && (
          <div className="mt-3 flex flex-wrap items-center gap-2 text-[10px] tabular-nums">
            {skinTempDeltaF != null && (
              <span
                className="px-2 py-0.5 rounded-sm border"
                style={{
                  borderColor: Math.abs(skinTempDeltaF) >= 0.9 ? "var(--negative)" : "oklch(1 0 0 / 0.10)",
                  color: Math.abs(skinTempDeltaF) >= 0.9 ? "var(--negative)" : "var(--text-muted)",
                  background: "oklch(1 0 0 / 0.02)",
                }}
              >
                Skin temp Δ {skinTempDeltaF >= 0 ? "+" : ""}{skinTempDeltaF.toFixed(1)}°F
              </span>
            )}
            {spo2Recovery != null && (
              <span
                className="px-2 py-0.5 rounded-sm border"
                style={{
                  borderColor: spo2Recovery < 92 ? "var(--negative)" : "oklch(1 0 0 / 0.10)",
                  color: spo2Recovery < 92 ? "var(--negative)" : "var(--text-muted)",
                  background: "oklch(1 0 0 / 0.02)",
                }}
              >
                SpO₂ {spo2Recovery.toFixed(1)}%
              </span>
            )}
            {userCalibrating && (
              <span
                className="px-2 py-0.5 rounded-sm border"
                style={{
                  borderColor: "var(--neutral)",
                  color: "var(--neutral)",
                  background: "var(--neutral-soft, oklch(0.5 0.05 80 / 0.15))",
                }}
              >
                <WarningIcon size={11} className="inline mr-1 align-middle" />WHOOP calibrating — score may be unreliable
              </span>
            )}
          </div>
        )}

        {/* Footer interpretation — collapsible */}
        <details className="mt-4 pt-3 border-t border-[oklch(1_0_0/0.06)] group">
          <summary className="text-[10.5px] cursor-pointer list-none text-[var(--text-faint)] hover:text-[var(--text-muted)] transition-colors select-none">
            <span className="group-open:hidden">▸ How to read this</span>
            <span className="hidden group-open:inline">▾ How to read this</span>
          </summary>
          <p className="mt-2 text-[10.5px] text-[var(--text-dim)] leading-snug">
            Recovery 67+ green-lights intensity. Sleep efficiency &lt;75% or disturbances ≥12 caps intensity to MODERATE even when HRV looks good — quality matters as much as duration. HRV σ tracks autonomic balance; trend over absolute, especially on β-blocker days.
          </p>
        </details>
      </div>
    </div>
  );
}

function SleepStat({
  label,
  value,
  unit,
  tone,
}: {
  label: string;
  value: string;
  unit?: string;
  tone: "good" | "bad" | "neutral";
}) {
  const color =
    tone === "good" ? "var(--positive)" : tone === "bad" ? "var(--negative)" : "var(--text-muted)";
  return (
    <div>
      <p className="text-[9px] uppercase tracking-[0.14em] text-[var(--text-dim)]">{label}</p>
      <p className="text-[14px] font-light leading-tight" style={{ color }}>
        {value}
        {unit && <span className="text-[10px] text-[var(--text-faint)] ml-0.5">{unit}</span>}
      </p>
    </div>
  );
}
