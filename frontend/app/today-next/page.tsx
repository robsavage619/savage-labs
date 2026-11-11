"use client";

import "../today.css";
import { CheckinCard } from "@/components/checkin-card";
import { MiddaySessionCard } from "@/components/midday-session-card";
import { SurfaceShell } from "@/components/surface-shell";
import { Block, BodyCheck, SessionSheet, Tape, TheCall, WriteUp } from "@/components/today-brief";

/**
 * TODAY: should I push, what do I do, and why.
 *
 * A morning brief, read top to bottom once: the call with the evidence beside
 * it, four weeks of mornings on one tape, the session as a working sheet, then
 * how you feel and whether the load can take it. The written report sits last.
 */
export default function TodayPage() {
  return (
    <SurfaceShell>
      <div className="td-page">
        <TheCall />
        <Block n="02" title="Four weeks of mornings" sub="Each night's HRV against your normal band, resting HR, WHOOP recovery, sleep, and the training that came before it. Hover a day to read it across.">
          <Tape />
        </Block>
        <Block id="session" n="03" title="The session" sub="Every lift with where today's load sits on its own history. Click a lift for its full progression.">
          <SessionSheet />
        </Block>
        <Block n="04" title="How you feel, and what the load says" sub="The check-in is the one input the wearables can't see. The load ratios are what the gates lock on.">
          <div className="td-lower">
            <div className="td-lower-l">
              <CheckinCard />
              <MiddaySessionCard />
            </div>
            <BodyCheck />
          </div>
        </Block>
        <Block n="05" title="The write-up" sub="The written read of the morning, when one has been generated.">
          <WriteUp />
        </Block>
      </div>
    </SurfaceShell>
  );
}
