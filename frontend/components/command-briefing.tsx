"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api, type Briefing, type DailyState } from "@/lib/api";
import { Eyebrow, Dot } from "@/components/ui/metric";

/**
 * Decision-first command briefing.
 *
 * Replaces the previous 6-slot metric ribbon with a single "Today's Move"
 * card: one verdict, one why, one CTA. The 6 vitals are demoted to a
 * collapsed row that expands on click. Readiness, HRV-σ, ACWR, and the
 * β-blocker reweighting all come from the canonical /api/state/today —
 * no client-side recomputation, no drift versus the LLM's view.
 */

const CALL_COLOR: Record<string, string> = {
  Push: "var(--positive)",
  Train: "var(--positive)",
  Maintain: "var(--neutral)",
  Easy: "var(--neutral)",
  Rest: "var(--negative)",
};

function tier(score: number | null | undefined): "positive" | "neutral" | "negative" {
  if (score == null) return "neutral";
  if (score >= 67) return "positive";
  if (score >= 34) return "neutral";
  return "negative";
}

function verdict(score: number | null | undefined): string {
  if (score == null) return "Awaiting data";
  if (score >= 80) return "Train hard";
  if (score >= 67) return "Push it";
  if (score >= 50) return "Moderate";
  if (score >= 34) return "Active recovery";
  return "Rest & restore";
}

function tierColor(t: "positive" | "neutral" | "negative") {
  return t === "positive" ? "var(--positive)" : t === "negative" ? "var(--negative)" : "var(--neutral)";
}

function scrollToPlan() {
  const el = document.getElementById("next-workout");
  if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
}

function VitalCell({
  label,
  value,
  unit,
  sub,
  tone = "neutral",
}: {
  label: string;
  value: string;
  unit?: string;
  sub?: string;
  tone?: "positive" | "neutral" | "negative";
}) {
  return (
    <div className="px-3 py-2 border-r border-[var(--hairline)] last:border-r-0 min-w-[110px]">
      <Eyebrow>{label}</Eyebrow>
      <div className="mt-0.5 flex items-baseline gap-1">
        <span className="metric-md tabular-nums" style={{ color: tierColor(tone) }}>{value}</span>
        {unit && <span className="text-[10px] text-[var(--text-dim)]">{unit}</span>}
      </div>
      {sub && <p className="mt-px text-[10px] text-[var(--text-muted)] tabular-nums">{sub}</p>}
    </div>
  );
}

