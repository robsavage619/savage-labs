import { PillarRecovery } from "@/components/pillar-recovery";
import { PillarSleep } from "@/components/pillar-sleep";
import { PillarTrainingLoad } from "@/components/pillar-training-load";
import { PeriodizationStrip } from "@/components/periodization-strip";
import { AfterActionPanel } from "@/components/after-action-panel";
import { PostWorkoutPanel } from "@/components/post-workout-panel";
import { ClinicalResearchPanel } from "@/components/clinical-research-panel";
import { LabPanel } from "@/components/lab-panel";
import { LabExperiments } from "@/components/lab-experiments";
import { EngineStatusPanel } from "@/components/engine-status-panel";
import { FuelingPanel } from "@/components/fueling-panel";
import { StrengthPanel } from "@/components/strength-panel";
import { TrendIntelligence } from "@/components/trend-intelligence";
import { RightRail } from "@/components/right-rail";
import { SyncStatus } from "@/components/sync-status";
import { DashboardClock } from "@/components/dashboard-clock";
import { LiveBadge } from "@/components/live-badge";
import { ProtocolStrip } from "@/components/protocol-strip";
import { AmbientHue } from "@/components/ambient-hue";
import { HeaderHUD } from "@/components/header-hud";
import { NextWorkoutCard } from "@/components/next-workout-card";
import { CardioPanel } from "@/components/cardio-panel";
import { WhoopVitals } from "@/components/whoop-vitals";
import { ErrorBoundary } from "@/components/error-boundary";
import { SectionNav } from "@/components/section-nav";
import { CollapsibleSection } from "@/components/collapsible-section";
import { GoalScorecard } from "@/components/goal-scorecard";
import { ProgressPhotoPanel } from "@/components/progress-photo-panel";
import { DailyReport } from "@/components/daily-report";
import { MiddaySessionCard } from "@/components/midday-session-card";
import { AthleteOSPanel } from "@/components/athlete-os-panel";

/** A labelled divider that opens a cluster of related detail sections. Anchor id
 *  must stay in sync with the SECTIONS list in section-nav.tsx. */
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

