"use client";

import { AfterActionPanel } from "@/components/after-action-panel";
import { CardioPanel } from "@/components/cardio-panel";
import { GoalScorecard } from "@/components/goal-scorecard";
import {
  LastSessionCard,
  MostTrainedCard,
  MuscleBalanceCard,
  RecoveryTrainingCard,
  TrainingConsistencyCard,
  VolumeLoadCard,
} from "@/components/strength-panel";
import { MonotonyCard } from "@/components/split-signals";
import { MuscleVolumePanel } from "@/components/muscle-volume-panel";
import { PerformanceCurvePane } from "@/components/performance-curve";
import { PeriodizationStrip } from "@/components/periodization-strip";
import { PickleballPane } from "@/components/pickleball-panel";
import { PillarTrainingLoad } from "@/components/pillar-training-load";
import { PostWorkoutPanel } from "@/components/post-workout-panel";
import { PrescriptionPanel } from "@/components/prescription-panel";
import { TournamentReadiness } from "@/components/tournament-readiness";
import { VolumeLandmarks } from "@/components/trend-intelligence";
import { SurfaceCard as Card } from "@/components/surface-card";
import { SurfaceShell } from "@/components/surface-shell";

/**
 * TRAINING — am I growing, muscle by muscle?
 *
 * Split out of the old Week page: block position and load shape first, then
 * performance and strength, per-muscle volume against its landmarks, output
 * (cardio, sport) and the debrief. Card spans carry over from Week, where
 * they were measured.
 */
