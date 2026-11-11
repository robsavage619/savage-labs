"use client";

import "../today.css";
import "../body.css";
import { ClinicalOverview } from "@/components/clinical-overview";
import { ProgressPhotoPanel } from "@/components/progress-photo-panel";
import { SurfaceShell } from "@/components/surface-shell";
import { EnergyOut, Fold, LogReading, Sheet, SlowSignals, TheRead, WeightRecord } from "@/components/body-brief";
import { Block } from "@/components/today-brief";

/**
 * BODY: is my body changing the way I want, and can I even tell?
 *
 * A ledger of change, read top to bottom: whether the composition can be read
 * at all and what it would take, the energy that kept reporting, the weight
 * record with its silence drawn honestly beside the form that ends it, six
 * months of the slow signals, then photos and the clinical record. Food
 * intake sits in the ledger until a logger feeds it.
 */
export default function BodyNextPage() {
  return (
    <SurfaceShell>
      <div className="td-page">
        <TheRead />
        <Block n="02" title="Energy out" sub="What the strap burned per day across the last thirteen months, with court time split out. When the scale is quiet this is the half of the energy balance that still reports.">
          <EnergyOut />
        </Block>
        <Block id="weight" n="03" title="Weight and waist" sub="Two years of weigh-ins, with the stretch since the last one marked as missing rather than drawn flat. Log today's numbers beside it.">
          <div className="bo-pair">
            <WeightRecord />
            <LogReading />
          </div>
        </Block>
        <Block n="04" title="Six months of the slow signals" sub="Resting heart rate, everyday movement, aerobic fitness and the airway overnight on one tape. A hatched stretch is a source that stopped reporting. Hover a day to read it across.">
          <SlowSignals />
        </Block>
        <Block n="05" title="Photos and the record" sub="The physique check against your own last session, then the clinical record behind it all.">
          <Sheet id="physique" label="Progress photos" title="Same light, same spot, morning, fasted.">
            <ProgressPhotoPanel />
          </Sheet>
          <Fold id="clinical" label="Clinical record" title="Conditions, labs, and what's overdue for a re-draw" sub="The full record runs long, so it opens on request.">
            <ClinicalOverview />
          </Fold>
        </Block>
      </div>
    </SurfaceShell>
  );
}