export default function Dashboard() {
  return (
    <main className="min-h-screen px-5 pb-20 pt-6 max-w-[1600px] mx-auto">
      <AmbientHue />
      <header className="flex items-stretch justify-between flex-wrap pb-5 border-b border-[var(--hairline)] mb-5 gap-4">
        <div className="flex flex-col justify-end gap-2 shrink-0">
          <div className="flex items-baseline gap-3 flex-wrap">
            <h1 className="flex items-baseline gap-[0.5em]">
              <span className="sl-wordmark-savage">Savage</span>
              <span className="sl-wordmark-labs">Labs</span>
            </h1>
            <span className="sl-wordmark-beta">β</span>
            <LiveBadge />
            <span className="sl-classified-badge">INTERNAL // AUTH</span>
          </div>
          <div className="sl-wordmark-bar" />
        </div>
        <div className="order-last w-full md:order-none md:w-auto md:flex-1 flex min-w-0">
          <HeaderHUD />
        </div>
        <div className="shrink-0 flex items-end">
          <DashboardClock />
        </div>
      </header>

      <ProtocolStrip />

      <SectionNav />

      <div className="mb-4">
        <SyncStatus />
      </div>

      {/*
        Decision-first, causally ordered: VERDICT → the SIGNALS it's built from →
        the PLAN that follows → the ENGINE that produced it → collapsed detail
        grouped into Training / Body / Intelligence. Anchor ids must stay in sync
        with the SECTIONS list in section-nav.tsx.
      */}
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
        <div className="space-y-4 min-w-0">
          {/* ── VERDICT ── */}
          <section id="today" className="scroll-mt-20">
            <ErrorBoundary label="Athlete operating system">
              <AthleteOSPanel />
            </ErrorBoundary>
          </section>
          <section className="scroll-mt-20">
            <ErrorBoundary label="Daily report">
              <DailyReport />
            </ErrorBoundary>
          </section>

          {/* ── SIGNALS (the inputs behind the verdict) ── */}
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
            {/* Raw WHOOP vitals demoted to a drill-down — the pillars above are the
                read; these are the underlying numbers, one click away. */}
            <CollapsibleSection id="whoop" title="Raw WHOOP vitals">
              <ErrorBoundary label="WHOOP vitals">
                <WhoopVitals />
              </ErrorBoundary>
            </CollapsibleSection>
          </section>

          {/* ── PLAN (the output) ── */}
          <section id="plan" className="scroll-mt-20 space-y-4">
            <ErrorBoundary label="Next workout">
              <NextWorkoutCard />
            </ErrorBoundary>
            <ErrorBoundary label="Midday session">
              <MiddaySessionCard />
            </ErrorBoundary>
          </section>

          {/* ── ENGINE & METHODOLOGY (how the call was made — promoted from the
                bottom; provenance, hypothesis tests, self-learning status) ── */}
          <CollapsibleSection id="engine" title="Engine & methodology">
            <div className="space-y-4">
              <ErrorBoundary label="Self-experiments">
                <LabExperiments />
              </ErrorBoundary>
              <ErrorBoundary label="Research lab">
                <LabPanel />
              </ErrorBoundary>
              <ErrorBoundary label="Engine status">
                <EngineStatusPanel />
              </ErrorBoundary>
            </div>
          </CollapsibleSection>

          {/* ── TRAINING ── */}
          <ClusterHeader id="training">Training</ClusterHeader>
          <CollapsibleSection id="meso" title="Mesocycle">
            <ErrorBoundary label="Periodization">
              <PeriodizationStrip />
            </ErrorBoundary>
          </CollapsibleSection>
          <CollapsibleSection id="strength" title="Strength">
            <ErrorBoundary label="Strength">
              <StrengthPanel />
            </ErrorBoundary>
          </CollapsibleSection>
          <CollapsibleSection id="cardio" title="Cardio & sports">
            <ErrorBoundary label="Cardio">
              <CardioPanel />
            </ErrorBoundary>
          </CollapsibleSection>
          <CollapsibleSection id="post" title="Post-workout">
            <div className="space-y-4">
              <ErrorBoundary label="Post-workout debrief">
                <PostWorkoutPanel />
              </ErrorBoundary>
              <ErrorBoundary label="After action">
                <AfterActionPanel />
              </ErrorBoundary>
            </div>
          </CollapsibleSection>
          <CollapsibleSection id="goals" title="2026 Goal scorecard">
            <ErrorBoundary label="Goal scorecard">
              <GoalScorecard />
            </ErrorBoundary>
          </CollapsibleSection>

          {/* ── BODY ── */}
          <ClusterHeader id="body">Body</ClusterHeader>
          <CollapsibleSection id="fueling" title="Fueling">
            <ErrorBoundary label="Fueling">
              <FuelingPanel />
            </ErrorBoundary>
          </CollapsibleSection>
          <CollapsibleSection id="physique" title="Progress photos">
            <ErrorBoundary label="Progress photos">
              <ProgressPhotoPanel />
            </ErrorBoundary>
          </CollapsibleSection>

          {/* ── INTELLIGENCE ── */}
          <ClusterHeader id="intel">Intelligence</ClusterHeader>
          <CollapsibleSection id="research" title="Clinical research">
            <ErrorBoundary label="Clinical research">
              <ClinicalResearchPanel />
            </ErrorBoundary>
          </CollapsibleSection>
          <CollapsibleSection id="trends" title="Trend intelligence">
            <ErrorBoundary label="Trends">
              <TrendIntelligence />
            </ErrorBoundary>
          </CollapsibleSection>
        </div>

        {/* Single RightRail mount — responsive class controls placement */}
        <div className="xl:block">
          <ErrorBoundary label="Right rail">
            <RightRail />
          </ErrorBoundary>
        </div>
      </div>
    </main>
  );
}
