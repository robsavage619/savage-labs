"use client";

import { useState, type ReactNode } from "react";
import { CheckinCard } from "@/components/checkin-card";
import { DailyReport } from "@/components/daily-report";
import { GuideProvider, PageHead, Panel, Section } from "@/components/kit";
import { MiddaySessionCard } from "@/components/midday-session-card";
import { NextWorkoutPane } from "@/components/next-workout";
import { SurfaceShell } from "@/components/surface-shell";
import { TodayHero } from "@/components/today-hero";
import { LoadSplit, MuscleFreshness, NoiseFloorCard, ReadinessBreakdown } from "@/components/today-signals";

/**
 * TODAY: should I push, and what do I do?
 *
 * Rebuilt to the approved overhaul mockup: the verdict and the morning read own
 * the first screen, the session follows (clamped, so it can't push everything
 * else off the page), and the written report sits last. Anchor ids match
 * `lib/sections.ts`.
 */

/** Shows the first screen of the session, then a toggle for the rest. */
function Clamp({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <div className={`k-clamp${open ? " open" : ""}`} style={open ? undefined : { maxHeight: 760 }}>
      {children}
      <button className="k-clamp-btn" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
        {open ? "Show less" : "Show the whole session"}
      </button>
    </div>
  );
}

export default function TodayPage() {
  const today = new Date().toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" });
  return (
    <SurfaceShell>
      <GuideProvider>
        <div className="k-page">
          <PageHead
            eyebrow={`Today · ${today}`}
            question="Should I push today, and what do I do?"
            lede="The call and why, what moved overnight against your own normal, then the session. Every chart has a reading guide; hide them with the button at the bottom right once you know them."
          />

          <Section n="01" title="The call">
            <Panel
              id="call"
              span={4}
              title="Today's call"
              question="The engine's verdict, what it locks, and the session it built from it."
              explore="hrv"
              guide={{
                what: "The verdict reconciles your readiness score with the safety gates, so a good score can never say \"push\" on a day the gates cap you.",
                read: "The big word is the call; the line under it is why. Red chips are movement patterns locked today, amber ones are single muscles or an intensity ceiling. The chart is your HRV for the last 28 days against your own normal band.",
                why: "It's the one decision the morning has to make. Everything below explains it.",
                ctx: "If a chip is locked, the planner will refuse any exercise that trains it, so don't program around it.",
              }}
            >
              <TodayHero />
            </Panel>
          </Section>

          <Section n="02" title="The morning read">
            <Panel
              id="overnight"
              span={2}
              title="Did anything actually move overnight?"
              question="Each signal against its own normal wobble. A dot inside the band is noise, however it looks."
              explore="hrv"
              tag="new"
              guide={{
                what: "How far each overnight reading moved from your own average over the last 28 days.",
                read: "The shaded band in the middle is your normal night-to-night range. A grey dot inside it means nothing really changed. A bright dot outside it, tagged moved, is a real change. Click a row to open its history.",
                why: "Most bad-looking mornings are just noise. This stops you reacting to a dip that's normal for you, and makes the rare real change stand out.",
                ctx: "The band is half the spread of your own last 28 days, the smallest change worth caring about. Skin temperature is in °F.",
              }}
            >
              <NoiseFloorCard />
            </Panel>
            <Panel
              id="readiness"
              title="What the score is made of"
              question="Readiness split into its four inputs."
              explore="recovery"
              guide={{
                what: "The 0–100 readiness score and the four scores it's built from.",
                read: "The ring is today's score. Each bar is one input on its own 0–100 scale; the small percentage is how much it counts. The amber bar is the weakest.",
                why: "A middling score can hide one strong input and one weak one. The short bar is what's dragging the day.",
                ctx: "HRV counts most at 40%. Skip the check-in and its 10% is simply missing.",
              }}
            >
              <ReadinessBreakdown />
            </Panel>
            <Panel
              id="load-split"
              title="Building or spiking?"
              question="Last 7 days of load against the 21 before, split by kind."
              explore="load"
              guide={{
                what: "The last 7 days of training load divided by the 21 days before, for all training, lifting only and conditioning only.",
                read: "Each dot sits on a scale. Green is steady building (0.8–1.3); red, from 1.5, is where the engine starts locking muscles.",
                why: "Sudden jumps in load, more than load itself, tend to come before injuries and bad weeks. The split shows whether lifting or pickleball did the jumping.",
              }}
            >
              <LoadSplit />
            </Panel>
          </Section>

          <Section n="03" title="The session">
            <Panel
              id="session"
              span={4}
              title="Today's session"
              question="Sets, reps, load and target effort, ready to push to Hevy."
              bare
              guide={{
                what: "Each lift with its sets, reps, target weight and target effort (RPE, where 10 is a set you couldn't add a rep to).",
                read: "Loads are anchored to what you've logged recently. Dumbbell weights are per hand. A swapped-in lift may have no weight yet: work up to the target effort instead.",
                why: "Hevy pushes the session as a routine to log against, and that log is what tomorrow's plan is built from. A session trained but not logged is invisible to the engine.",
              }}
            >
              <Clamp>
                <NextWorkoutPane />
              </Clamp>
            </Panel>
          </Section>

          <Section n="04" title="Around the session">
            <Panel
              id="checkin"
              span={2}
              title="Check-in"
              question="Thirty seconds of how you feel. It moves tomorrow's plan."
              bare
              guide={{
                what: "Soreness, sleep quality, energy, stress and motivation on a 1–10 scale, plus where you're sore.",
                read: "Higher stress or soreness pulls tomorrow's load down. Everything saves as you touch it.",
                why: "Wearables can't see how you feel. This is the only way it reaches the engine, and readiness is missing 10% without it.",
              }}
            >
              <CheckinCard />
            </Panel>
            <div className="k-span-2 k-stack">
              <Panel
                id="fresh"
                title="What's fresh"
                question="Days since each muscle last got a real dose."
                explore="sets"
                guide={{
                  what: "Days since each muscle last got 4 or more hard sets.",
                  read: "Bigger numbers on greener tiles mean more rested.",
                  why: "A muscle generally needs 2–3 days between hard sessions to grow.",
                }}
              >
                <MuscleFreshness />
              </Panel>
              <Panel id="midday" title="Lunch session" question="What to do at midday, built from what the morning left in the tank." bare>
                <MiddaySessionCard />
              </Panel>
            </div>
          </Section>

          <Section n="05" title="The write-up">
            <Panel id="report" span={4} title="Morning report" question="The written read of your morning, when you've generated one." bare>
              <DailyReport />
            </Panel>
          </Section>
        </div>
      </GuideProvider>
    </SurfaceShell>
  );
}
