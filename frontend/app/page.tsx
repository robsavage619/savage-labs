"use client";

import { AthleteOSPanel } from "@/components/athlete-os-panel";
import { CheckinCard } from "@/components/checkin-card";
import { DailyReport } from "@/components/daily-report";
import { ErrorBoundary } from "@/components/error-boundary";
import { MiddaySessionCard } from "@/components/midday-session-card";
import { NextWorkoutPane } from "@/components/next-workout";
import { SurfaceShell } from "@/components/surface-shell";

/**
 * TODAY — what to train, and log it.
 *
 * Ordered by what the morning actually asks, not by panel size: the call, then
 * the session that follows from it, then the input that feeds tomorrow's. The
 * narrative report sits beside the session rather than above it — it is a read,
 * not a decision, and it was previously pushing the first prescribed set two
 * screens down.
 *
 * Anchor ids come from `lib/sections.ts`, which the command palette reads too,
 * so a link can no longer point at a section that isn't here.
 */
export default function TodayPage() {
  return (
    <SurfaceShell>
      <div className="board">
        <section id="call" className="span-4 scroll-mt-24">
          <ErrorBoundary label="Today's call">
            <AthleteOSPanel />
          </ErrorBoundary>
        </section>

        <div className="board-rule">The session</div>

        <section id="session" className="span-3 scroll-mt-24">
          <ErrorBoundary label="Next workout">
            <NextWorkoutPane />
          </ErrorBoundary>
        </section>

        <div className="span-1 flex flex-col gap-4">
          <section id="midday" className="scroll-mt-24">
            <ErrorBoundary label="Midday session">
              <MiddaySessionCard />
            </ErrorBoundary>
          </section>
          <section id="checkin" className="scroll-mt-24">
            <ErrorBoundary label="Check-in">
              <CheckinCard />
            </ErrorBoundary>
          </section>
        </div>

        <div className="board-rule">Today&apos;s report</div>

        <section id="report" className="span-4 scroll-mt-24">
          <ErrorBoundary label="Daily report">
            <DailyReport />
          </ErrorBoundary>
        </section>
      </div>
    </SurfaceShell>
  );
}
