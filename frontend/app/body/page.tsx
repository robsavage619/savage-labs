"use client";

import { RhrDevices, RespHalf, Spo2Half, StepsBars, Vo2Trend, WeightTrend } from "@/components/body-board";
import { ClinicalOverview } from "@/components/clinical-overview";
import { FuelingPanel } from "@/components/fueling-panel";
import { GuideProvider, PageHead, Panel, Section } from "@/components/kit";
import { ProgressPhotoPanel } from "@/components/progress-photo-panel";
import { SurfaceShell } from "@/components/surface-shell";
import { TapeCard } from "@/components/tape-card";

/**
 * BODY: is my body changing the way I want?
 *
 * Rebuilt on the kit. The slow movers lead as charts (weight, aerobic
 * fitness, daily movement, resting heart rate), then the airway overnight,
 * then the inputs you log by hand (food, tape, photos) and the clinical
 * record at full width.
 */
export default function BodyPage() {
  return (
    <SurfaceShell>
      <GuideProvider>
        <div className="k-page">
          <PageHead
            eyebrow="Body"
            question="Is my body changing the way I want?"
            lede="Weight and fitness over the long run, how you breathe overnight, what you eat and measure, and the clinical record behind it."
          />

          <Section n="01" title="The slow movers">
            <Panel
              id="composition"
              span={2}
              title="Where is my weight heading?"
              question="Every weigh-in on record."
              guide={{
                what: "Body weight from the scale, through Apple Health.",
                read: "Read the shape over months, not the day-to-day wiggle; water and food timing alone swing a couple of pounds.",
                why: "Under recomposition the target is weight holding steady while strength climbs.",
                ctx: "If it says no reading since a date, the scale hasn't synced; that's missing data, not a stable weight.",
              }}
            >
              <WeightTrend />
            </Panel>
            <Panel
              id="vo2"
              span={2}
              title="Is my aerobic engine growing?"
              question="VO₂ max estimates from the watch."
              guide={{
                what: "The most oxygen your body can use, estimated by the watch from outdoor walks and runs.",
                read: "Higher is better. The trend over a season matters more than any one reading.",
                why: "VO₂ max is among the strongest predictors of long-term health of anything you can train.",
              }}
            >
              <Vo2Trend />
            </Panel>
            <Panel
              id="steps"
              span={2}
              title="How much do I move outside training?"
              question="Daily steps, last 90 days."
              guide={{
                what: "Steps per day from the phone or watch.",
                read: "Cyan days reached 10,000; copper fell short. Gaps are days that didn't report.",
                why: "Everyday movement burns more than the workout does, and it's the easiest lever on a recomp.",
              }}
            >
              <StepsBars />
            </Panel>
            <Panel
              id="rhr-devices"
              span={2}
              title="Resting heart rate, both devices"
              explore="rhr"
              question="WHOOP and Apple Watch, last 90 days."
              guide={{
                what: "Resting heart rate as each device measures it.",
                read: "Lower is fitter. Compare each line with its own past, never with the other device.",
                why: "A slow drift down is aerobic fitness arriving; a sudden rise is stress, illness or short sleep.",
                ctx: "Propranolol lowers it on the days you take it: a drug effect, not fitness.",
              }}
            >
              <RhrDevices />
            </Panel>
          </Section>

          <Section n="02" title="Airway overnight">
            <Panel
              id="airway"
              span={2}
              title="Is my oxygen holding up overnight?"
              question="Nightly SpO₂ average, last 180 nights."
              guide={{
                what: "Average blood-oxygen saturation each night, from the strap.",
                read: "The cyan line is the 7-night mean. Above 95% is unremarkable; a mean that settles below it is worth raising with a doctor. At 92% the planner restricts training.",
                why: "Diagnosed sleep apnea, off CPAP: a slow drift here would have nowhere else to show up.",
              }}
            >
              <Spo2Half />
            </Panel>
            <Panel
              id="resp"
              span={2}
              title="Is my breathing rate drifting?"
              question="Breaths per minute asleep against your own baseline."
              guide={{
                what: "Respiratory rate during sleep, nightly and as a 7-night mean.",
                read: "The line marks where the daily gate starts flagging possible illness, above your 28-night baseline.",
                why: "It's the companion to oxygen: infection and airway load both push it up.",
              }}
            >
              <RespHalf />
            </Panel>
          </Section>

          <Section n="03" title="What you log">
            <Panel id="fueling" span={4} title="Fuelling" question="Protein, calories and hydration from your food logger." bare>
              <FuelingPanel />
            </Panel>
            <Panel id="tape" span={4} title="Tape measurements" question="Waist and girths, by hand." bare>
              <TapeCard />
            </Panel>
            <Panel id="physique" span={4} title="Progress photos" question="Same light, same spot, morning, fasted." bare>
              <ProgressPhotoPanel />
            </Panel>
          </Section>

          <Section n="04" title="Clinical record">
            <Panel id="clinical" span={4} title="Clinical record" question="Conditions, medications, labs, and what's overdue for a re-draw." bare>
              <ClinicalOverview />
            </Panel>
          </Section>
        </div>
      </GuideProvider>
    </SurfaceShell>
  );
}
