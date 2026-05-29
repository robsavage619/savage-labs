"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "@/lib/api";
import type { MiddaySession } from "@/lib/api";
import { Eyebrow } from "@/components/ui/metric";

type CopyState = "idle" | "copied" | "error";

// ── Type config ───────────────────────────────────────────────────────────────

const TYPE_CONFIG = {
  workout: {
    color: "var(--positive)",
    soft: "var(--positive-soft)",
    border: "oklch(0.72 0.18 145 / 0.25)",
    label: "WORKOUT",
    icon: "⚡",
  },
  recovery: {
    color: "var(--link)",
    soft: "oklch(0.18 0.04 240)",
    border: "oklch(0.55 0.18 240 / 0.3)",
    label: "RECOVERY",
    icon: "◈",
  },
  mixed: {
    color: "var(--neutral)",
    soft: "var(--neutral-soft)",
    border: "oklch(0.75 0.18 75 / 0.25)",
    label: "MIXED",
    icon: "◆",
  },
} as const;

const INTENSITY_LABEL: Record<string, string> = {
  high: "High",
  moderate: "Moderate",
  low: "Low",
  passive: "Passive",
};

// ── Activity list ─────────────────────────────────────────────────────────────

function ActivityRow({ activity, idx }: { activity: MiddaySession["activities"][number]; idx: number }) {
  return (
    <div
      className="flex gap-3 px-3 py-2.5 rounded-[var(--r-sm)]"
      style={{ background: "oklch(1 0 0 / 0.025)", border: "1px solid var(--hairline)" }}
    >
      <span className="text-[10.5px] text-[var(--text-faint)] w-4 text-center tabular-nums mt-0.5">
        {idx + 1}
      </span>
      <div className="flex-1 min-w-0">
        <div className="flex items-baseline gap-2 flex-wrap">
          <span className="text-[13px] font-medium text-[var(--text-primary)]">{activity.name}</span>
          <span className="text-[10.5px] text-[var(--text-faint)] tabular-nums">
            {activity.duration_min} min
          </span>
        </div>
        {activity.notes && (
          <p className="text-[11.5px] text-[var(--text-dim)] leading-snug mt-0.5">{activity.notes}</p>
        )}
      </div>
    </div>
  );
}

// ── Session display ───────────────────────────────────────────────────────────

function SessionDisplay({ session }: { session: MiddaySession }) {
  const cfg = TYPE_CONFIG[session.session_type] ?? TYPE_CONFIG.mixed;
  return (
    <div className="space-y-3">
      {/* Header badge */}
      <div
        className="rounded-[var(--r-md)] overflow-hidden"
        style={{ background: cfg.soft, border: `1px solid ${cfg.border}` }}
      >
        <div className="p-4 flex gap-3 items-start">
          <div
            className="w-10 h-10 rounded-full flex items-center justify-center text-sm font-bold flex-shrink-0"
            style={{ background: cfg.color, color: "oklch(0.1 0 0)" }}
          >
            {cfg.icon}
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex items-baseline gap-2 flex-wrap mb-1">
              <span className="text-[16px] font-semibold leading-none" style={{ color: cfg.color }}>
                {session.title}
              </span>
            </div>
            <div className="flex items-center gap-2 text-[10.5px] text-[var(--text-dim)] tabular-nums mb-2 flex-wrap">
              <span
                className="px-1.5 py-0.5 rounded text-[9.5px] font-semibold uppercase tracking-wide"
                style={{ background: cfg.color, color: "oklch(0.1 0 0)" }}
              >
                {cfg.label}
              </span>
              <span className="text-[var(--text-faint)]">•</span>
              <span>{session.duration_min} min</span>
              <span className="text-[var(--text-faint)]">•</span>
              <span>{INTENSITY_LABEL[session.intensity] ?? session.intensity} intensity</span>
            </div>
            <p className="text-[12px] text-[var(--text-muted)] leading-relaxed">{session.rationale}</p>
            {session.performance_goal && (
              <p className="text-[11px] text-[var(--text-dim)] leading-snug italic mt-1.5">
                <span className="text-[var(--text-faint)] not-italic font-semibold uppercase tracking-wider text-[9px] mr-1.5">
                  Goal
                </span>
                {session.performance_goal}
              </p>
            )}
          </div>
        </div>
      </div>

      {/* Activities */}
      <div>
        <Eyebrow className="mb-2">Activities</Eyebrow>
        <div className="space-y-1.5">
          {session.activities.map((a, i) => (
            <ActivityRow key={i} activity={a} idx={i} />
          ))}
        </div>
        <div className="mt-2 text-right text-[10.5px] text-[var(--text-faint)] tabular-nums">
          {session.activities.reduce((s, a) => s + a.duration_min, 0)} / {session.duration_min} min
        </div>
      </div>
    </div>
  );
}

