"use client";

import { AthleteOSPanel } from "@/components/athlete-os-panel";
import { CardHelp } from "@/components/card-help";
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
 *
 * The report is stacked under the session in the same three-column stack rather
 * than given its own band below. The check-in is a ~960px sidebar whatever width
 * it gets, and on a day the session is already logged the prescription card
 * collapses to a 280px receipt — which left ~890px of empty board beside the
 * sidebar. Stacking closes most of that, and on an untrained day the two columns
 * come out near enough level.
 *
 * Each panel here brings its own card chrome and its own heading, so unlike the
 * body and lab boards there is no local wrapper to hang the explanation on. The
 * `CardHelp` therefore sits inline as the first child of every section — same
 * position, same padding, in every case.
 */
export default function TodayPage() {
  return (
    <SurfaceShell>
      <div className="board">
        <section id="call" className="span-4 scroll-mt-24">
          <div className="px-1">
            <CardHelp summary="Today's verdict on how hard to train — and which muscles are locked out entirely.">
              <p>
                The red <strong>Locked today</strong> strip is the part to read first. It
                only appears when the engine has actually restricted something: red chips
                are whole movement patterns barred for the day, amber ones are single
                muscles, an intensity ceiling, or a required deload, and the line beneath
                gives the reason. Nothing you program should touch a locked chip — the plan
                builder will refuse it anyway, and this is where you find that out before
                you have written the session rather than after.
              </p>
              <p>
                The four tiles are, in order: the call itself and why today looks like this;
                the goal pressure pulling on it, usually a push-versus-pull imbalance or
                court load to protect your legs from; whichever self-experiment is currently
                running; and the strongest thing this system has actually proven about you.
              </p>
              <p>
                The ages along the top row are how stale each data feed is. Anything past a
                day means today&apos;s call is resting on yesterday&apos;s body, and is worth
                a sync before you trust it.
              </p>
            </CardHelp>
          </div>
          <ErrorBoundary label="Today's call">
            <AthleteOSPanel />
          </ErrorBoundary>
        </section>

        <div className="board-rule">The session</div>

        <div className="span-3 flex flex-col gap-4">
        <section id="session" className="scroll-mt-24">
          <div className="px-1">
            <CardHelp summary="Today's prescribed lifts — sets, reps, load and target effort — ready to push to Hevy.">
              <p>
                Each exercise carries a target weight and a target effort level, where 10
                would be a set you could not add another rep to; most working sets here are
                aimed at 7–9. Prescribed loads are anchored to what you have actually logged
                recently, and dumbbell numbers are the weight in <em>one hand</em>, not the
                pair.
              </p>
              <p>
                <strong>Hevy</strong> pushes the whole session across as a routine to log
                against — that logging is what feeds tomorrow&apos;s prescription, so a
                session trained but not logged is invisible to the engine. A
                <em> Trained</em> badge means today&apos;s work is already recorded;
                <em> Not today&apos;s</em> means you are looking at a plan carried over from
                an earlier day, so regenerate before following it.
              </p>
              <p>
                <em>Why this session</em> opens the reasoning: what drove the exercise
                selection, any clinical constraints applied, and the research the choice
                leans on. Worth opening the first time an unfamiliar lift appears — a swapped
                exercise usually has no recent load history, which is why it may arrive
                without a weight.
              </p>
            </CardHelp>
          </div>
          <ErrorBoundary label="Next workout">
            <NextWorkoutPane />
          </ErrorBoundary>
        </section>
        <section id="report" className="scroll-mt-24">
          <div className="px-1">
            <CardHelp summary="The written read on your morning: what your sleep and recovery numbers actually mean today.">
              <p>
                The ring is this system&apos;s own readiness score, which reconciles the raw
                numbers against the day&apos;s gates; the tracker&apos;s separate score sits
                beside it as a stat, and the two disagreeing is informative rather than a
                fault.
              </p>
              <p>
                On the stats: the figure next to <strong>HRV</strong> is how many standard
                deviations you are from your own 28-day baseline, so −1σ or worse alongside a
                raised resting heart rate is a genuine recovery day rather than one bad
                night. The <strong>load ratio</strong> compares recent training against your
                established base — above roughly 1.5 means the last week has outrun what your
                body is conditioned for, and it is the usual reason a muscle appears locked
                in the card at the top of this page.
              </p>
              <p>
                The narrative is not automatic: <strong>Generate daily report</strong> copies
                a prompt to run in Claude Code, which posts the written version back. Check
                the date beside the heading — an old date means you are reading an old
                morning.
              </p>
            </CardHelp>
          </div>
          <ErrorBoundary label="Daily report">
            <DailyReport />
          </ErrorBoundary>
        </section>
        </div>

        <div className="span-1 flex flex-col gap-4">
          <section id="midday" className="scroll-mt-24">
            <div className="px-1">
              <CardHelp summary="Your lunch-hour session at work: what to do, for how long, and what it's for.">
                <p>
                  This is built around whatever the morning call left in the tank, which is
                  why it is tagged workout, recovery, or mixed. On a day the gates are tight
                  it will deliberately be a recovery session — doing it as prescribed is what
                  keeps it from eating into the evening lift.
                </p>
                <p>
                  The figure under the activity list is planned minutes against the session
                  budget. If no plan exists yet, <strong>Generate plan</strong> copies a
                  prompt to run in Claude Code, which writes one back here.
                </p>
              </CardHelp>
            </div>
            <ErrorBoundary label="Midday session">
              <MiddaySessionCard />
            </ErrorBoundary>
          </section>
          <section id="checkin" className="scroll-mt-24">
            <div className="px-1">
              <CardHelp summary="Thirty seconds of self-report — this is the input tomorrow's prescription is built from.">
                <p>
                  Wearables cannot see soreness, stress or motivation, so these five sliders
                  are the only route those have into the engine. They are not decoration:
                  they move the gates directly, which is why the day you skip it is the day
                  the plan is least likely to fit you. All of them run 1–10, higher meaning
                  more of the named thing — so a high stress or soreness score is the one
                  that pulls tomorrow&apos;s load down.
                </p>
                <p>
                  Tap the body map to mark <strong>where</strong> you are sore; that is what
                  lets tomorrow route volume away from one muscle instead of dropping the
                  whole session. The propranolol toggle matters for the same reason —
                  it suppresses heart rate and variability, and flagging it stops a
                  drug effect from being read as recovery. <em>Sick</em> and
                  <em> Traveling</em> tell the engine to stop treating a bad week as
                  detraining.
                </p>
                <p>Everything saves as you touch it; there is no submit button.</p>
              </CardHelp>
            </div>
            <ErrorBoundary label="Check-in">
              <CheckinCard />
            </ErrorBoundary>
          </section>
        </div>

      </div>
    </SurfaceShell>
  );
}
