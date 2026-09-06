"use client";

import type { ReactNode } from "react";
import { SurfaceShell } from "@/components/surface-shell";

import { AirwayPanel } from "@/components/airway-panel";
import { BodyPane } from "@/components/body-panel";
import { CardHelp } from "@/components/card-help";
import { ClinicalOverview } from "@/components/clinical-overview";
import { ErrorBoundary } from "@/components/error-boundary";
import { FuelingPanel } from "@/components/fueling-panel";
import { ProgressPhotoPanel } from "@/components/progress-photo-panel";
import type { Span } from "@/lib/sections";

/**
 * A board card. The anchor id comes from `sectionsFor("body")` in
 * lib/sections.ts — the nav and the palette resolve against that same list, so
 * an id that isn't in the manifest is a dead scroll target.
 *
 * Nothing here collapses. Panels supply their own card chrome where they have
 * it (FuelingPanel does), so this wrapper contributes only the anchor, the
 * span, the label rule, and the one-line explanation that sits between them.
 *
 * `help` is required rather than optional: an unexplained card is the state
 * this wrapper exists to prevent, and a missing prop is a type error rather
 * than something you notice on the page a month later.
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

export default function BodyPage() {
  return (
    <SurfaceShell>
      <div className="board">
        {/* An even 2+2. Fuelling cannot go narrower — its macro row is a
            five-column grid, and at span-1 those tracks fall to ~70px — and
            the photo strip is flex-wrap, so it reflows to whatever width it
            is handed and stays close to Fuelling in height at 800px. */}
        <div className="board-rule">Intake &amp; physique</div>

        <BoardCard
          id="fueling"
          label="Fuelling"
          span={1}
          help="Whether today's eating supports the build: protein, calorie balance, and where your weight sits."
          helpDetail={
            <>
              <p>
                <strong>Protein</strong> at 1.6–2.2 g/kg is the range that supports muscle
                growth; under 1.2 g/kg blunts recovery from training. The number to the
                right of the gram total is your grams per kilo of body weight — that is the
                one that matters, not the raw total.
              </p>
              <p>
                <strong>Energy balance</strong> is intake minus estimated burn. Staying
                within ±250 kcal of that line holds lean mass while fat comes off; the
                14-day bars show red for a surplus day and green for a deficit, so what you
                want is a green-leaning week rather than any single perfect day.
              </p>
              <p>
                Body weight, body fat and lean mass come from a smart scale through Apple
                Health; food comes from whatever logger you have connected to it. A dash
                means that source has not reported, which is not the same as a zero.
              </p>
            </>
          }
        >
          <FuelingPanel />
        </BoardCard>

        <BoardCard
          id="physique"
          label="Progress photos"
          span={3}
          help="Visual proof of whether your shape is actually changing, measured rather than eyeballed."
          helpDetail={
            <>
              <p>
                Shoot the same way every time — morning, fasted, at least 24 hours after
                training, same spot and same light. Photos taken pumped or in different
                lighting are the main reason a trend looks like it reversed.
              </p>
              <p>
                The <strong>waist ratio</strong> line is computed from silhouette geometry
                normalised to your shoulder-to-hip span, not from the raw pixel width, so it
                survives a change in camera distance. It is a rolling median, so one bad
                frame cannot swing it, and any change smaller than the 2% measurement error
                floor is reported as no change rather than as progress.
              </p>
              <p>
                The written critique is not automatic: copy the prompt, run it in Claude
                Code with your latest front and side shots attached, and it posts back here.
                Photos stay on this machine.
              </p>
            </>
          }
        >
          <ProgressPhotoPanel />
        </BoardCard>

        <div className="board-rule">The body itself</div>

        {/* Full width: a two-up chart pane. Halving it stacks the charts and
            doubles the height for no gain. */}
        <BoardCard
          id="composition"
          label="Body composition"
          span={4}
          help="The slow movers — body weight, aerobic fitness, daily steps and resting heart rate."
          helpDetail={
            <>
              <p>
                On the weight chart, read the <strong>line, not the bars</strong>. Day-to-day
                bars swing a couple of pounds on water and food timing alone; the line is the
                rolling average and is the only part that tells you which direction you are
                going.
              </p>
              <p>
                <strong>VO₂ max</strong> is graded against your age band. When it is not
                coming from the watch it is estimated from resting heart rate, so treat it as
                a trend line rather than a lab measurement. <strong>Steps</strong> are shown
                against a 10,000/day reference — this is your non-training activity, which
                moves daily burn more than the workout itself does.
              </p>
              <p>
                Resting heart rate is plotted from two devices that disagree in absolute
                terms, so compare each line against its own history, never against the other.
                Propranolol suppresses the number outright on days you take it, which is a
                drug effect and not improved fitness.
              </p>
            </>
          }
        >
          <BodyPane />
        </BoardCard>

        <BoardCard
          id="airway"
          label="Airway overnight"
          span={4}
          help="Whether your breathing is holding up overnight — oxygen saturation and respiratory rate against the thresholds that would prompt a doctor's visit."
          helpDetail={
            <>
              <p>
                This card exists because you have <strong>diagnosed obstructive sleep apnea and
                are off CPAP</strong>. Both numbers were already being recorded every night and
                neither was plotted anywhere, so a slow drift had nowhere to show up.
              </p>
              <p>
                On the top chart, the shaded bands are what matters more than any single dot.
                Above 95% is unremarkable; the amber band is 94–95%; the red band is under 94%,
                which is the screening floor where a consistently low reading is worth raising
                with a physician. The dashed line near the bottom is 92%, where this system
                actually restricts training. The solid line is a seven-night mean — one bad
                night is a bad night, a line that sits in the amber band is a pattern.
              </p>
              <p>
                The lower chart is respiratory rate against <em>your own</em> 28-night baseline
                rather than a textbook number. Amber is +0.5 bpm, red is +1.0 — the same
                thresholds the daily gate already uses to flag possible illness. It is the
                companion signal: infection and airway load both push it up, so a saturation dip
                with a flat respiratory rate reads differently from one where both move together.
              </p>
              <p>
                What this cannot tell you is how <em>often</em> you stop breathing. A nightly
                average is not an apnea count, and only a sleep study produces one.
              </p>
            </>
          }
        >
          <AirwayPanel />
        </BoardCard>

        {/* 649 lines of risk strip, meds, labs table and panel results — the
            widest surface in the app, and until now reachable only through a tab
            bar inside a collapsed accordion. */}
        <BoardCard
          id="clinical"
          label="Clinical record"
          span={4}
          help="Your real medical record: conditions, medications, lab results, and what is overdue for a re-draw."
          helpDetail={
            <>
              <p>
                The tiles at the top are your latest cardiometabolic values with the zone each
                one falls in. In the labs table, an <strong>H or L flag</strong> means outside
                the lab&apos;s reference range — that is a question for your doctor, not an
                input to today&apos;s training. The bar beside each value is the more useful
                read: it shows where the result sits inside its own reference interval,
                so a value scraping the edge looks different from one in the middle.
              </p>
              <p>
                <strong>Care gaps</strong> lists panels that are past their re-draw interval,
                with how many months overdue. That is the actionable part of this card — it is
                the only thing here you can fix this week.
              </p>
              <p>
                Values are entered by hand from your actual results, so an absent marker means
                it has not been recorded, never that it came back normal.
              </p>
            </>
          }
        >
          <ClinicalOverview />
        </BoardCard>
      </div>
    </SurfaceShell>
  );
}