// ── Generate prompt button ────────────────────────────────────────────────────

function GenerateButton({ onGenerated }: { onGenerated: () => void }) {
  const [state, setState] = useState<CopyState>("idle");

  const handleClick = async () => {
    setState("idle");
    try {
      const { prompt } = await api.middayContext();
      await navigator.clipboard.writeText(prompt);
      setState("copied");
      setTimeout(onGenerated, 2500);
    } catch {
      setState("error");
    }
    setTimeout(() => setState("idle"), 3000);
  };

  return (
    <div className="flex flex-col items-center gap-3 py-4">
      <div
        className="w-12 h-12 rounded-full flex items-center justify-center text-xl opacity-30"
        style={{ background: "oklch(1 0 0 / 0.04)", border: "1px solid var(--hairline)" }}
      >
        ◈
      </div>
      <p className="text-[12px] text-[var(--text-dim)] text-center leading-relaxed max-w-[240px]">
        No midday plan yet. Generate one to make the most of your Nike lunch hour.
      </p>
      <button
        onClick={handleClick}
        className="px-4 py-2 rounded-[var(--r-sm)] text-[12px] font-medium"
        style={{
          background: state === "copied" ? "var(--positive-soft)" : "oklch(1 0 0 / 0.06)",
          border: `1px solid ${state === "copied" ? "oklch(0.72 0.18 145 / 0.35)" : "var(--hairline)"}`,
          color: state === "copied" ? "var(--positive)" : "var(--text-primary)",
        }}
      >
        {state === "copied"
          ? "✓ Prompt copied — paste into Claude"
          : state === "error"
            ? "Failed — try again"
            : "Generate Midday Plan"}
      </button>
    </div>
  );
}

// ── Root card ─────────────────────────────────────────────────────────────────

export function MiddaySessionCard() {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["midday-session"],
    queryFn: api.middaySessionToday,
    refetchInterval: 60_000,
  });

  const session = data?.session ?? null;

  return (
    <div id="midday-session" className="shc-card shc-enter p-5">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/nike-swoosh.png" alt="Nike" className="h-5 w-auto opacity-90" />
          <div>
            <Eyebrow>Midday Session</Eyebrow>
            <h2 className="text-[15px] font-semibold text-[var(--text-primary)] mt-0.5">
              Nike Lunch Hour
            </h2>
          </div>
        </div>
        {session && (
          <button
            onClick={() => qc.invalidateQueries({ queryKey: ["midday-session"] })}
            className="text-[10.5px] text-[var(--text-faint)] hover:text-[var(--text-dim)] transition-colors"
            title="Refresh"
          >
            ↻
          </button>
        )}
      </div>

      {isLoading ? (
        <div className="text-[12px] text-[var(--text-faint)] py-4 text-center">Loading…</div>
      ) : session ? (
        <SessionDisplay session={session} />
      ) : (
        <GenerateButton onGenerated={() => qc.invalidateQueries({ queryKey: ["midday-session"] })} />
      )}
    </div>
  );
}
