"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

const SESSION_EPOCH = new Date("2025-09-01T00:00:00Z");

function sessionDay(): number {
  return Math.max(1, Math.ceil((Date.now() - SESSION_EPOCH.getTime()) / 86_400_000));
}

function protocolLabel(score: number | null): string {
  if (score == null) return "MONITORING";
  if (score >= 67) return "PEAK OUTPUT";
  if (score >= 34) return "ADAPTIVE LOAD";
  return "RECOVERY";
}

function Sep() {
  return (
    <span style={{ margin: "0 18px", color: "oklch(1 0 0 / 0.13)" }}>//</span>
  );
}

export function ProtocolStrip() {
  const { data } = useQuery({
    queryKey: ["daily-state"],
    queryFn: api.dailyState,
    staleTime: 5 * 60_000,
  });

  const score = data?.recovery?.score ?? null;

  return (
    <div
      style={{
        position: "relative",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        height: 30,
        borderTop: "1px solid var(--hairline)",
        borderBottom: "1px solid var(--hairline)",
        background: "oklch(0.11 0.006 250 / 0.55)",
        overflow: "hidden",
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
        SUBJECT: ROB-01
        <Sep />
        PROTOCOL: {protocolLabel(score)}
        <Sep />
        SESSION DAY {sessionDay()}
        <Sep />
        <span style={{ color: "var(--positive)", opacity: 0.65 }}>DATA ACQ: LIVE</span>
      </span>
    </div>
  );
}
