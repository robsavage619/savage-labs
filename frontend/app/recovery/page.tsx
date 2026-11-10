"use client";

import { AerobicBaseCard, SleepNeedCard } from "@/components/split-signals";
import { MomentumPanel } from "@/components/momentum-panel";
import { PatternsPane } from "@/components/patterns-pane";
import { PillarRecovery } from "@/components/pillar-recovery";
import { PillarSleep } from "@/components/pillar-sleep";
import { RecoveryTrendPane } from "@/components/trend-intelligence";
import { WhoopVitals } from "@/components/whoop-vitals";
import { SurfaceCard as Card } from "@/components/surface-card";
import { SurfaceShell } from "@/components/surface-shell";

/**
 * RECOVERY — am I absorbing the work?
 *
 * Split out of the old Week page on 2026-11-09. Rows pair cards of similar height so no
 * span leaves half a row empty: the weekly delta beside last night's sleep
 * need, the signal pillars with the aerobic-base dose, then the long trends.
 */
export default function RecoveryPage() {
  return (
    <SurfaceShell>
      <div className="board">
        <div className="board-rule">Where the week stands</div>

        <Card
          id="momentum"
          span={2}
          label="Momentum"
          help="Whether the last 7 days were better or worse than the 7 before them."
          helpDetail={
            <>
              <p>
                Three comparisons: average recovery, average sleep, and sessions trained. The arrow
                and number are the change against the prior week, not the raw value.
              </p>
              <p>
                One week down is noise — bad sleep, a hard tournament, a cold. Two in a row on the
                same tile is the signal worth acting on, usually by adding sleep before subtracting
                training.
              </p>
            </>
          }
        >
          <MomentumPanel />
        </Card>
        <Card
          id="sleep-need"
          span={2}
          label="Sleep need"
          help="Why last night's sleep target was what it was, and how close you came to it."
          helpDetail={
            <>
              <p>
                <strong>What it measures.</strong> WHOOP&apos;s estimate of how much sleep you needed, split into its parts: your
                baseline need, extra for built-up sleep debt, extra for yesterday&apos;s strain, minus any naps.
              </p>
              <p>
                <strong>How to read it.</strong> The copper bars add up from left to right to the total need. The cyan bar
                underneath is what you actually slept.
              </p>
              <p>
                <strong>Why it matters.</strong> Eight hours is the wrong target after a hard day. This shows why the target
                moved and by how much.
              </p>
            </>
          }
        >
          <SleepNeedCard />
        </Card>

        <div className="board-rule">Signals</div>

        <Card
          id="recovery"
          span={1}
          label="Recovery"
          help="How ready your body says it is today, and which signal is driving that number."
          helpDetail={
            <>
              <p>
                The ring is the WHOOP recovery score. <strong>67 and up</strong> is green — train as
                planned. <strong>34–66</strong> is yellow — train, but hold the top end. Under 34 is
                red: the session should be easy or skipped.
              </p>
              <p>
                The chips underneath say why: heart-rate variability against your 28-day baseline
                (in σ, standard deviations), resting heart rate, and last night&apos;s sleep. On
                propranolol days HRV is chemically blunted, so a low σ there is the drug, not
                necessarily your nervous system.
              </p>
            </>
          }
        >
          <PillarRecovery />
        </Card>
        <Card
          id="sleep"
          span={1}
          label="Sleep"
          help="How you actually slept the last seven nights — duration, sleep stages, and how steady your timing was."
          helpDetail={
            <>
              <p>
                Aim for <strong>7.5 hours or more</strong>, with roughly 15–20% deep and 20–25% REM.
                Deep is where the physical repair happens, REM is where the motor learning consolidates
                — a short night usually cuts REM first.
              </p>
              <p>
                Efficiency above 85% and disturbances at 5 or fewer are healthy. The consistency
                figure is how much your mid-sleep time wanders night to night; tight beats long if
                you have to pick one.
              </p>
            </>
          }
        >
          <PillarSleep />
        </Card>
        <Card
          id="vitals"
          span={1}
          label="WHOOP vitals"
          help="Whether WHOOP is still syncing, plus this week's cardio minutes and last night's sleep detail."
          helpDetail={
            <>
              <p>
                Check the sync stamp first — every other card on this page is downstream of it, and a
                &quot;reauth needed&quot; badge means the numbers are frozen, not good.
              </p>
              <p>
                Sleep performance and efficiency want to be 85% or better, consistency 70% or better,
                disturbances 5 or fewer. Respiratory rate and skin temperature are the illness tells:
                both drifting up together is worth a light day. Allergies push them the same
                direction, so read them with the season in mind.
              </p>
            </>
          }
        >
          <WhoopVitals />
        </Card>
        <Card
          id="aerobic-base"
          span={1}
          label="Aerobic base"
          help="Minutes of easy, steady aerobic work this week against the 180-minute weekly dose."
          helpDetail={
            <>
              <p>
                <strong>What it measures.</strong> Minutes in the last 7 days in WHOOP heart-rate zones 2 and 3 together,
                about 70–85% of your max.
              </p>
              <p>
                <strong>How to read it.</strong> The arc fills toward 180 minutes. The bars below show every zone; the cyan
                ones are what count.
              </p>
              <p>
                <strong>Why it matters.</strong> This work builds the aerobic base that speeds recovery between sets and
                between days. WHOOP&apos;s zone 2 alone undercounts it by roughly 40%.
              </p>
            </>
          }
        >
          <AerobicBaseCard />
        </Card>

        <div className="board-rule">Trends</div>

        <Card
          id="recovery-trend"
          span={2}
          label="Recovery trend"
          help="Three months of recovery and nervous-system data, so slow drift shows up before it becomes a slump."
          helpDetail={
            <>
              <p>
                The grid is one square per day, darker meaning better recovery — read it for streaks
                and clusters, not single days. The chart under it plots heart-rate variability with a
                shaded band of ±1σ, your normal range; sustained trips below the band matter, single
                dips do not.
              </p>
              <p>
                The pre-illness strip flags days where resting heart rate rose and HRV fell together.
                Two or three of those in a row is the classic run-up to getting sick, and the cheapest
                response is an early night rather than a skipped block.
              </p>
            </>
          }
        >
          <RecoveryTrendPane />
        </Card>
        <Card
          id="patterns"
          span={2}
          label="Patterns"
          help="Which days you recover best on, and how strongly sleep and heart-rate variability track your recovery."
          helpDetail={
            <>
              <p>
                The day-of-week bars are all-time averages: a reliably low day usually traces back to
                a fixed habit — weekend pickleball, a late Friday, a Sunday night.
              </p>
              <p>
                The two scatter plots show how tightly sleep hours and heart-rate variability track
                recovery for <em>you</em>. A steep, tight cloud means that input is worth protecting;
                a shapeless one means the score is being driven by something else that week.
              </p>
            </>
          }
        >
          <PatternsPane />
        </Card>
      </div>
    </SurfaceShell>
  );
}
