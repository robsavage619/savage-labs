import { CommandBriefing } from "@/components/command-briefing";
import { HealthAnalysis } from "@/components/health-analysis";
import { HealthStory } from "@/components/health-story";
import { PillarRecovery } from "@/components/pillar-recovery";
import { PillarSleep } from "@/components/pillar-sleep";
import { PillarTrainingLoad } from "@/components/pillar-training-load";
import { PeriodizationStrip } from "@/components/periodization-strip";
import { AfterActionPanel } from "@/components/after-action-panel";
import { PostWorkoutPanel } from "@/components/post-workout-panel";
import { ClinicalResearchPanel } from "@/components/clinical-research-panel";
import { LabPanel } from "@/components/lab-panel";
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
        Decision-first hierarchy. Today's essentials (verdict, plan, signals)
        render expanded; history/research/detail collapse by default and are
        reachable via SectionNav. Anchor ids must stay in sync with the
        SECTIONS list in section-nav.tsx.
      */}
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
        <div className="space-y-4 min-w-0">
          <section id="today" className="scroll-mt-20 space-y-4">
            <ErrorBoundary label="Command briefing">
              <CommandBriefing />
            </ErrorBoundary>

            <ErrorBoundary label="WHOOP vitals">
              <WhoopVitals />
            </ErrorBoundary>

            <ErrorBoundary label="Health story">
              <HealthStory />
            </ErrorBoundary>

            <ErrorBoundary label="Health analysis">
              <HealthAnalysis />
            </ErrorBoundary>
          </section>

          <ErrorBoundary label="Next workout">
            <NextWorkoutCard />
          </ErrorBoundary>

          <section id="signals" className="scroll-mt-20 grid grid-cols-1 lg:grid-cols-3 gap-4">
            <ErrorBoundary label="Recovery">
              <PillarRecovery />
            </ErrorBoundary>
            <ErrorBoundary label="Sleep">
              <PillarSleep />
            </ErrorBoundary>
            <ErrorBoundary label="Training load">
              <PillarTrainingLoad />
            </ErrorBoundary>
          </section>

          <CollapsibleSection id="goals" title="2026 Goal scorecard">
            <ErrorBoundary label="Goal scorecard">
              <GoalScorecard />
            </ErrorBoundary>
          </CollapsibleSection>

          <CollapsibleSection id="meso" title="Mesocycle">
            <ErrorBoundary label="Periodization">
              <PeriodizationStrip />
            </ErrorBoundary>
          </CollapsibleSection>

          <CollapsibleSection id="after-action" title="Post-workout">
            <div className="space-y-4">
              <ErrorBoundary label="Post-workout debrief">
                <PostWorkoutPanel />
              </ErrorBoundary>
              <ErrorBoundary label="After action">
                <AfterActionPanel />
              </ErrorBoundary>
            </div>
          </CollapsibleSection>

          <CollapsibleSection id="research" title="Research">
            <div className="space-y-4">
              <ErrorBoundary label="Clinical research">
                <ClinicalResearchPanel />
              </ErrorBoundary>
              <ErrorBoundary label="Research lab">
                <LabPanel />
              </ErrorBoundary>
            </div>
          </CollapsibleSection>

          <CollapsibleSection id="fueling" title="Fueling">
            <ErrorBoundary label="Fueling">
              <FuelingPanel />
            </ErrorBoundary>
          </CollapsibleSection>

          <CollapsibleSection id="training" title="Strength">
            <ErrorBoundary label="Strength">
              <StrengthPanel />
            </ErrorBoundary>
          </CollapsibleSection>

          <CollapsibleSection id="cardio" title="Cardio & sports">
            <ErrorBoundary label="Cardio">
              <CardioPanel />
            </ErrorBoundary>
          </CollapsibleSection>

          <CollapsibleSection id="physique" title="Progress photos">
            <ErrorBoundary label="Progress photos">
              <ProgressPhotoPanel />
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
