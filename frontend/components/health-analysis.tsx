"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type Briefing, type DailyState, type Insight, type StatsSummary } from "@/lib/api";
import { Eyebrow } from "@/components/ui/metric";

/**
 * Comprehensive AI-driven health briefing.
 *
 * Aggregates the deterministic signals already computed server-side
 * (DailyState, StatsSummary) with the rule-based insights engine
 * (/api/insights) and the latest Claude-generated briefing
 * (/api/briefing) into one expandable analysis panel.
 */
export function HealthAnalysis() {
  const [open, setOpen] = useState(true);

  const stateQ = useQuery({ queryKey: ["daily-state"], queryFn: api.dailyState });
  const statsQ = useQuery({ queryKey: ["stats-summary"], queryFn: api.statsSummary });
  const insightsQ = useQuery({ queryKey: ["insights"], queryFn: api.insights });
  const briefingQ = useQuery({ queryKey: ["briefing"], queryFn: api.briefing });

  const loading = stateQ.isLoading || statsQ.isLoading || insightsQ.isLoading;
  const state: DailyState | undefined = stateQ.data;
  const stats: StatsSummary | undefined = statsQ.data;
  const insights: Insight[] = insightsQ.data ?? [];
  const briefing =
    briefingQ.data && "training_call" in briefingQ.data ? (briefingQ.data as Briefing) : null;

  return (
    <div className="shc-card shc-enter overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="w-full px-5 py-3 flex items-center justify-between hover:bg-[var(--card-hover)] transition-colors text-left"
      >
        <div className="flex items-center gap-3">
          <span
            className="inline-flex items-center justify-center h-5 w-5 rounded-full text-[9px] font-bold uppercase tracking-wider"
            style={{ background: "oklch(0.88 0.18 145 / 0.18)", color: "oklch(0.88 0.18 145)" }}
          >
            AI
          </span>
          <div>
            <Eyebrow>Health analysis</Eyebrow>
            <p className="mt-0.5 text-[13px] text-[var(--text-primary)]">
              {briefing?.readiness_headline ?? "Comprehensive briefing on metrics, progression, and signals"}
            </p>
          </div>
        </div>
        <span className="text-[11px] text-[var(--text-dim)]">{open ? "▴ collapse" : "▾ expand"}</span>
      </button>

      {open && (
        <div className="border-t border-[var(--hairline)]">
          {loading ? (
            <div className="p-5 space-y-2">
              {Array.from({ length: 4 }).map((_, i) => (
                <div key={i} className="shc-skeleton h-[14px]" />
              ))}
            </div>
          ) : (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-px bg-[var(--hairline)]">
              <Section title="What metrics are saying">
                <CurrentSignals state={state} stats={stats} />
              </Section>
              <Section title="How you're progressing">
                <ProgressionView stats={stats} state={state} />
              </Section>
              <Section title="Patterns the data shows" wide>
                <InsightList insights={insights} />
              </Section>
              {briefing && (
                <Section title="Today's coaching call" wide>
                  <CoachingNote briefing={briefing} />
                </Section>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function Section({
  title,
  children,
  wide = false,
}: {
  title: string;
  children: React.ReactNode;
  wide?: boolean;
}) {
  return (
    <div
      className={`bg-[var(--bg)] p-5 ${wide ? "lg:col-span-2" : ""}`}
    >
      <Eyebrow>{title}</Eyebrow>
      <div className="mt-3">{children}</div>
    </div>
  );
}

function CurrentSignals({
  state,
  stats,
}: {
  state: DailyState | undefined;
  stats: StatsSummary | undefined;
}) {
  if (!state || !stats) return <p className="text-[12px] text-[var(--text-faint)]">No data yet.</p>;

  const lines: { label: string; value: string; tone: "positive" | "neutral" | "negative" | "muted" }[] = [];

  if (state.recovery.score != null) {
    const s = state.recovery.score;
    lines.push({
      label: "Recovery",
      value: `${Math.round(s)}/100 — ${s >= 67 ? "primed for hard work" : s >= 50 ? "moderate readiness" : s >= 34 ? "lean toward recovery" : "rest emphasized"}`,
      tone: s >= 67 ? "positive" : s >= 34 ? "neutral" : "negative",
    });
  }

  if (state.recovery.hrv_sigma != null) {
    const z = state.recovery.hrv_sigma;
    const verb = z >= 0.5 ? "elevated above" : z >= -0.5 ? "tracking near" : z >= -1.5 ? "running below" : "well below";
    lines.push({
      label: "HRV",
      value: `${z >= 0 ? "+" : ""}${z.toFixed(2)}σ — ${verb} 28-day baseline`,
      tone: z >= 0 ? "positive" : z >= -1 ? "neutral" : "negative",
    });
  }

  if (stats.acwr.ratio != null) {
    const r = stats.acwr.ratio;
    const desc =
      r > 1.5
        ? "danger zone — sharp injury risk increase"
        : r > 1.3
        ? "above sweet spot — monitor recovery"
        : r >= 0.8
        ? "in the safe progressive band"
        : "detraining — load is too low to drive adaptation";
    lines.push({
      label: "Workload (ACWR)",
      value: `${r.toFixed(2)} — ${desc}`,
      tone: r > 1.5 ? "negative" : r > 1.3 || r < 0.8 ? "neutral" : "positive",
    });
  }

  if (state.sleep.last_hours != null) {
    const h = state.sleep.last_hours;
    const desc =
      h >= 7.5
        ? "in the recovery-supportive band"
        : h >= 6.5
        ? "marginal — daytime cognition will be fine, repair is partial"
        : "insufficient — hormone & glycogen recovery compromised";
    lines.push({
      label: "Last sleep",
      value: `${h.toFixed(1)}h — ${desc}`,
      tone: h >= 7 ? "positive" : h >= 6 ? "neutral" : "negative",
    });
  }

  if (stats.rhr.elevated_pct != null) {
    const p = stats.rhr.elevated_pct;
    if (Math.abs(p) > 1.5) {
      lines.push({
        label: "Resting HR",
        value: `${p >= 0 ? "+" : ""}${p.toFixed(1)}% vs 28-day baseline — ${p > 5 ? "stress / illness signal" : p > 0 ? "mild elevation, watch" : "below baseline, parasympathetic dominant"}`,
        tone: p > 5 ? "negative" : p > 2 ? "neutral" : "positive",
      });
    }
  }

  if (state.gates.reasons.length > 0) {
    lines.push({
      label: "Auto-regulation",
      value: `Gates active: ${state.gates.reasons.join("; ")}`,
      tone: "negative",
    });
  }

  if (lines.length === 0)
    return <p className="text-[12px] text-[var(--text-faint)]">All metrics within normal ranges.</p>;

  return (
    <ul className="space-y-2">
      {lines.map((l, i) => (
        <li key={i} className="flex gap-2 text-[12.5px] leading-snug">
          <Bullet tone={l.tone} />
          <span className="min-w-0 flex-1">
            <span className="text-[var(--text-muted)] font-medium">{l.label}: </span>
            <span className="text-[var(--text-primary)]">{l.value}</span>
          </span>
        </li>
      ))}
    </ul>
  );
}

function ProgressionView({
  stats,
  state,
}: {
  stats: StatsSummary | undefined;
  state: DailyState | undefined;
}) {
  if (!stats) return <p className="text-[12px] text-[var(--text-faint)]">Insufficient history.</p>;

  const lines: { label: string; value: string; tone: "positive" | "neutral" | "negative" }[] = [];

  if (stats.recovery_trend_slope_7d) {
    const m = stats.recovery_trend_slope_7d;
    if (Math.abs(m) > 0.3) {
      lines.push({
        label: "7-day recovery trend",
        value: `${m >= 0 ? "+" : ""}${m.toFixed(2)} pts/day — ${m > 0.5 ? "rising sharply" : m > 0 ? "trending up" : m > -0.5 ? "trending down" : "falling fast"}`,
        tone: m > 0 ? "positive" : "negative",
      });
    } else {
      lines.push({
        label: "7-day recovery trend",
        value: "Flat — body is at steady state",
        tone: "neutral",
      });
    }
  }

  if (stats.sleep.avg_7d != null) {
    const a = stats.sleep.avg_7d;
    lines.push({
      label: "7-day sleep avg",
      value: `${a.toFixed(1)}h — ${a >= 7.5 ? "exceeding adult guideline" : a >= 7 ? "meeting guideline" : "below 7h target"}`,
      tone: a >= 7 ? "positive" : a >= 6.5 ? "neutral" : "negative",
    });
  }

  if (stats.sleep.consistency_stdev != null) {
    const sd = stats.sleep.consistency_stdev;
    lines.push({
      label: "Sleep consistency (σ)",
      value: `${sd.toFixed(2)}h — ${sd < 0.5 ? "highly regular schedule" : sd < 1 ? "reasonable consistency" : "irregular, hurts recovery"}`,
      tone: sd < 0.5 ? "positive" : sd < 1 ? "neutral" : "negative",
    });
  }

  if (stats.sleep.debt_7d_hours != null && stats.sleep.debt_7d_hours > 0) {
    lines.push({
      label: "7-day sleep debt",
      value: `${stats.sleep.debt_7d_hours.toFixed(1)}h below 8h/night target`,
      tone: stats.sleep.debt_7d_hours > 5 ? "negative" : "neutral",
    });
  }

  if (state?.training_load?.acute_load_7d != null && state.training_load.chronic_load_28d != null) {
    const a = state.training_load.acute_load_7d;
    const c = state.training_load.chronic_load_28d;
    lines.push({
      label: "Load (acute / chronic)",
      value: `${a.toFixed(0)} / ${c.toFixed(0)} — ${a > c * 1.2 ? "ramping volume" : a < c * 0.8 ? "tapering" : "matched chronic"}`,
      tone: a > c * 1.5 ? "negative" : "neutral",
    });
  }

  if (lines.length === 0)
    return <p className="text-[12px] text-[var(--text-faint)]">Need more data to surface trends.</p>;

  return (
    <ul className="space-y-2">
      {lines.map((l, i) => (
        <li key={i} className="flex gap-2 text-[12.5px] leading-snug">
          <Bullet tone={l.tone} />
          <span className="min-w-0 flex-1">
            <span className="text-[var(--text-muted)] font-medium">{l.label}: </span>
            <span className="text-[var(--text-primary)]">{l.value}</span>
          </span>
        </li>
      ))}
    </ul>
  );
}

function InsightList({ insights }: { insights: Insight[] }) {
  if (insights.length === 0)
    return (
      <p className="text-[12px] text-[var(--text-faint)]">
        Patterns will surface as more data accumulates (need ~30 days).
      </p>
    );

  return (
    <ul className="grid grid-cols-1 md:grid-cols-2 gap-3">
      {insights.slice(0, 6).map((ins, i) => (
        <li
          key={i}
          className="rounded-md border border-[var(--hairline)] p-3 hover:border-[var(--hairline-strong)] transition-colors"
        >
          <div className="flex items-baseline gap-2">
            <Bullet tone={ins.polarity} />
            <p className="text-[12.5px] font-medium text-[var(--text-primary)] leading-snug">
              {ins.headline}
            </p>
          </div>
          <p className="mt-1.5 text-[11.5px] text-[var(--text-muted)] leading-relaxed pl-3.5">
            {ins.body}
          </p>
        </li>
      ))}
    </ul>
  );
}

function CoachingNote({ briefing }: { briefing: Briefing }) {
  return (
    <div>
      <div className="flex items-baseline gap-2 mb-2">
        <span
          className="text-[10px] font-semibold uppercase tracking-wider px-1.5 py-0.5 rounded"
          style={{
            background:
              briefing.training_call === "Push" || briefing.training_call === "Train"
                ? "oklch(0.88 0.18 145 / 0.18)"
                : briefing.training_call === "Rest"
                ? "oklch(0.7 0.18 25 / 0.18)"
                : "oklch(0.85 0.13 90 / 0.18)",
            color:
              briefing.training_call === "Push" || briefing.training_call === "Train"
                ? "var(--positive)"
                : briefing.training_call === "Rest"
                ? "var(--negative)"
                : "var(--neutral)",
          }}
        >
          {briefing.training_call}
        </span>
        <span className="text-[11px] text-[var(--text-dim)]">
          {briefing.readiness_headline}
        </span>
      </div>
      <p className="text-[13px] text-[var(--text-primary)] leading-relaxed">
        {briefing.coaching_note}
      </p>
      {briefing.training_rationale && (
        <p className="mt-2 text-[11.5px] text-[var(--text-muted)] leading-relaxed border-l-2 border-[var(--hairline)] pl-3">
          <span className="text-[var(--text-dim)] uppercase tracking-wider text-[9.5px] mr-1">
            rationale
          </span>
          {briefing.training_rationale}
        </p>
      )}
    </div>
  );
}

function Bullet({ tone }: { tone: "positive" | "neutral" | "negative" | "muted" }) {
  const color =
    tone === "positive"
      ? "var(--positive)"
      : tone === "negative"
      ? "var(--negative)"
      : tone === "muted"
      ? "var(--text-faint)"
      : "var(--neutral)";
  return (
    <span
      className="inline-block w-1 h-1 rounded-full shrink-0 mt-2"
      style={{ background: color }}
    />
  );
}
