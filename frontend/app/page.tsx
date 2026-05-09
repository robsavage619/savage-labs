import { CommandBriefing } from "@/components/command-briefing";
import { HealthAnalysis } from "@/components/health-analysis";
import { HealthStory } from "@/components/health-story";
import { PillarRecovery } from "@/components/pillar-recovery";
import { PillarSleep } from "@/components/pillar-sleep";
import { PillarTrainingLoad } from "@/components/pillar-training-load";
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

export default function Dashboard() {
  return (
    <main className="min-h-screen px-5 pb-20 pt-6 max-w-[1600px] mx-auto">
      <AmbientHue />
      <header className="flex items-stretch justify-between pb-5 border-b border-[var(--hairline)] mb-5 gap-4">
        <div className="flex flex-col justify-end gap-2 shrink-0">
          <div className="flex items-baseline gap-3">
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
        <HeaderHUD />
        <div className="shrink-0 flex items-end">
          <DashboardClock />
        </div>
      </header>

      <ProtocolStrip />

      <div className="mb-4">
        <SyncStatus />
      </div>

      {/*
        Layout follows the decision-first hierarchy from the design review:
        1. Command briefing (one verdict + one why)
        2. Today's plan — the action surface
        3. Three body-signal pillars (Recovery, Sleep, Training Load) — Readiness
           is folded into Recovery via DailyState; no longer rendered as a 4th card
        4. Strength → Cardio → Trends — drill-down detail
      */}
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
        <div className="space-y-4 min-w-0">
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

          <ErrorBoundary label="Next workout">
            <NextWorkoutCard />
          </ErrorBoundary>

          <section className="grid grid-cols-1 lg:grid-cols-3 gap-4">
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

          <ErrorBoundary label="Strength">
            <StrengthPanel />
          </ErrorBoundary>

          <ErrorBoundary label="Cardio">
            <CardioPanel />
          </ErrorBoundary>

          <ErrorBoundary label="Trends">
            <TrendIntelligence />
          </ErrorBoundary>
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
