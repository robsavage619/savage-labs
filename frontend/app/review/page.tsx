import { AppShell } from "@/components/app-shell";
import { AfterActionPanel } from "@/components/after-action-panel";
import { CardioPanel } from "@/components/cardio-panel";
import { CollapsibleSection } from "@/components/collapsible-section";
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
import { REVIEW_SECTIONS } from "@/components/section-nav";
import { StrengthPanel } from "@/components/strength-panel";
import { WhoopVitals } from "@/components/whoop-vitals";

/** A labelled divider that opens a cluster of related detail sections. Anchor id
 *  must stay in sync with REVIEW_SECTIONS in section-nav.tsx. */
function ClusterHeader({ id, children }: { id: string; children: string }) {
  return (
    <div
      id={id}
      className="scroll-mt-20 pt-3 pb-1 text-[10px] uppercase tracking-[0.22em] text-[var(--text-faint)]"
      style={{ fontFamily: "var(--font-orbitron)" }}
    >
      {children}
    </div>
  );
}

/**
 * REVIEW — the weekly read.
 *
 * Opens on what changed since last time, which is the question a longitudinal
 * tool exists to answer and which used to be the last widget on the page. Then
 * the signal detail, then training and body history as drill-downs.
 */
export default function ReviewPage() {
  return (
    <AppShell sections={REVIEW_SECTIONS}>
      <div className="space-y-4">
        {/* ── WHAT CHANGED ── */}
        <section id="momentum" className="scroll-mt-20">
          <ErrorBoundary label="Momentum">
            <MomentumPanel />
          </ErrorBoundary>
        </section>

        {/* ── SIGNALS ── */}
        <section id="signals" className="scroll-mt-20 space-y-4">
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
          <CollapsibleSection id="whoop" cluster="signals" title="Raw WHOOP vitals" defaultOpen>
            <ErrorBoundary label="WHOOP vitals">
              <WhoopVitals />
            </ErrorBoundary>
          </CollapsibleSection>
        </section>

        {/* ── TRAINING ── */}
        <ClusterHeader id="training">Training</ClusterHeader>
        <CollapsibleSection id="meso" cluster="training" title="Mesocycle" defaultOpen>
          <ErrorBoundary label="Periodization">
            <PeriodizationStrip />
          </ErrorBoundary>
        </CollapsibleSection>
        <CollapsibleSection id="strength" cluster="training" title="Strength" defaultOpen>
          <ErrorBoundary label="Strength">
            <StrengthPanel />
          </ErrorBoundary>
        </CollapsibleSection>
        <CollapsibleSection id="cardio" cluster="training" title="Cardio & sports" defaultOpen>
          <ErrorBoundary label="Cardio">
            <CardioPanel />
          </ErrorBoundary>
        </CollapsibleSection>
        <CollapsibleSection id="post" cluster="training" title="Post-workout" defaultOpen>
          <div className="space-y-4">
            <ErrorBoundary label="Post-workout debrief">
              <PostWorkoutPanel />
            </ErrorBoundary>
            <ErrorBoundary label="After action">
              <AfterActionPanel />
            </ErrorBoundary>
          </div>
        </CollapsibleSection>
        <CollapsibleSection id="goals" cluster="training" title="2026 Goal scorecard" defaultOpen>
          <ErrorBoundary label="Goal scorecard">
            <GoalScorecard />
          </ErrorBoundary>
        </CollapsibleSection>

        {/* ── BODY ── */}
        <ClusterHeader id="body">Body</ClusterHeader>
        <CollapsibleSection id="fueling" cluster="body" title="Fueling" defaultOpen>
          <ErrorBoundary label="Fueling">
            <FuelingPanel />
          </ErrorBoundary>
        </CollapsibleSection>
        <CollapsibleSection id="physique" cluster="body" title="Progress photos" defaultOpen>
          <ErrorBoundary label="Progress photos">
            <ProgressPhotoPanel />
          </ErrorBoundary>
        </CollapsibleSection>
      </div>
    </AppShell>
  );
}
