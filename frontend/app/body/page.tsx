"use client";

import "../today.css";
import "../body.css";
import { ClinicalOverview } from "@/components/clinical-overview";
import { SurfaceShell } from "@/components/surface-shell";
import { EnergyOut, Fold, LogReading, SlowSignals, TapeProgress, TheRead, WeightRecord } from "@/components/body-brief";
import { Block } from "@/components/today-brief";

/**
 * BODY: is my body changing the way I want, and can I even tell?
 *
 * A ledger of change, read top to bottom: whether the composition can be read
 * at all and what it would take, the energy that kept reporting, the weight
 * record with its silence drawn honestly beside the form that ends it, six
 * months of the slow signals, then the clinical record. Food
 * intake sits in the ledger until a logger feeds it.
 */
export default function BodyPage() {
  return (
    <SurfaceShell>
      <div className="td-page">
        <TheRead />
        <Block id="energy" n="02" title="Energy out" sub="What the strap burned per day across the last thirteen months, with court time split out. When the scale is quiet this is the half of the energy balance that still reports.">
          <EnergyOut />
        </Block>
        <Block id="composition" n="03" title="Weight and waist" sub="Two years of weigh-ins, with the stretch since the last one marked as missing rather than drawn flat. Log today's numbers beside it.">
          <div className="bo-pair">
            <WeightRecord />
            <LogReading />
          </div>
        </Block>
        <Block id="tape" n="04" title="Tape progress" sub="Arms, waist, hips, legs and chest, every tape reading on one time axis. The tape sees what the scale can't: where the change is landing.">
          <TapeProgress />
        </Block>
        <Block id="slow-signals" n="05" title="Six months of the slow signals" sub="Resting heart rate, everyday movement, aerobic fitness and the airway overnight on one tape. A hatched stretch is a source that stopped reporting. Hover or drag across a day to read it.">
          <SlowSignals />
        </Block>
        <Block n="06" title="The record" sub="The clinical record behind it all.">
          <Fold id="clinical" label="Clinical record" title="Conditions, labs, and what's overdue for a re-draw" sub="The full record runs long, so it opens on request.">
            <ClinicalOverview />
          </Fold>
        </Block>
      </div>
    </SurfaceShell>
  );
}
