"use client";

import { AfterActionPanel } from "@/components/after-action-panel";
import { SurfaceShell } from "@/components/surface-shell";
import { CardHelp } from "@/components/card-help";
import { CardioPanel } from "@/components/cardio-panel";
import { ErrorBoundary } from "@/components/error-boundary";
import { GoalScorecard } from "@/components/goal-scorecard";
import { MomentumPanel } from "@/components/momentum-panel";
import { MuscleVolumePanel } from "@/components/muscle-volume-panel";
import { PatternsPane } from "@/components/patterns-pane";
import { PeriodizationStrip } from "@/components/periodization-strip";
import { PerformanceCurvePane } from "@/components/performance-curve";
import { PickleballPane } from "@/components/pickleball-panel";
import { TournamentReadiness } from "@/components/tournament-readiness";
import { PillarRecovery } from "@/components/pillar-recovery";
import { PillarSleep } from "@/components/pillar-sleep";
import { PillarTrainingLoad } from "@/components/pillar-training-load";
import { PostWorkoutPanel } from "@/components/post-workout-panel";
import { PrescriptionPanel } from "@/components/prescription-panel";
import {
  LastSessionCard,
  TrainingConsistencyCard,
  MuscleBalanceCard,
  RecoveryTrainingCard,
  VolumeLoadCard,
  MostTrainedCard,
} from "@/components/strength-panel";
import { RecoveryTrendPane, VolumeLandmarks } from "@/components/trend-intelligence";
import { WhoopVitals } from "@/components/whoop-vitals";

import type { Span } from "@/lib/sections";

/**
 * One card on the board. The `id` is the anchor the command palette and every
 * deep link scroll to, so it must match a row in `sectionsFor("week")` — that
 * manifest is the only place section ids are declared.
 *
 * Nothing here collapses. A card that has to be opened is a card that never
 * gets read; the four-column grid is what buys the room to leave it all open.
 *
 * `help` is mandatory, not optional. Explanations used to exist on 10 of 21
 * cards and read like release notes for the engine ("Banister TSB (452 EWMA of
 * composite load)"); making the prop required is what stops the next card from
 * shipping without one. One sentence, plain words, second person — the
 * acronyms are allowed only in `helpDetail`, where there is room to define
 * them.
 */
function Card({
  id,
  span,
  label,
  help,
  helpDetail,
  children,
}: {
  id: string;
  span: Span;
  label: string;
  help: string;
  helpDetail?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section id={id} className={`span-${span} scroll-mt-24`}>
      <CardHelp summary={help}>{helpDetail}</CardHelp>
      <ErrorBoundary label={label}>{children}</ErrorBoundary>
    </section>
  );
}

/**
 * WEEK — what changed, and how training is going.
 *
 * Reads top-down as the weekly review actually runs: the delta and the block
 * position first, then the three signal pillars that explain them, then the
 * longitudinal trend, then training (performance → strength → volume), then
 * output (cardio, sport), then the debrief and the scorecard.
 *
 * SPANS ARE MEASURED, NOT GUESSED. Every row below pairs cards whose rendered
 * heights are within ~2x of each other, and every row fills all four columns —
 * grid auto-placement follows source order, so the order IS the layout. The
 * two rules that produced this arrangement:
 *
 *   - a card's height is a function of its width, so a dense panel starved of
 *     columns just grows downward (Pickleball at span-1 rendered 392x1339 —
 *     a quarter-column pillar of unreadable text);
 *   - a short card at span-4 owns a whole row for nothing (Momentum rendered
 *     1616x184), so it gets a partner of similar height instead.
 *
 * The corollary was being missed: a span-2 card with no partner is just as
 * wrong, and four of them (Most trained, Volume prescription, Cardio,
 * Pickleball) were leaving ~3,400px of empty right-hand column between them.
 * A card with nothing beside it takes span-4.
 */
export default function WeekPage() {
  return (
    <SurfaceShell>
      <div className="board">
        {/* ── Where the week stands ────────────────────────────────────────
            Two short strips, paired: the delta (184px) and the block position
            (265px). Neither has the content to justify a row of its own. */}
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

        {/* ── Signals ──────────────────────────────────────────────────────
            Four pillar tiles, 350–469px tall — the tightest row on the board,
            and the one case where span-1 is the right size. */}
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
        {/* Two longitudinal panes, 755px and 668px — an even row. */}
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

        {/* ── Training ─────────────────────────────────────────────────────
            Two full-width panels (a time-series curve and the strength
            heatmap, both of which read better the wider they get), then the
            tall dose pair: volume 1552px beside prescription 999px. */}
        <div className="board-rule">Training</div>
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
        {/* StrengthPanel was ONE card 1,559px tall containing six independent
            blocks — four of them under 150px. Measured heights: last session 77,
            consistency 141, balance 127, recovery×training 111, volume load 491,
            most trained 381. As one card the four small ones were trapped in a
            skyscraper; as six they fill two clean rows. */}
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

        {/* ── Output ───────────────────────────────────────────────────────
            Both panels are dense; splitting the row evenly is what makes the
            Pickleball pane readable at all (it was 392px wide, 1339px tall). */}
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

        {/* ── Debrief ──────────────────────────────────────────────────────
            552px and 571px — already the flattest row on the page. */}
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
