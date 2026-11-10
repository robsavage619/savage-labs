"use client";

import { AfterActionPanel } from "@/components/after-action-panel";
import { CardioPanel } from "@/components/cardio-panel";
import { GoalScorecard } from "@/components/goal-scorecard";
import { GuideProvider, PageHead, Panel, Section } from "@/components/kit";
import { PickleballPane } from "@/components/pickleball-panel";
import { PostWorkoutPanel } from "@/components/post-workout-panel";
import { SurfaceShell } from "@/components/surface-shell";
import { TournamentReadiness } from "@/components/tournament-readiness";
import { BalanceBars, BlockStrip, FitnessFatigue, FormChart, GrowthZones, LiftBoard, MonotonyBars, WeeklyVolume } from "@/components/training-board";

/**
 * TRAINING: am I growing, muscle by muscle?
 *
 * Rebuilt on the kit. Growth zones and the lift scoreboard lead because they
 * answer the question directly; load shape, the block and consistency explain
 * them; court and conditioning, then the debrief, close the page. Replaced and
 * retired from this page: the per-muscle and landmark tables, prescription
 * text, last-session strip, consistency heatmap, most-trained and volume-load
 * lists, the old performance curve and the training-load pillar.
 */
export default function TrainingPage() {
  return (
    <SurfaceShell>
      <GuideProvider>
        <div className="k-page">
          <PageHead
            eyebrow="Training"
            question="Am I growing, muscle by muscle?"
            lede="Whether each muscle is getting a growing dose, whether each lift is going up, and whether the load around them is building or piling up."
          />

          <Section n="01" title="Growth">
            <Panel
              id="growth"
              span={4}
              title="Is each muscle in its growth range?"
              question="Hard sets per muscle per week against the minimum that grows it and the most you can recover from. Scrub back through the block."
              guide={{
                what: "Working sets each muscle got in one week, counted the way the engine counts them: a compound lift also credits the muscles that help it, set for set.",
                read: "The grey bar is the useful range, from the minimum that grows muscle (MEV) to the most you can recover from (MRV); the lighter part is the sweet spot (MAV to MRV). The coloured line is what you did. Priority muscles are tagged grow and listed first.",
                why: "Muscle grows when weekly sets land in this range. Too few only maintains; too many adds fatigue without adding growth.",
                ctx: "Targets are the active block's. Maintenance muscles sit under the minimum on purpose; the grow muscles are the ones to watch.",
              }}
            >
              <GrowthZones />
            </Panel>
          </Section>

          <Section n="02" title="Strength">
            <Panel
              id="lifts"
              span={4}
              title="Is each lift going up?"
              question="Every lift from the last 12 weeks, by trend. Pick one to see its history."
              guide={{
                what: "Each lift's estimated one-rep max and trend over 12 weeks, plus the top set of every session for the lift you pick.",
                read: "Green dots are progressing, amber stalled, red going backwards. The number is the estimated one-rep max in lb. The chart is the heaviest set each session.",
                why: "It's the quickest answer to whether you're getting stronger, and which lifts need a change.",
                ctx: "Dumbbell weights are per hand.",
              }}
            >
              <LiftBoard />
            </Panel>
          </Section>

          <Section n="03" title="Load">
            <Panel
              id="fitness"
              span={2}
              title="Fitness vs fatigue"
              question="Ninety days of slow-building fitness against fast-moving fatigue."
              explore="load"
              guide={{
                what: "Two rolling averages of daily training load: fitness over about 6 weeks and fatigue over about 1 week.",
                read: "When the copper fatigue line runs above the cyan fitness line you're training harder than you're used to; when it drops below, you're fresher.",
                why: "Fitness builds and fades slowly, fatigue fast. You perform best when fitness is high and fatigue has just come down.",
              }}
            >
              <FitnessFatigue />
            </Panel>
            <Panel
              id="form"
              title="Form"
              question="Fitness minus fatigue."
              explore="form"
              guide={{
                what: "Fitness minus fatigue, usually called form.",
                read: "Above zero is fresh, below zero is carrying fatigue. Weeks well below zero mean you're digging a hole.",
                why: "The simplest single read on whether this week should be hard or easy.",
              }}
            >
              <FormChart />
            </Panel>
            <Panel
              id="monotony"
              title="Is every week the same week?"
              question="How alike your training days were, per week."
              guide={{
                what: "Average daily load divided by its day-to-day variation, per week (Foster monotony).",
                read: "Taller bars mean the days were more alike. The red line at 2.0 is a common warning level.",
                why: "Training the same way every day, even moderately, is linked to illness and going stale.",
              }}
            >
              <MonotonyBars />
            </Panel>
          </Section>

          <Section n="04" title="The block">
            <Panel
              id="block"
              span={2}
              title="Where you are in the block"
              question="Mesocycle position and the sets each week of it."
              explore="sets"
              guide={{
                what: "The current training block (mesocycle) week by week, and the working sets you did in each of its weeks.",
                read: "Filled weeks are done, the bright one is now, the dashed DL is the planned deload. The bars are sets per week.",
                why: "Volume climbs through a block, then drops in a deload so fatigue clears and the gains show.",
              }}
            >
              <BlockStrip />
            </Panel>
            <Panel
              id="balance"
              span={2}
              title="Push, pull, legs, core"
              question="Where the last four weeks of sets went."
              guide={{
                what: "Average working sets per week by movement group over the last 4 weeks.",
                read: "Longer bars got more work. The percentage is each group's share of all sets.",
                why: "A group that quietly drops off is how imbalances and nagging shoulders start.",
              }}
            >
              <BalanceBars />
            </Panel>
          </Section>

          <Section n="05" title="Consistency">
            <Panel
              id="weekly"
              span={4}
              title="How often you actually train"
              question="Working sets per week for the last 26 weeks."
              explore="sets"
              guide={{
                what: "Total working sets logged each week, all muscles together.",
                read: "Each bar is a week. Gaps and short bars are missed sessions; hover for the count.",
                why: "Frequency, more than anything inside a session, is what has driven your volume up and down this year.",
              }}
            >
              <WeeklyVolume />
            </Panel>
          </Section>

          <Section n="06" title="Court and conditioning">
            <Panel id="cardio" span={4} title="Cardio" question="Sessions, heart-rate zones and the aerobic dose." bare>
              <CardioPanel />
            </Panel>
            <Panel id="sport" span={4} title="Pickleball" question="Rating, matches and court load." bare>
              <PickleballPane />
            </Panel>
            <Panel id="event-prep" span={4} title="Tournament readiness" question="How fresh you'll be on the day." bare>
              <TournamentReadiness />
            </Panel>
          </Section>

          <Section n="07" title="Debrief">
            <Panel id="post" span={4} title="After the session" question="How the last session went against its plan." bare>
              <PostWorkoutPanel />
              <AfterActionPanel />
            </Panel>
            <Panel id="goals" span={4} title="2026 goals" question="Where each goal stands." bare>
              <GoalScorecard />
            </Panel>
          </Section>
        </div>
      </GuideProvider>
    </SurfaceShell>
  );
}