export default function TrainingPage() {
  return (
    <SurfaceShell>
      <div className="board">
        <div className="board-rule">The block</div>

        <Card
          id="meso"
          span={2}
          label="Mesocycle"
          help="Which week of the current training block you are in, and how fresh you are right now."
          helpDetail={
            <>
              <p>
                Left side: the block runs a few accumulation weeks and ends in a deload, and the
                strip marks where today sits. Right side is <strong>form</strong> — fitness (CTL)
                built over 42 days, fatigue (ATL) built over 7, and TSB, the difference between
                them.
              </p>
              <p>
                TSB above about +5 means you are fresh and can push; below −10 means fatigue is
                running ahead of recovery. Deep negatives late in a block are expected — that is
                what the deload week is for.
              </p>
            </>
          }
        >
          <PeriodizationStrip />
        </Card>
        <Card
          id="load"
          span={1}
          label="Training load"
          help="Whether the last week has been harder on you than the last month, and today's verdict."
          helpDetail={
            <>
              <p>
                This is the acute:chronic workload ratio (ACWR) — the last 7 days measured against
                your 28-day average. The pillar derives it from recovery scores rather than tonnage,
                so it reflects what training cost you, not what you lifted.
              </p>
              <p>
                <strong>0.8–1.3 is the build zone</strong>: enough new stress to adapt, not enough to
                break. Above 1.5 is a spike, and the injury risk climbs with it; well under 0.8 means
                you are detraining. &quot;Today&apos;s call&quot; is what the engine did with that —
                if it says capped, a safety gate lowered the intensity ceiling for the day.
              </p>
            </>
          }
        >
          <PillarTrainingLoad />
        </Card>
        <Card
          id="monotony"
          span={1}
          label="Monotony"
          help="How alike your training days were each week. Variety between hard and easy days protects you."
          helpDetail={
            <>
              <p>
                <strong>What it measures.</strong> Average daily training load divided by how much it varied from day to day,
                per week (Foster monotony).
              </p>
              <p>
                <strong>How to read it.</strong> A taller bar means the days that week were more alike. The red dashed line
                at 2.0 is a common warning level.
              </p>
              <p>
                <strong>Why it matters.</strong> Training the same way every day, even at a moderate load, is linked to
                illness and going stale. The load ratio can&apos;t see this; it only compares totals.
              </p>
            </>
          }
        >
          <MonotonyCard />
        </Card>

        <div className="board-rule">Performance</div>

        <Card
          id="performance"
          span={4}
          label="Performance curve"
          help="Ninety days of fitness against fatigue — the long view of whether the training is actually working."
          helpDetail={
            <>
              <p>
                <strong>CTL (fitness)</strong> is a 42-day average of your training load: it climbs
                slowly and is the line you want going up. <strong>ATL (fatigue)</strong> is the 7-day
                version — it spikes after hard weeks and clears fast. <strong>TSB (form)</strong> is
                CTL minus ATL.
              </p>
              <p>
                TSB between <strong>+5 and +20</strong> is the window where you perform best — worth
                aiming at before a tournament. Around zero is normal training. Below −25 is deep
                overreach: fine for a week, a problem if it persists, and the deload banner will say
                so.
              </p>
            </>
          }
        >
          <PerformanceCurvePane />
        </Card>
        <Card
          id="last-session"
          span={4}
          label="Last session"
          help="A four-number status check: when you last lifted, this week's work, and where load is heading."
          helpDetail={
            <>
              <p>
                Days-ago turns amber past 2 days and red past 5 — for hypertrophy each muscle wants
                hitting about twice a week, so a long gap costs more than a light session would have.
              </p>
              <p>
                Frequency is a rolling 8-week average; 3–4 lifting days a week is the target. Load
                trend compares the last 8 weeks against the 8 before: a positive number is
                progressive overload, a negative one means the week&apos;s volume actually fell,
                whatever it felt like.
              </p>
            </>
          }
        >
          <LastSessionCard />
        </Card>
        <Card
          id="consistency"
          span={4}
          label="Training consistency"
          help="Two years of training days at a glance — how often you show up, and where the gaps opened."
          helpDetail={
            <>
              <p>
                One square per day, brighter for more work done. Hover any square for that day&apos;s
                sets and total weight moved.
              </p>
              <p>
                Read the shape, not the squares. Long pale stretches are the thing that actually
                costs muscle — missed weeks show up in this grid months before they show up in the
                strength numbers.
              </p>
            </>
          }
        >
          <TrainingConsistencyCard />
        </Card>
        <Card
          id="balance"
          span={2}
          label="Muscle balance"
          help="Whether push, pull, legs, and core are all getting worked, or one has quietly been dropped."
          helpDetail={
            <>
              <p>
                Each bar is weekly sets against that group&apos;s target, tagged on target, below, or
                neglected. Neglected means under half the target — that is where an imbalance starts.
              </p>
              <p>
                The push:pull ratio at the top is the one to watch. Near <strong>1.0</strong> is
                balanced; over 1.4 is push-dominant, which over time rounds the shoulders forward and
                is the common pattern for anyone who also serves and hits overhead.
              </p>
            </>
          }
        >
          <MuscleBalanceCard />
        </Card>
        <Card
          id="recovery-training"
          span={2}
          label="Recovery × training"
          help="What training actually costs you the next morning, and whether you pick good days to train."
          helpDetail={
            <>
              <p>
                Compares average recovery on days you trained with days you rested, then the
                next-day difference. A delta of about <strong>−5 or worse</strong> means sessions are
                outrunning your recovery and something has to give: volume, intensity, or sleep.
              </p>
              <p>
                If train-day recovery runs clearly higher than rest-day recovery, that is good
                self-regulation — you are already choosing to lift on the days your body can take it.
              </p>
            </>
          }
        >
          <RecoveryTrainingCard />
        </Card>
        <Card
          id="most-trained"
          span={4}
          label="Most trained"
          help="The ten exercises you do most, with your best lift on each — click one for its full history."
          helpDetail={
            <p>
              Useful as an audit of where the time is going. If the top of this list is all the same
              movement pattern, the muscles that pattern misses are the ones drifting under target on
              the volume cards. Clicking a row opens its progression over time.
            </p>
          }
        >
          <MostTrainedCard />
        </Card>
        <Card
          id="volume-load"
          span={4}
          label="Volume load"
          help="Total weight lifted each week for a year, and whether your main lifts are still getting stronger."
          helpDetail={
            <>
              <p>
                The bars are weekly tonnage against your 52-week average, so the trend line matters
                more than any one bar — a deload week is supposed to dip. The badge names it:
                progressive overload, maintained, or a volume reduction.
              </p>
              <p>
                The sparklines are <strong>e1RM</strong> — estimated one-rep max, worked out from the
                weight and reps you logged, so it tracks strength without needing to test a true
                max. Flat is fine during a hard block; falling across several lifts at once is a
                genuine regression signal. Click any lift for its full history.
              </p>
            </>
          }
        >
          <VolumeLoadCard />
        </Card>

        <div className="board-rule">Volume</div>

        <Card
          id="volume"
          span={2}
          label="Volume vs landmarks"
          help="How many sets each muscle got this week, against the range that actually builds it."
          helpDetail={
            <>
              <p>
                Three thresholds per muscle, from Renaissance Periodization&apos;s research:{" "}
                <strong>MEV</strong> is the least that still grows anything, <strong>MAV</strong> is
                where the growth per set starts falling off, and <strong>MRV</strong> is the most you
                can recover from.
              </p>
              <p>
                Below MEV is maintenance at best. Between MEV and MAV is the productive zone and
                where most muscles should sit. Past MRV is junk volume — fatigue with no extra
                growth. Exercises listed as unmapped are not counted at all, which can make a muscle
                look emptier than it is.
              </p>
            </>
          }
        >
          <VolumeLandmarks />
        </Card>
        <Card
          id="per-muscle"
          span={2}
          label="Per-muscle volume"
          help="The same question one muscle at a time — which specific muscles are short this week."
          helpDetail={
            <p>
              The card above groups everything into push, pull, legs and core. This one breaks it
              out per muscle, because a group can look healthy while one muscle inside it gets
              nothing. Muscles are ordered worst-first, so the top of the list is where to add sets.
            </p>
          }
        >
          <MuscleVolumePanel />
        </Card>
        <Card
          id="prescription"
          span={4}
          label="Volume prescription"
          help="How many sets each muscle should get this week, and whether to add work, hold, or cut."
          helpDetail={
            <>
              <p>
                Each row reads current sets → target sets, with the engine&apos;s call beside it. The
                target is not a generic template: it is adapted from your recent strength numbers,
                soreness, and how much court and cardio load you are carrying. A ★ marks an emphasis
                muscle you have asked to prioritise.
              </p>
              <p>
                A red deload banner means volume has been halved deliberately and loads should stay
                moderate — that is a planned week, not a setback. The short line under each muscle is
                the reason for its call, and it is the part worth reading before you argue with the
                number.
              </p>
            </>
          }
        >
          <PrescriptionPanel />
        </Card>

        <div className="board-rule">Output</div>

        <Card
          id="cardio"
          span={4}
          label="Cardio"
          help="How much conditioning you are doing, how hard it is, and whether your engine is improving."
          helpDetail={
            <>
              <p>
                The four tiles compare the last 14 days with the 14 before. The one to trust is{" "}
                <strong>average heart rate</strong>: if it falls while minutes and effort hold steady,
                your aerobic fitness is genuinely improving.
              </p>
              <p>
                Zone minutes come from WHOOP&apos;s own bands off your measured max heart rate, not a
                textbook percentage. Most of the week should sit in the easy zones — that is the
                aerobic base that makes hard sessions repeatable. The pickleball efficiency chart
                tracks heart rate per minute of play, so a downward drift there means the same game
                is costing you less.
              </p>
            </>
          }
        >
          <CardioPanel />
        </Card>
        <Card
          id="event-prep"
          span={4}
          label="Tournament readiness"
          help="How you prepared for, played at, and recovered from each tournament — day by day."
          helpDetail={
            <>
              <p>
                Each strip is the eleven days around one event: seven before, the day itself, and
                three after. Bar height is that morning&apos;s recovery, and the markers underneath
                are what you actually did — gym sessions and court minutes. A taper would show as
                load emptying out over the last 72 hours.
              </p>
              <p>
                <strong>It has not, so far.</strong> Before the PNW Team Cup you lifted six times
                and played 277 minutes in the prior three days, 216 of them the day before, and
                started the event on 41 recovery.
              </p>
              <p>
                Three events is not enough to tell you what preparation works, and the numbers
                currently point the wrong way — your best rating gain came off your worst recovery
                and your worst result off your best. Read this as a record of what you did, not
                as advice.
              </p>
            </>
          }
        >
          <TournamentReadiness />
        </Card>
        <Card
          id="sport"
          span={4}
          label="Pickleball"
          help="How much you are playing, how fresh you play, and how quickly you bounce back afterwards."
          helpDetail={
            <>
              <p>
                <strong>Play freshness</strong> is your average recovery on days you play. Playing
                competitively on low-recovery days is where the decision-making errors and the soft
                tissue injuries both come from.
              </p>
              <p>
                The HRV delta compares the morning after a session with the day of it. Consistently
                negative means matches are costing you more than they used to; trending toward zero
                over months means your conditioning is catching up with your play. Tournament rows
                show results with the rating change alongside.
              </p>
            </>
          }
        >
          <PickleballPane />
        </Card>

        <div className="board-rule">Debrief</div>

        <Card
          id="post"
          span={2}
          label="Post-workout debrief"
          help="What your last session actually delivered versus the plan, and what to lift next time."
          helpDetail={
            <>
              <p>
                Two steps, in order: copy the prompt, paste it into Claude Code after you train, then
                hit sync to pull the session and its write-up back in.
              </p>
              <p>
                The table underneath is per exercise — sets, reps, load and effort against what was
                planned, ending in a verdict of progress, repeat, or drop, plus the weight to use
                next time. It only works properly if you log RPE in Hevy; without it the engine has
                to guess how hard the sets actually were.
              </p>
            </>
          }
        >
          <div className="space-y-4">
            <PostWorkoutPanel />
            <AfterActionPanel />
          </div>
        </Card>
        <Card
          id="goals"
          span={2}
          label="2026 goal scorecard"
          help="The three things 2026 is being judged on: your pickleball rating, your key lifts, and your bodyweight."
          helpDetail={
            <>
              <p>
                <strong>DUPR</strong> is the pickleball rating; the bar shows how much of the gap to
                the 5.0 target you have closed since baseline. It moves in tournaments, not in
                practice, so long flat stretches are expected.
              </p>
              <p>
                The key lifts should be holding or climbing — training this much cardio and court
                time while adding strength is the hard part, and holding counts as a win. Bodyweight
                moving less than about half a pound a week is the stable window where recomposition
                is actually happening.
              </p>
            </>
          }
        >
          <GoalScorecard />
        </Card>
      </div>
    </SurfaceShell>
  );
}
