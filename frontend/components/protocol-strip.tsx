"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

const SESSION_EPOCH = new Date("2025-09-01T00:00:00Z");

function sessionDay(): number {
  return Math.max(1, Math.ceil((Date.now() - SESSION_EPOCH.getTime()) / 86_400_000));
}

function tierLabel(tier: string | null | undefined, score: number | null): string {
  if (tier === "green") return "RECOVERY OPTIMAL";
  if (tier === "yellow") return "ADAPTIVE LOAD";
  if (tier === "red") return "RECOVERY";
  if (score != null) return score >= 67 ? "RECOVERY OPTIMAL" : score >= 34 ? "ADAPTIVE LOAD" : "RECOVERY";
  return "MONITORING";
}

function Sep() {
  return <span style={{ margin: "0 18px", color: "oklch(1 0 0 / 0.13)" }}>{"//"}</span>;
}

export function ProtocolStrip() {
  const { data } = useQuery({
    queryKey: ["daily-state"],
    queryFn: api.dailyState,
    staleTime: 5 * 60_000,
  });

  const score = data?.recovery?.score ?? null;
  const tier = data?.readiness?.tier ?? null;
  const acwr = data?.training_load?.acwr ?? null;
  const hrv_sigma = data?.recovery?.hrv_sigma ?? null;
  const push_pull = data?.training_load?.push_pull_ratio_28d ?? null;

  return (
    <div
      className="justify-start md:justify-center overflow-x-auto no-scrollbar px-4 md:px-0"
      style={{
        position: "relative",
        display: "flex",
        alignItems: "center",
        height: 30,
        borderTop: "1px solid var(--hairline)",
        borderBottom: "1px solid var(--hairline)",
        background: "oklch(0.11 0.006 250 / 0.55)",
        userSelect: "none",
      }}
    >
      <div className="sl-protocol-scan" aria-hidden />
      <span
        style={{
          position: "relative",
          zIndex: 1,
          fontFamily: "var(--font-geist-mono, monospace)",
          fontSize: 8.5,
          letterSpacing: "0.18em",
          color: "var(--text-faint)",
          textTransform: "uppercase",
          whiteSpace: "nowrap",
        }}
      >
        {tierLabel(tier, score)}
        <Sep />
        T:C RATIO {acwr != null ? acwr.toFixed(2) : "—"}
        <Sep />
        HRV {hrv_sigma != null ? `${hrv_sigma >= 0 ? "+" : ""}${hrv_sigma.toFixed(1)}σ` : "—"}
        {push_pull != null && (
          <>
            <Sep />
            PUSH:PULL {push_pull.toFixed(1)}
          </>
        )}
        <Sep />
        <span style={{ color: "var(--positive)", opacity: 0.65 }}>DATA ACQ: LIVE</span>
        <Sep />
        DAY {sessionDay()}
      </span>
    </div>
  );
}
