"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { recoveryRead, hrvRead, rhrRead, sleepRead, signalChannels } from "@/lib/console-copy";
import { Channel } from "@/components/console/channel";
import { ConsoleShell } from "@/components/console/shell";
import { AfterActionPanel } from "@/components/after-action-panel";
import { CardioPanel } from "@/components/cardio-panel";
import { ErrorBoundary } from "@/components/error-boundary";
import { FuelingPanel } from "@/components/fueling-panel";
import { GoalScorecard } from "@/components/goal-scorecard";
import { MomentumPanel } from "@/components/momentum-panel";
import { PeriodizationStrip } from "@/components/periodization-strip";
import { PillarRecovery } from "@/components/pillar-recovery";
import { PillarSleep } from "@/components/pillar-sleep";
import { PillarTrainingLoad } from "@/components/pillar-training-load";
import { PostWorkoutPanel } from "@/components/post-workout-panel";
import { ProgressPhotoPanel } from "@/components/progress-photo-panel";
import { StrengthPanel } from "@/components/strength-panel";
import { WhoopVitals } from "@/components/whoop-vitals";

/**
 * SIGNALS — what the body is doing, as opposed to Ops's what to do about it.
 *
 * This is the content that used to sit behind eight collapsed accordions on
 * /review plus a "Raw WHOOP vitals" section. Nothing here collapses.
 *
 * The console channels up top are a summary read, not a replacement: every
 * original panel is hosted below, expanded, with its controls intact.
 */
export default function SignalsPage() {
  const state = useQuery({ queryKey: ["daily-state"], queryFn: api.dailyState, staleTime: 5 * 60_000 });
  const volume = useQuery({ queryKey: ["muscle-volume"], queryFn: api.muscleVolume, staleTime: 5 * 60_000 });

  const s = state.data;
  const vitals = s ? [recoveryRead(s), hrvRead(s), rhrRead(s), sleepRead(s)] : [];
  const detail = s ? signalChannels(s) : [];

  // Volume against target — the thing the audit found buried three levels deep
  // on /lab, which is odd for the number that decides whether the training is
  // working at all.
  const muscles = (volume.data?.muscles ?? [])
    .filter((m) => m.mev != null)
    .map((m) => ({
      ...m,
      pct: m.mev ? Math.min(1.6, m.weekly_sets / m.mev) : 0,
    }))
    .sort((a, b) => a.pct - b.pct);

  const under = muscles.filter((m) => m.pct < 1);

  return (
    <ConsoleShell>
      <div className="cx-grid">
        <div className="cx-rule" style={{ marginTop: 0 }}>
          Today&apos;s vitals
        </div>
        {s
          ? vitals.map((ch) => <Channel key={ch.label} ch={ch} />)
          : Array.from({ length: 4 }, (_, i) => <div key={i} className="cx-skel" />)}

        <div className="cx-rule">Sleep &amp; systemic</div>
        {s
          ? detail.map((ch) => <Channel key={ch.label} ch={ch} />)
          : Array.from({ length: 6 }, (_, i) => <div key={i} className="cx-skel" />)}

        <div className="cx-rule">Weekly volume against target</div>
        {volume.data ? (
          <section className="cx-card" style={{ gridColumn: "1 / -1" }}>
            <header className="cx-head">
              <h3 className="cx-label">Sets this week</h3>
              <span className="cx-status" style={{ color: under.length ? "var(--warn)" : "var(--c-dim)" }}>
                {under.length ? `${under.length} below minimum` : "all at minimum"}
              </span>
            </header>
            <p className="cx-read" style={{ marginTop: 2, marginBottom: 14 }}>
              {under.length
                ? `${under
                    .slice(0, 3)
                    .map((m) => m.muscle.replace(/_/g, " "))
                    .join(", ")} ${under.length === 1 ? "is" : "are"} short of the weekly minimum that maintains size. Everything at or past the line is doing its job.`
                : "Every muscle is at or above the weekly minimum that maintains size."}
            </p>
            <div className="cx-bars">
              {muscles.map((m) => (
                <div className="cx-bar" key={m.muscle}>
                  <span className="cx-bar-name">{m.muscle.replace(/_/g, " ")}</span>
                  <span className="cx-bar-track">
                    <i
                      style={{
                        width: `${Math.min(100, (m.pct / 1.6) * 100)}%`,
                        background: m.pct < 1 ? "var(--warn)" : "var(--ok)",
                      }}
                    />
                    <em style={{ left: `${(1 / 1.6) * 100}%` }} aria-hidden="true" />
                  </span>
                  <span className="cx-bar-n">
                    {m.weekly_sets}
                    <span style={{ color: "var(--c-faint)" }}>/{m.mev}</span>
                  </span>
                </div>
              ))}
            </div>
          </section>
        ) : (
          <div className="cx-skel" style={{ gridColumn: "1 / -1", minHeight: 220 }} />
        )}

        <div className="cx-legacy">
          <div className="cx-rule" style={{ marginTop: 0 }}>
            What changed
          </div>
          <ErrorBoundary label="Momentum">
            <MomentumPanel />
          </ErrorBoundary>

          <div className="cx-rule">Recovery, sleep &amp; load</div>
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            <ErrorBoundary label="Recovery">
              <PillarRecovery />
            </ErrorBoundary>
            <ErrorBoundary label="Sleep">
              <PillarSleep />
            </ErrorBoundary>
            <ErrorBoundary label="Training load">
              <PillarTrainingLoad />
            </ErrorBoundary>
          </div>
          <ErrorBoundary label="WHOOP vitals">
            <WhoopVitals />
          </ErrorBoundary>

          <div className="cx-rule">Training history</div>
          <ErrorBoundary label="Periodization">
            <PeriodizationStrip />
          </ErrorBoundary>
          <ErrorBoundary label="Strength">
            <StrengthPanel />
          </ErrorBoundary>
          <ErrorBoundary label="Cardio">
            <CardioPanel />
          </ErrorBoundary>
          <ErrorBoundary label="Post-workout debrief">
            <PostWorkoutPanel />
          </ErrorBoundary>
          <ErrorBoundary label="After action">
            <AfterActionPanel />
          </ErrorBoundary>
          <ErrorBoundary label="Goal scorecard">
            <GoalScorecard />
          </ErrorBoundary>

          <div className="cx-rule">Body</div>
          <ErrorBoundary label="Fueling">
            <FuelingPanel />
          </ErrorBoundary>
          <ErrorBoundary label="Progress photos">
            <ProgressPhotoPanel />
          </ErrorBoundary>
        </div>
      </div>
    </ConsoleShell>
  );
}
