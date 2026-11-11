"use client";

import "../training.css";
import { SurfaceShell } from "@/components/surface-shell";
import { Block, CourtCost, MuscleVolume, SessionBrief, Strength } from "@/components/training-brief";

/**
 * TRAINING: what to lift today, and is each muscle getting grown.
 *
 * The session and the rotation lead, then muscle volume against target with
 * the emphasis muscles first, what court weeks cost the glutes, and each
 * lift's working e1RM. Read top to bottom once.
 */
export default function TrainingPage() {
  return (
    <SurfaceShell>
      <div className="tr-page">
        <SessionBrief />
        <Block id="volume" n="02" title="Muscle first: sets this week against target" sub="The engine's weekly target per muscle, counted its way: a compound credits every muscle it trains, set for set. Biceps and glutes are the emphasis.">
          <MuscleVolume />
        </Block>
        <Block id="court" n="03" title="What the court costs the glutes" sub="Glute sets each week beside the days you played. Twenty-five complete weeks.">
          <CourtCost />
        </Block>
        <Block id="lifts" n="04" title="Strength: is each lift going up?" sub="Every loaded lift of the last 90 days, emphasis muscles first, stalled and sliding at the top. Pick one to read its last six months.">
          <Strength />
        </Block>
      </div>
    </SurfaceShell>
  );
}