export function CommandBriefing() {
  const [vitalsOpen, setVitalsOpen] = useState(false);

  const stateQ = useQuery({
    queryKey: ["daily-state"],
    queryFn: api.dailyState,
    refetchInterval: 5 * 60 * 1000,
  });
  const briefingQ = useQuery({
    queryKey: ["briefing"],
    queryFn: api.briefing,
    refetchInterval: 10 * 60 * 1000,
    staleTime: 5 * 60 * 1000,
  });

  if (stateQ.isLoading || !stateQ.data) {
    return (
      <div className="shc-card overflow-hidden">
        <div className="px-5 py-5">
          <div className="shc-skeleton h-[26px] w-[160px] mb-2 !rounded" />
          <div className="shc-skeleton h-[14px] w-[260px] !rounded" />
        </div>
      </div>
    );
  }

  const state: DailyState = stateQ.data;
  const r = state.readiness;
  const rec = state.recovery;
  const sleep = state.sleep;
  const load = state.training_load;
  const gates = state.gates;
  const fresh = state.freshness;

  const score = r.score;
  const t = tier(score);
  const v = verdict(score);
  const briefing =
    briefingQ.data && "training_call" in briefingQ.data ? (briefingQ.data as Briefing) : null;

  // The "why" — one sentence, real numbers, gates inline.
  const whyParts: string[] = [];
  if (rec.hrv_sigma != null) whyParts.push(`HRV ${rec.hrv_sigma >= 0 ? "+" : ""}${rec.hrv_sigma.toFixed(1)}σ`);
  if (rec.score != null) whyParts.push(`recovery ${Math.round(rec.score)}`);
  if (load.acwr != null) whyParts.push(`ACWR ${load.acwr.toFixed(2)}`);
  if (sleep.last_hours != null) whyParts.push(`sleep ${sleep.last_hours.toFixed(1)}h`);
  const why = whyParts.join(" · ");

  return (
    <div className="shc-card shc-enter overflow-hidden">
      {/* Headline: verdict + why + CTA */}
      <div className="px-5 py-4 flex items-center gap-4 flex-wrap">
        <div className="flex items-center gap-3 flex-[1.4] min-w-[200px]">
          <Dot tone={t} />
          <div className="min-w-0">
            <Eyebrow>Today · Verdict</Eyebrow>
            <p
              className="mt-0.5 text-[22px] font-medium tracking-tight leading-none"
              style={{ color: tierColor(t) }}
            >
              {v}
            </p>
          </div>
        </div>

        <div className="flex-1 min-w-0">
          <Eyebrow>Why</Eyebrow>
          <p className="mt-0.5 text-[14px] text-[var(--text-primary)] leading-snug tabular-nums">
            {why || "Insufficient data for a verdict — sync sources to populate."}
          </p>
          {r.beta_blocker_adjusted && (
            <span
              className="inline-block mt-1 text-[9.5px] font-medium uppercase tracking-wider px-1.5 py-px rounded-sm"
              style={{
                color: "var(--neutral)",
                background: "var(--neutral-soft)",
                border: "1px solid oklch(0.75 0.18 75 / 0.25)",
              }}
              title="HRV signal blunted by beta-blocker; readiness composite re-weighted toward sleep + RHR + subjective"
            >
              β-blocker adj
            </span>
          )}
        </div>

        <button type="button" onClick={scrollToPlan} className="btn btn-secondary shrink-0">
          Today's plan ↓
        </button>
      </div>

      {/* Auto-regulation gates — inline coloured strip when active */}
      {gates.reasons.length > 0 && (
        <div
          className="px-5 py-2 border-t border-[var(--hairline)] flex items-start gap-3"
          style={{
            borderLeft: `3px solid ${tierColor(t)}`,
            background: "var(--surface-1)",
          }}
        >
          <span className="text-[10px] uppercase tracking-wider text-[var(--text-dim)] mt-px shrink-0">
            Gates
          </span>
          <div className="flex-1 min-w-0">
            <p className="text-[12px] text-[var(--text-primary)] leading-snug">
              Max intensity {gates.max_intensity.toUpperCase()}
              {gates.forbid_muscle_groups.length > 0 && (
                <> · skip {gates.forbid_muscle_groups.join(", ")}</>
              )}
              {gates.deload_required && <> · deload required</>}
              {gates.hr_zone_shift_bpm > 0 && <> · HR −{gates.hr_zone_shift_bpm} bpm</>}
            </p>
            <p className="text-[10.5px] text-[var(--text-muted)] mt-0.5">
              {gates.reasons.join(" · ")}
            </p>
          </div>
        </div>
      )}

      {/* Coaching note — promoted to primary text per design review */}
      {briefing && (
        <div className="px-5 py-3 border-t border-[var(--hairline)]">
          <div className="flex items-baseline gap-3 mb-1">
            <span
              className="text-[11px] font-semibold uppercase tracking-wider"
              style={{ color: CALL_COLOR[briefing.training_call] ?? "var(--text-primary)" }}
            >
              {briefing.training_call}
            </span>
            <span className="text-[11px] text-[var(--text-dim)]">{briefing.readiness_headline}</span>
            <span className="ml-auto text-[10px] text-[var(--text-faint)] tabular-nums">
              {new Date(briefing.generated_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
            </span>
          </div>
          <p className="text-[13.5px] text-[var(--text-primary)] leading-relaxed">
            {briefing.coaching_note}
          </p>
          {briefing.flags.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {briefing.flags.map((f, i) => (
                <span
                  key={i}
                  className="rounded-full border border-[var(--hairline)] px-2 py-0.5 text-[9.5px] text-[var(--text-dim)]"
                >
                  {f}
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Vitals — collapsed by default, expands on click */}
      <button
        type="button"
        onClick={() => setVitalsOpen((o) => !o)}
        className="w-full px-5 py-2 border-t border-[var(--hairline)] flex items-center gap-2 text-left hover:bg-[var(--card-hover)] transition-colors"
      >
        <span className="text-[10px] uppercase tracking-wider text-[var(--text-dim)]">Vitals</span>
        <span className="text-[11px] text-[var(--text-muted)] tabular-nums">
          {[
            r.score != null ? `Readiness ${Math.round(r.score)}` : null,
            rec.score != null ? `Recovery ${Math.round(rec.score)}` : null,
            rec.hrv_ms != null ? `HRV ${rec.hrv_ms.toFixed(0)}ms` : null,
            sleep.last_hours != null ? `Sleep ${sleep.last_hours.toFixed(1)}h` : null,
          ]
            .filter(Boolean)
            .join("  ·  ")}
        </span>
        <span className="ml-auto text-[10px] text-[var(--text-dim)]">{vitalsOpen ? "▴" : "▾"}</span>
      </button>

      {vitalsOpen && (
        <div className="flex flex-wrap border-t border-[var(--hairline)]">
          <VitalCell
            label="Readiness"
            value={r.score != null ? String(Math.round(r.score)) : "—"}
            tone={tier(r.score)}
            sub={r.beta_blocker_adjusted ? "β-adj composite" : "composite"}
          />
          <VitalCell
            label="Recovery"
            value={rec.score != null ? String(Math.round(rec.score)) : "—"}
            tone={tier(rec.score)}
            sub={rec.score_date ? new Date(rec.score_date).toLocaleDateString([], { month: "short", day: "numeric" }) : undefined}
          />
          <VitalCell
            label="HRV"
            value={rec.hrv_ms ? rec.hrv_ms.toFixed(0) : "—"}
            unit="ms"
            tone={rec.hrv_sigma == null ? "neutral" : rec.hrv_sigma >= -0.5 ? "positive" : rec.hrv_sigma >= -1.5 ? "neutral" : "negative"}
            sub={rec.hrv_sigma != null ? `${rec.hrv_sigma >= 0 ? "+" : ""}${rec.hrv_sigma.toFixed(2)}σ` : undefined}
          />
          <VitalCell
            label="RHR"
            value={rec.rhr ? String(rec.rhr) : "—"}
            unit="bpm"
            sub={rec.rhr_elevated_pct != null ? `${rec.rhr_elevated_pct >= 0 ? "+" : ""}${rec.rhr_elevated_pct.toFixed(1)}%` : undefined}
            tone={rec.rhr_elevated_pct == null ? "neutral" : rec.rhr_elevated_pct > 5 ? "negative" : rec.rhr_elevated_pct < -2 ? "positive" : "neutral"}
          />
          <VitalCell
            label="Sleep"
            value={sleep.last_hours ? sleep.last_hours.toFixed(1) : "—"}
            unit="h"
            sub={sleep.deep_pct_last != null ? `deep ${(sleep.deep_pct_last * 100).toFixed(0)}%` : sleep.avg_7d ? `${sleep.avg_7d.toFixed(1)}h 7d` : undefined}
            tone={sleep.last_hours == null ? "neutral" : sleep.last_hours >= 7.5 ? "positive" : sleep.last_hours >= 6.5 ? "neutral" : "negative"}
          />
          <VitalCell
            label="ACWR"
            value={load.acwr != null ? load.acwr.toFixed(2) : "—"}
            tone={load.acwr == null ? "neutral" : load.acwr > 1.5 ? "negative" : load.acwr > 1.3 ? "neutral" : load.acwr < 0.8 ? "neutral" : "positive"}
            sub={load.days_since_last != null ? `${load.days_since_last}d since` : undefined}
          />
        </div>
      )}

      {fresh.gaps.length > 0 && (
        <div className="px-5 py-2 border-t border-[var(--hairline)] text-[10.5px] text-[var(--negative)]">
          {fresh.gaps.join(" · ")}
        </div>
      )}
    </div>
  );
}
