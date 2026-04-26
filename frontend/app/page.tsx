import { CommandBriefing } from "@/components/command-briefing";
import { HealthAnalysis } from "@/components/health-analysis";
import { PillarRecovery } from "@/components/pillar-recovery";
import { PillarSleep } from "@/components/pillar-sleep";
import { PillarTrainingLoad } from "@/components/pillar-training-load";
import { StrengthPanel } from "@/components/strength-panel";
import { TrendIntelligence } from "@/components/trend-intelligence";
import { RightRail } from "@/components/right-rail";
import { AdvisorChat } from "@/components/advisor-chat";
import { SyncStatus } from "@/components/sync-status";
import { DashboardClock } from "@/components/dashboard-clock";
import { NextWorkoutCard } from "@/components/next-workout-card";
import { CardioPanel } from "@/components/cardio-panel";
import { ErrorBoundary } from "@/components/error-boundary";

export default function Dashboard() {
  return (
    <main className="min-h-screen px-5 pb-20 pt-6 max-w-[1600px] mx-auto">
      <header className="flex items-baseline justify-between pb-4 border-b border-[var(--hairline)] mb-5">
        <div className="flex items-baseline gap-3">
          <span className="inline-block h-1.5 w-1.5 rounded-full bg-[var(--positive)] animate-pulse" />
          <h1
            className="text-[14px] tracking-[0.22em] uppercase"
            style={{
              fontFamily: "var(--font-orbitron)",
              color: "oklch(0.88 0.18 145)",
              textShadow: "0 0 8px oklch(0.88 0.18 145), 0 0 24px oklch(0.72 0.22 145 / 0.7), 0 0 48px oklch(0.6 0.25 145 / 0.35)",
            }}
          >
            Savage Health Center
          </h1>
        </div>
        <DashboardClock />
      </header>

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

      <AdvisorChat />
    </main>
  );
}
