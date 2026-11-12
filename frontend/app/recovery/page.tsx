"use client";

import { GuideProvider, PageHead, Panel, Section } from "@/components/kit";
import {
  AerobicBase,
  DayOfWeek,
  DayStrip,
  EventMarkers,
  HrvBand,
  Places,
  RecoveryMix,
  RecoveryScoreTrend,
  RhrTrend,
  SleepNeed,
  SleepStages,
  SleepTiming,
  StressRhythm,
  Spo2Burden,
  Verdict,
  WeekOverWeek,
} from "@/components/recovery-board";
import { SurfaceShell } from "@/components/surface-shell";

/**
 * RECOVERY: am I absorbing the work?
 *
 * Rebuilt on the kit. The nervous system first (HRV, resting HR, recovery,
 * each against your own normal), then sleep, then the week and the aerobic
 * and oxygen signals, then long-run patterns. Retired from the page: the
 * recovery and sleep pillars, raw WHOOP vitals, the old trend and patterns
 * panes, and the momentum strip, all redrawn here.
 */
export default function RecoveryPage() {
  return (
    <SurfaceShell>
      <GuideProvider>
        <div className="k-page">
          <PageHead
            eyebrow="Recovery"
            question="Am I absorbing the work?"
            lede="Your nervous system and sleep against your own normal, the week against the one before, and the patterns underneath."
          />

          <Verdict />

          <Section n="01" title="Nervous system">
            <Panel
              id="hrv"
              span={2}
              title="HRV against your own baseline"
              question="Ninety nights, with your 28-day average and its normal band."
              explore="hrv"
              guide={{
                what: "Heart rate variability each night, with your rolling 28-day average and a band of plus or minus one standard deviation.",
                read: "Cyan is each night, copper the 28-day average, the shaded band your normal range. One night below the band means little; several in a row means something.",
                why: "HRV reflects how settled your nervous system is. Only compare it to yourself; it varies hugely between people.",
                ctx: "Watch the copper line: a sliding average is a bigger story than any single night.",
              }}
            >
              <HrvBand />
            </Panel>
            <Panel
              id="rhr"
              title="Resting heart rate"
              question="Ninety mornings against your baseline."
              explore="rhr"
              guide={{
                what: "Resting heart rate each morning, with your 28-day baseline.",
                read: "Points above the dashed baseline are higher than your normal.",
                why: "A run of higher mornings often comes before illness or after hard weeks.",
              }}
            >
              <RhrTrend />
            </Panel>
            <Panel
              id="recovery"
              title="Recovery score"
              question="WHOOP's daily score, ninety mornings."
              explore="recovery"
              guide={{
                what: "WHOOP's 0–100 recovery score each morning.",
                read: "Above the 67 line is green, below 34 is red.",
                why: "It blends HRV, resting HR and sleep into one number; the trend matters more than the day.",
              }}
            >
              <RecoveryScoreTrend />
            </Panel>
            <Panel
              id="events"
              span={4}
              title="What happened"
              question="Mark illness, travel or a tournament, and the charts above show it."
              guide={{
                what: "Dated notes you add yourself, drawn as dashed lines on the HRV and recovery charts.",
                read: "A dip next to a dashed line has an explanation; a dip with none is worth watching.",
                why: "Charts show that something changed, not why. A date and a few words supply the why.",
              }}
            >
              <EventMarkers />
            </Panel>
          </Section>

          <Section n="02" title="Sleep">
            <Panel
              id="sleep"
              span={2}
              title="Sleep architecture"
              question="Deep, REM, light and awake, night by night."
              explore="sleep"
              guide={{
                what: "Hours in each sleep stage for the last four weeks of nights.",
                read: "Each column is a night, stages stacked from the bottom: deep, REM, light, awake. Hover a night for minutes.",
                why: "Deep sleep drives physical repair, REM supports memory and mood; total hours alone hide which one you're short on.",
                ctx: "Where WHOOP logged two main sleeps on one night, the longer is shown.",
              }}
            >
              <SleepStages />
            </Panel>
            <Panel
              id="sleep-need"
              title="Why you needed what you needed"
              question="Last night's need, by part, against what you got."
              guide={{
                what: "WHOOP's estimate of last night's need: baseline, plus debt, plus yesterday's strain, minus naps.",
                read: "Copper bars add up to the need; the cyan bar is what you slept.",
                why: "Eight hours is the wrong target after a hard day.",
              }}
            >
              <SleepNeed />
            </Panel>
            <Panel
              id="sleep-timing"
              title="When and how well"
              question="Consistency, timing and how long you've been sleeping."
              guide={{
                what: "How regular your sleep timing is, how far your sleep midpoint sits from WHOOP's ideal window, efficiency and wake-ups, plus nightly hours.",
                read: "Higher consistency and efficiency are better; a midpoint far from zero means you're sleeping off your best window.",
                why: "Regular timing does as much for recovery as total hours.",
              }}
            >
              <SleepTiming />
            </Panel>
          </Section>

          <Section n="03" title="The week">
            <Panel
              id="momentum"
              span={2}
              title="This week against last"
              question="Recovery, sleep and sessions, last 7 days versus the 7 before."
              guide={{
                what: "Average recovery, average sleep and sessions trained this week and last.",
                read: "Arrows show the change. One week down is noise; two in a row on the same tile is the signal.",
                why: "It's the quickest read on whether the week is going the right way.",
              }}
            >
              <WeekOverWeek />
            </Panel>
            <Panel
              id="aerobic-base"
              title="Aerobic base"
              question="Steady aerobic minutes against the 180 a week."
              guide={{
                what: "Minutes in WHOOP zones 2 and 3 over 7 days, about 70–85% of your max heart rate.",
                read: "The arc fills toward 180; the cyan bars are the zones that count.",
                why: "It speeds recovery between sets and between days. Zone 2 alone undercounts it.",
              }}
            >
              <AerobicBase />
            </Panel>
            <Panel
              id="spo2"
              title="Overnight oxygen"
              question="Nightly average SpO₂, four weeks."
              guide={{
                what: "Average blood oxygen during sleep each night.",
                read: "Points under the 95% line are low nights.",
                why: "Repeatedly low overnight oxygen can point to breathing problems during sleep, which quietly hurt recovery.",
              }}
            >
              <Spo2Burden />
            </Panel>
          </Section>

          <Section n="04" title="Stress and places">
            <Panel
              id="stress-day"
              span={2}
              title="Your day, minute by minute"
              question="Stress through one day, with where you were and when you trained."
              guide={{
                what: "WHOOP's stress score across the day in 10-minute averages, over shaded bands for the places you stayed and your workouts.",
                read: "Higher is more stressed, 0 to 3. Cyan bands are places, copper are workouts. Hover or drag across the line for a value.",
                why: "A number for the day hides when it went wrong. This shows whether the load was the commute, the desk or the workout.",
              }}
            >
              <DayStrip />
            </Panel>
            <Panel
              id="stress-rhythm"
              span={2}
              title="Your week's stress rhythm"
              question="Which weekday and hour blocks run hot."
              guide={{
                what: "Average stress for each weekday and hour over the last four weeks, with workouts left out.",
                read: "Darker blocks are higher. A block needs 20 readings to show.",
                why: "Recurring hot blocks are the ones worth changing; one-offs are not.",
              }}
            >
              <StressRhythm />
            </Panel>
          </Section>

          <Section n="05" title="Places">
            <Panel
              id="places"
              span={2}
              title="Where you spend your time"
              question="Places found from your phone, and what each one does to stress and the next morning."
              guide={{
                what: "Spots where you stayed 10 minutes or more, grouped into places. Nothing is set up by hand; tap a place to name it.",
                read: "Stress is the average gap against your own normal for the same hours elsewhere; plus means higher there. HRV is the next morning after 2+ hours there versus days you didn't go.",
                why: "Some places cost you more than a hard workout does, and you rarely see it from inside the day.",
                ctx: "Ranges that cross zero mean no clear difference yet.",
              }}
            >
              <Places />
            </Panel>
          </Section>

          <Section n="06" title="Patterns">
            <Panel
              id="patterns"
              span={2}
              title="Your best and worst days"
              question="Average recovery by day of the week, all time."
              guide={{
                what: "Average morning recovery for each day of the week across your whole WHOOP history.",
                read: "Taller bars are better mornings.",
                why: "It shows which days your week costs you, usually the ones after court days or late nights.",
              }}
            >
              <DayOfWeek />
            </Panel>
            <Panel
              id="recovery-trend"
              span={2}
              title="Green, yellow, red"
              question="How your mornings have split, all time."
              guide={{
                what: "Every scored morning, bucketed green (67+), yellow (34–66) and red (under 34).",
                read: "The bar shows the share of each; the rows give counts.",
                why: "A rising red share over a season is a sign to back off before a single bad week tells you.",
              }}
            >
              <RecoveryMix />
            </Panel>
          </Section>
        </div>
      </GuideProvider>
    </SurfaceShell>
  );
}
