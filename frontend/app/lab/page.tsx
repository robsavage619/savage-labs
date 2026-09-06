"use client";

import { useEffect, useRef, type ReactNode } from "react";
import { SurfaceShell } from "@/components/surface-shell";
import { useQueryClient } from "@tanstack/react-query";

import { CardHelp } from "@/components/card-help";
import { ClinicalResearchPanel } from "@/components/clinical-research-panel";
import { CorrelationCards } from "@/components/correlation-cards";
import { EngineStatusPanel } from "@/components/engine-status-panel";
import { ErrorBoundary } from "@/components/error-boundary";
import { LabExperiments } from "@/components/lab-experiments";
import { LabPanel } from "@/components/lab-panel";
import { BehaviorImpactPanel, StressPanel } from "@/components/stress-panel";
import { SubjectDossier } from "@/components/subject-dossier";
import { SuggestedExperiments } from "@/components/suggested-experiments";
import { api } from "@/lib/api";
import type { Span } from "@/lib/sections";

const LAB_RUN_THROTTLE_KEY = "lab_last_run_ms";
const LAB_RUN_THROTTLE_MS = 6 * 60 * 60 * 1000; // 6 hours

/**
 * A board card. The anchor id comes from `sectionsFor("lab")` in
 * lib/sections.ts. Nothing collapses — the panels that used to sit behind
 * seven accordion headers are laid out across the width instead.
 *
 * A card without an `id` is a companion to the one before it (suggested
 * studies beside the trials, behaviour impact beside the stress panel): the
 * manifest has one anchor for the pair, and ids must stay unique.
 *
 * `help` is required, not optional. This page is the densest statistics in the
 * app, and a card whose explanation was left off is exactly the card that needed
 * one — making it a type error is cheaper than noticing later.
 */
function BoardCard({
  id,
  label,
  span,
  help,
  helpDetail,
  children,
}: {
  id?: string;
  label: string;
  span: Span;
  /** One sentence, second person: what this card tells you and why you'd look. */
  help: string;
  /** Optional longer read: thresholds, how to act, caveats. */
  helpDetail?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section id={id} className={`span-${span} scroll-mt-24`}>
      <div className="flex items-center gap-3 px-1 pb-2">
        <span className="shc-section-title text-[10px] tracking-[0.18em] text-[var(--text-dim)]">
          {label}
        </span>
        <span className="flex-1 h-px bg-[var(--hairline)]" />
      </div>
      <div className="px-1">
        <CardHelp summary={help}>{helpDetail}</CardHelp>
      </div>
      <ErrorBoundary label={label}>{children}</ErrorBoundary>
    </section>
  );
}

