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
import {
  LastSessionCard,
  TrainingConsistencyCard,
  MuscleBalanceCard,
  RecoveryTrainingCard,
  VolumeLoadCard,
  MostTrainedCard,
} from "@/components/strength-panel";
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
 * Reads top-down as the weekly review actually runs: the delta and the block
 * position first, then the three signal pillars that explain them, then the
 * longitudinal trend, then training (performance → strength → volume), then
 * output (cardio, sport), then the debrief and the scorecard.
 *
 * SPANS ARE MEASURED, NOT GUESSED. Every row below pairs cards whose rendered
 * heights are within ~2x of each other, and every row fills all four columns —
 * grid auto-placement follows source order, so the order IS the layout. The
 * two rules that produced this arrangement:
 *
 *   - a card's height is a function of its width, so a dense panel starved of
 *     columns just grows downward (Pickleball at span-1 rendered 392x1339 —
 *     a quarter-column pillar of unreadable text);
 *   - a short card at span-4 owns a whole row for nothing (Momentum rendered
 *     1616x184), so it gets a partner of similar height instead.
 */
export default function WeekPage() {
  return (
    <SurfaceShell>
      <div className="board">
        {/* ── Where the week stands ────────────────────────────────────────
            Two short strips, paired: the delta (184px) and the block position
            (265px). Neither has the content to justify a row of its own. */}
        <Card id="momentum" span={2} label="Momentum">
          <MomentumPanel />
        </Card>
        <Card id="meso" span={2} label="Mesocycle">
          <PeriodizationStrip />
        </Card>

        {/* ── Signals ──────────────────────────────────────────────────────
            Four pillar tiles, 350–469px tall — the tightest row on the board,
            and the one case where span-1 is the right size. */}
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
        {/* Two longitudinal panes, 755px and 668px — an even row. */}
        <Card id="recovery-trend" span={2} label="Recovery trend">
          <RecoveryTrendPane />
        </Card>
        <Card id="patterns" span={2} label="Patterns">
          <PatternsPane />
        </Card>

        {/* ── Training ─────────────────────────────────────────────────────
            Two full-width panels (a time-series curve and the strength
            heatmap, both of which read better the wider they get), then the
            tall dose pair: volume 1552px beside prescription 999px. */}
        <div className="board-rule">Training</div>
        <Card id="performance" span={4} label="Performance curve">
          <PerformanceCurvePane />
        </Card>
        {/* StrengthPanel was ONE card 1,559px tall containing six independent
            blocks — four of them under 150px. Measured heights: last session 77,
            consistency 141, balance 127, recovery×training 111, volume load 491,
            most trained 381. As one card the four small ones were trapped in a
            skyscraper; as six they fill two clean rows. */}
        <Card id="last-session" span={4} label="Last session">
          <LastSessionCard />
        </Card>
        <Card id="consistency" span={4} label="Training consistency">
          <TrainingConsistencyCard />
        </Card>
        <Card id="balance" span={2} label="Muscle balance">
          <MuscleBalanceCard />
        </Card>
        <Card id="recovery-training" span={2} label="Recovery × training">
          <RecoveryTrainingCard />
        </Card>
        <Card id="most-trained" span={2} label="Most trained">
          <MostTrainedCard />
        </Card>
        <Card id="volume-load" span={4} label="Volume load">
          <VolumeLoadCard />
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

        {/* ── Output ───────────────────────────────────────────────────────
            Both panels are dense; splitting the row evenly is what makes the
            Pickleball pane readable at all (it was 392px wide, 1339px tall). */}
        <div className="board-rule">Output</div>
        <Card id="cardio" span={2} label="Cardio">
          <CardioPanel />
        </Card>
        <Card id="sport" span={2} label="Pickleball">
          <PickleballPane />
        </Card>

        {/* ── Debrief ──────────────────────────────────────────────────────
            552px and 571px — already the flattest row on the page. */}
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
