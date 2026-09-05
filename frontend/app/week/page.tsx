"use client";

import { AfterActionPanel } from "@/components/after-action-panel";
import { SurfaceShell } from "@/components/surface-shell";
import { CardioPanel } from "@/components/cardio-panel";
import { ErrorBoundary } from "@/components/error-boundary";
import { GoalScorecard } from "@/components/goal-scorecard";
import { MomentumPanel } from "@/components/momentum-panel";
import { MuscleVolumePanel } from "@/components/muscle-volume-panel";
import { PatternsPane } from "@/components/patterns-pane";
import { PeriodizationStrip } from "@/components/periodization-strip";
import { PerformanceCurvePane } from "@/components/performance-curve";
import { PickleballPane } from "@/components/pickleball-panel";
import { PillarRecovery } from "@/components/pillar-recovery";
import { PillarSleep } from "@/components/pillar-sleep";
import { PillarTrainingLoad } from "@/components/pillar-training-load";
import { PostWorkoutPanel } from "@/components/post-workout-panel";
import { PrescriptionPanel } from "@/components/prescription-panel";
import { StrengthPanel } from "@/components/strength-panel";
import { RecoveryTrendPane, VolumeLandmarks } from "@/components/trend-intelligence";
import { WhoopVitals } from "@/components/whoop-vitals";

import type { Span } from "@/lib/sections";

/**
 * One card on the board. The `id` is the anchor the command palette and every
 * deep link scroll to, so it must match a row in `sectionsFor("week")` — that
 * manifest is the only place section ids are declared.
 *
 * Nothing here collapses. A card that has to be opened is a card that never
 * gets read; the four-column grid is what buys the room to leave it all open.
 */
function Card({ id, span, label, children }: { id: string; span: Span; label: string; children: React.ReactNode }) {
  return (
    <section id={id} className={`span-${span} scroll-mt-24`}>
      <ErrorBoundary label={label}>{children}</ErrorBoundary>
    </section>
  );
}

/**
 * WEEK — what changed, and how training is going.
 *
 * Reads top-down as the weekly review actually runs: the delta first, then the
 * three signal pillars that explain it, then the longitudinal trend, then
 * training (block → performance → strength → volume), then output (cardio,
 * sport), then the debrief and the scorecard.
 */
export default function WeekPage() {
  return (
    <SurfaceShell>
      <div className="board">
        {/* ── What changed ─────────────────────────────────────────────── */}
        <Card id="momentum" span={4} label="Momentum">
          <MomentumPanel />
        </Card>

        {/* ── Signals ──────────────────────────────────────────────────── */}
        <div className="board-rule">Signals</div>
        <Card id="recovery" span={1} label="Recovery">
          <PillarRecovery />
        </Card>
        <Card id="sleep" span={1} label="Sleep">
          <PillarSleep />
        </Card>
        <Card id="load" span={1} label="Training load">
          <PillarTrainingLoad />
        </Card>
        <Card id="vitals" span={1} label="WHOOP vitals">
          <WhoopVitals />
        </Card>
        <Card id="recovery-trend" span={2} label="Recovery trend">
          <RecoveryTrendPane />
        </Card>
        <Card id="patterns" span={2} label="Patterns">
          <PatternsPane />
        </Card>

        {/* ── Training ─────────────────────────────────────────────────── */}
        <div className="board-rule">Training</div>
        <Card id="meso" span={2} label="Mesocycle">
          <PeriodizationStrip />
        </Card>
        <Card id="performance" span={2} label="Performance curve">
          <PerformanceCurvePane />
        </Card>
        <Card id="strength" span={4} label="Strength">
          <StrengthPanel />
        </Card>
        <Card id="volume" span={2} label="Volume vs landmarks">
          <div className="space-y-4">
            <VolumeLandmarks />
            <MuscleVolumePanel />
          </div>
        </Card>
        <Card id="prescription" span={2} label="Volume prescription">
          <PrescriptionPanel />
        </Card>

        {/* ── Output ───────────────────────────────────────────────────── */}
        <div className="board-rule">Output</div>
        <Card id="cardio" span={3} label="Cardio">
          <CardioPanel />
        </Card>
        <Card id="sport" span={1} label="Pickleball">
          <PickleballPane />
        </Card>

        {/* ── Debrief ──────────────────────────────────────────────────── */}
        <div className="board-rule">Debrief</div>
        <Card id="post" span={2} label="Post-workout debrief">
          <div className="space-y-4">
            <PostWorkoutPanel />
            <AfterActionPanel />
          </div>
        </Card>
        <Card id="goals" span={2} label="2026 goal scorecard">
          <GoalScorecard />
        </Card>
      </div>
    </SurfaceShell>
  );
}
