import { AppShell } from "@/components/app-shell";
import { AthleteOSPanel } from "@/components/athlete-os-panel";
import { CheckinCard } from "@/components/checkin-card";
import { DailyReport } from "@/components/daily-report";
import { ErrorBoundary } from "@/components/error-boundary";
import { MiddaySessionCard } from "@/components/midday-session-card";
import { NextWorkoutCard } from "@/components/next-workout-card";
import { NOW_SECTIONS } from "@/components/section-nav";

/**
 * NOW — the daily driver, phone-first.
 *
 * Scoped to the two questions the morning and the gym actually ask: what am I
 * doing today, and what did I log. Trends, volume history, PRs and body
 * composition moved to /review; they are a Sunday-desktop read, and keeping
 * them here is what made this page 10,500px tall and pushed the session below
 * three screens of context on a phone.
 */
export default function NowPage() {
  return (
    <AppShell sections={NOW_SECTIONS}>
      <div className="space-y-4">
        {/* ── THE CALL ── */}
        <section id="today" className="scroll-mt-20 space-y-4">
          <ErrorBoundary label="Athlete operating system">
            <AthleteOSPanel />
          </ErrorBoundary>
          <ErrorBoundary label="Daily report">
            <DailyReport />
          </ErrorBoundary>
        </section>

        {/* ── THE SESSION ── */}
        <section id="plan" className="scroll-mt-20 space-y-4">
          <ErrorBoundary label="Next workout">
            <NextWorkoutCard />
          </ErrorBoundary>
          <ErrorBoundary label="Midday session">
            <MiddaySessionCard />
          </ErrorBoundary>
        </section>

        {/* ── THE INPUT ──
            Check-in feeds tomorrow's prescription, so it is a first-class step
            in the daily loop, not a sidebar widget parked below a duplicate
            readiness dial. Capped to a reading column so the form stays scannable. */}
        <section id="checkin" className="scroll-mt-20 max-w-[520px]">
          <ErrorBoundary label="Check-in">
            <CheckinCard />
          </ErrorBoundary>
        </section>
      </div>
    </AppShell>
  );
}