export default function LabPage() {
  const qc = useQueryClient();
  const ranRef = useRef(false);

  useEffect(() => {
    if (ranRef.current) return;
    ranRef.current = true;

    try {
      const last = parseInt(localStorage.getItem(LAB_RUN_THROTTLE_KEY) ?? "0", 10);
      if (Date.now() - last < LAB_RUN_THROTTLE_MS) return;
    } catch {
      // localStorage unavailable — proceed
    }

    // Fire-and-forget: never block render
    api
      .labRun()
      .then(() => {
        try {
          localStorage.setItem(LAB_RUN_THROTTLE_KEY, String(Date.now()));
        } catch {
          // ok
        }
        qc.invalidateQueries({ queryKey: ["lab-findings"] });
        qc.invalidateQueries({ queryKey: ["experiments"] });
      })
      .catch(() => {
        // 401 when key unset, network errors — page still renders last persisted findings
      });
  }, [qc]);

  return (
    <SurfaceShell>
      <div className="board">
        {/* A three-column header strip. It is short and inherently wide, so a
            full-width row costs nothing and splitting it would crush the
            internal grid-cols-3 into ~130px tracks. */}
        <BoardCard
          id="subject"
          label="Subject dossier"
          span={4}
          help="How well the system actually knows you: how long it has watched, and how much is tuned to you."
          helpDetail={
            <>
              <p>
                The <strong>personalization bar</strong> is the share of the engine&apos;s
                settings that have been fitted from your own history rather than taken from
                published population averages. Each family beneath it reads either
                &quot;fitted&quot; or &quot;population&quot;. Population is a reasonable
                starting point and a poor finishing one — anything still on defaults is a
                textbook rule being applied to you, not a rule learned from you.
              </p>
              <p>
                <strong>Engine accuracy</strong> is the share of past calls that held up when
                replayed against what actually happened. Roughly: 70%+ means the daily
                prescription has earned trust, under 50% means treat it as a suggestion. The
                count beneath it is how many calls that percentage is based on — a high score
                over a handful of days means very little.
              </p>
              <p>
                Source chips at the bottom show which feeds are still streaming. A dark chip
                means that data stopped arriving, which quietly degrades everything above it.
              </p>
            </>
          }
        >
          <SubjectDossier />
        </BoardCard>

        {/* Four list panels of comparable density — no chart, no table wide
            enough to need three columns — so an even 2+2 on each row, with
            each companion card kept beside the anchored card it belongs to. */}
        <div className="board-rule">n-of-1 program</div>

        <BoardCard
          id="trials"
          label="Active trials"
          span={2}
          help="Experiments you are running on yourself, and how close each is to an answer worth acting on."
          helpDetail={
            <>
              <p>
                Each study is pre-registered: the hypothesis, the two conditions, and the
                smallest effect worth caring about are fixed before any data is looked at, so
                the result cannot be talked into existence afterwards. The two bars are how
                many days each arm has collected against the sample it needs.
              </p>
              <p>
                <strong>Check the design before you trust a verdict.</strong> A randomized
                study assigns your condition for the day up front, which is what licenses a
                causal reading. An observational one classifies days after the fact out of
                data you had already generated — it can only show that two things travelled
                together, and whatever else changed that week travelled with them. Most of the
                running set is observational, so a confirmed observational effect is a strong
                lead rather than a settled fact.
              </p>
              <p>
                <strong>Log today</strong> records adherence and reveals the day&apos;s
                assigned arm; <strong>Score</strong> pulls the outcome and reports an effect
                with a 95% confidence interval, withheld until the sample is large enough. A
                confirmed study writes a prior the workout planner then leans on — which is
                the reason design quality here is worth being fussy about.
              </p>
            </>
          }
        >
          <LabExperiments />
        </BoardCard>

        {/* Two short cards stacked into one column beside Active trials.
            Alone they were each a ~200px card facing a 945px and a 1,891px
            neighbour; the spans on the sections below are inert inside this
            wrapper, since `.board > .span-N` only matches direct children. */}
        <div className="span-2 flex flex-col gap-4">
        <BoardCard
          label="Suggested studies"
          span={2}
          help="Unanswered findings you could turn into a real trial — the shortlist worth testing next."
          helpDetail={
            <>
              <p>
                These are drawn from the standing research program: findings that are still
                unresolved <em>and</em> have an exposure you can actually control, which is
                what makes them testable rather than merely interesting.
              </p>
              <p>
                Registering one locks the hypothesis and the analysis before data is seen, and
                it then appears under Active trials. The citation on a card is the published
                methodology the design would follow.
              </p>
            </>
          }
        >
          <SuggestedExperiments />
        </BoardCard>

        <BoardCard
          id="engine"
          label="Engine self-assessment"
          span={2}
          help="How often the daily plan gets it right, and how much of it is still generic defaults."
          helpDetail={
            <>
              <p>
                <strong>Prescription accuracy</strong> replays past calls against what actually
                happened. Green from about 70% up, amber 50–70%, red below — and the
                &quot;backtested&quot; count is how much that number rests on. The sparkline is
                the more useful signal: a falling line means the engine is drifting away from
                you, usually because something changed in your training that it has not
                absorbed yet.
              </p>
              <p>
                The three tiles beneath say where each family of thresholds came from. A value
                marked <em>(default)</em> or <em>population</em> is a textbook number, not one
                learned from your data — so when a population-default deload trigger or load
                band locks a session, that is a generic rule firing rather than evidence about
                you specifically. Green means it was fitted from your own history.
              </p>
            </>
          }
        >
          <EngineStatusPanel />
        </BoardCard>
        </div>

        <BoardCard
          id="findings"
          label="Standing research program"
          span={4}
          help="The standing question bank: which hypotheses about you the data has answered, and how firmly."
          helpDetail={
            <>
              <p>
                Every card is a question registered in advance, with its test and threshold
                fixed before the data was looked at. Four verdicts:
                <strong> confirmed</strong> (the effect met the threshold in the predicted
                direction), <strong>refuted</strong> (it ran the other way),
                <strong> inconclusive</strong> (right direction, too small to act on), and
                <strong> insufficient n</strong> (not enough days yet — no verdict at all, not
                a negative one).
              </p>
              <p>
                A question only moves to <em>Answered</em> after three consecutive identical
                definitive verdicts, and is re-checked every 30 days after that; a disagreeing
                re-check sends it back under test. Confirmations are corrected for the fact
                that many hypotheses are being tested at once, but not for re-testing the same
                one as data accumulates — so read a confirmation as strong evidence, not proof.
              </p>
              <p>
                <strong>Run all</strong> rescores the whole bank against current data. The
                page runs it for you at most once every six hours.
              </p>
            </>
          }
        >
          <LabPanel />
        </BoardCard>


        {/* Ordered so each companion pair lands SIDE BY SIDE rather than
            stacked across a row break: the derived-signal panels take the
            first row, then autonomic load with the behaviour impact that
            annotates it. Both pairs are middling-height list panels, so an
            even 2+2 split is the right footprint for all four. */}
        <div className="board-rule">Physiological signals</div>

        <BoardCard
          id="signals"
          label="Clinical research signals"
          span={2}
          help="Four longitudinal signals computed from your data, each banded against its published threshold — or, where one exists, against your own noise floor. Lab-based indices like FIB-4 live on the Body panel."
          helpDetail={
            <>
              <p>
                Every tile shows your current value, what it means in plain terms, and the
                bands from the paper it comes from — the highlighted band is where you sit
                today. Hover a tile&apos;s name for the full citation.
              </p>
              <p>
                <strong>Sleep regularity</strong> scores how consistent your sleep and wake
                clock times are: 80+ is tight, under 60 irregular, and it moves recovery more
                than total hours does. <strong>ln-RMSSD trend</strong> is the direction of your
                heart-rate variability — rising means you are adapting to the load, falling
                means it is accumulating. <strong>Recovery deficit streak</strong> counts
                consecutive suppressed days; three or more is the point to back off rather
                than push through. <strong>Allostatic load</strong> tallies concurrent stress
                markers, with six or more high.
              </p>
              <p>
                <strong>Adjusted HRV</strong> factors propranolol and SSRI dampening back out,
                so it only shows a value on days such a drug was active — on those days it is
                the truer read of autonomic recovery. <strong>Zone-2 heart-rate drift</strong>
                measures how steadily your heart rate holds during easy cardio: 4% or less is
                a solid aerobic base, above 7% means the base is not there yet.
              </p>
            </>
          }
        >
          <ClinicalResearchPanel />
        </BoardCard>

        <BoardCard
          id="correlations"
          label="What moves your HRV"
          span={2}
          help="Which of your logged habits actually move next-morning recovery, ranked by how much."
          helpDetail={
            <>
              <p>
                Each bar is the average difference in next-morning heart-rate variability
                between days you did the thing and days you did not, taken from your nightly
                journal answers. Green helped, red hurt, and bar length is scaled to the
                largest effect on the card. Only differences of 1ms or more are shown; below
                that is noise.
              </p>
              <p>
                This is association, not proof — the days you drank late are also the days you
                slept badly. Treat a big bar as a candidate, then promote it into a registered
                trial if it is worth knowing for certain. It needs roughly 14 paired journal
                days before anything appears at all.
              </p>
            </>
          }
        >
          <CorrelationCards />
        </BoardCard>

        <BoardCard
          id="autonomic"
          label="Autonomic load"
          span={2}
          help="How much of each day your body spent under stress, plus today's hour-by-hour curve."
          helpDetail={
            <>
              <p>
                The bars are the share of each day spent in the high-stress band, and the
                dashed line is the level past which recovery starts getting docked. Read the
                <em> rate across the week</em>: a single day sits well inside the normal
                day-to-day spread and means nothing on its own, while four bars over the line
                is a week that will show up in tomorrow&apos;s readiness.
              </p>
              <p>
                The lower chart is the most recent day on a 0–3 gauge by hour. A sharp isolated
                spike is usually just the workout; a broad afternoon plateau is the part worth
                looking at, because that is load your training did not cause and your recovery
                still has to pay for.
              </p>
            </>
          }
        >
          <StressPanel />
        </BoardCard>

        <BoardCard
          label="WHOOP behaviour impact"
          span={2}
          help="Your tracker's own verdict on which habits help or hurt recovery, across your whole history."
          helpDetail={
            <>
              <p>
                Bars to the right in green helped recovery, bars to the left in red hurt it.
                This is computed by WHOOP over your full history rather than by this system,
                so it is a second opinion with a different model and a different sample.
              </p>
              <p>
                It is not filtered for sample size or for factors that travel together, so
                where it disagrees with the HRV panel beside it, believe neither on its own —
                that disagreement is the thing to settle with a registered trial.
              </p>
            </>
          }
        >
          <BehaviorImpactPanel />
        </BoardCard>
      </div>
    </SurfaceShell>
  );
}
