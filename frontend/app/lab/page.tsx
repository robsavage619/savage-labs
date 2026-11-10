"use client";

import { useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ClinicalResearchPanel } from "@/components/clinical-research-panel";
import { EngineReportCard } from "@/components/engine-report-card";
import { EngineStatusPanel } from "@/components/engine-status-panel";
import { GuideProvider, PageHead, Panel, Section } from "@/components/kit";
import { EffectForest, HrvDrivers, PriorsShelf, ScorecardBullets, TrialProgress } from "@/components/lab-charts";
import { LabExperiments } from "@/components/lab-experiments";
import { LabPanel } from "@/components/lab-panel";
import { BehaviorImpactPanel, StressPanel } from "@/components/stress-panel";
import { SubjectDossier } from "@/components/subject-dossier";
import { SuggestedExperiments } from "@/components/suggested-experiments";
import { SurfaceShell } from "@/components/surface-shell";
import { api } from "@/lib/api";

const LAB_RUN_THROTTLE_KEY = "lab_last_run_ms";
const LAB_RUN_THROTTLE_MS = 6 * 60 * 60 * 1000; // 6 hours

/**
 * LAB: what have I proven about myself?
 *
 * Rebuilt on the kit. The trials and what they found lead, drawn as charts;
 * then what's proven and how good the engine is; then the habits linked to
 * HRV. The panels with working controls (log a day, score, suggest a study)
 * and the research and engine detail follow at full width. The old engine
 * scorecard table and HRV correlation cards are retired: the charts above
 * replace them.
 */
export default function LabPage() {
  const qc = useQueryClient();
  const ranRef = useRef(false);

  // Refresh the standing research program at most every 6 hours, in the
  // background; the page renders the last persisted findings meanwhile.
  useEffect(() => {
    if (ranRef.current) return;
    ranRef.current = true;
    try {
      const last = parseInt(localStorage.getItem(LAB_RUN_THROTTLE_KEY) ?? "0", 10);
      if (Date.now() - last < LAB_RUN_THROTTLE_MS) return;
    } catch {
      // localStorage unavailable: proceed
    }
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
        // 401 when the key is unset, network errors: the page still renders
      });
  }, [qc]);

  return (
    <SurfaceShell>
      <GuideProvider>
        <div className="k-page">
          <PageHead
            eyebrow="Lab"
            question="What have I proven about myself?"
            lede="Your n-of-1 trials and what they found, what's been proven and is now in use, and how far to trust the engine that plans your days."
          />

          <Section n="01" title="The trials">
            <Panel
              id="trial-progress"
              span={2}
              title="How close is each trial to an answer?"
              question="Days logged in each condition against the minimum set before it started."
              guide={{
                what: "For each running experiment, the qualifying days in condition A and condition B, against its pre-registered minimum.",
                read: "Cyan bars have enough days; copper ones still need more. Observational trials classify days after the fact; randomized ones assign them up front, which is stronger evidence.",
                why: "Small samples produce false findings. This shows which trials are close to an answer and which need more days of one condition.",
              }}
            >
              <TrialProgress />
            </Panel>
            <Panel
              id="effects"
              span={2}
              title="What the trials found so far"
              question="Each scored effect with its 95% range."
              guide={{
                what: "The difference between conditions B and A on each trial's outcome, with its 95% confidence interval.",
                read: "The diamond is the best estimate; the bar is the 95% range. Grey crosses zero. Copper is a clear effect in the opposite direction to the hypothesis.",
                why: "An average difference on its own overstates what you know. The range shows how sure to be.",
                ctx: "Observational findings against the hypothesis usually mean the arrow points the other way (you play more when you already feel good), not that you should do more of the thing.",
              }}
            >
              <EffectForest />
            </Panel>
          </Section>

          <Section n="02" title="What's proven">
            <Panel
              id="priors"
              span={2}
              title="What's been proven and is in use"
              question="Confirmed findings the engine acts on, and the trial closest to joining them."
              guide={{
                what: "Priors: effects a randomized trial confirmed, which the planner now applies to your prescriptions.",
                read: "An empty shelf means nothing has confirmed yet, so the engine still runs on population rules here.",
                why: "This is where the app stops treating you as average.",
              }}
            >
              <PriorsShelf />
            </Panel>
            <Panel
              id="engine-bullets"
              span={2}
              title="Is the engine any good?"
              question="How the planner has performed against what you actually did."
              guide={{
                what: "Whether you did what it prescribed, whether its loads were right, and whether its calls beat chance.",
                read: "Longer bars are better on the percentage measures. Green is on track, amber needs review.",
                why: "Trust the plan only as much as it has earned.",
              }}
            >
              <ScorecardBullets />
            </Panel>
          </Section>

          <Section n="03" title="Habits">
            <Panel
              id="hrv-drivers"
              span={4}
              title="What moves your HRV"
              question="Average HRV on days you answered yes to a WHOOP journal question, minus days you answered no."
              explore="hrv"
              guide={{
                what: "For each journal question, average HRV on yes days minus no days.",
                read: "Bars right of centre mean higher HRV on yes days, left mean lower. The thin line is the 95% range; grey means it crosses zero. A question needs 10 yes and 10 no days before it is drawn.",
                why: "It points at habits worth testing as a trial.",
                ctx: "These are links, not causes, and the journal stopped on 8 May.",
              }}
            >
              <HrvDrivers />
            </Panel>
          </Section>

          <Section n="04" title="Run the trials">
            <Panel id="trials" span={4} title="Active trials" question="Log today's condition, score a trial, or score them all." bare>
              <LabExperiments />
            </Panel>
            <Panel id="suggested" span={4} title="Suggested studies" question="Findings worth turning into a real trial." bare>
              <SuggestedExperiments />
            </Panel>
          </Section>

          <Section n="05" title="Research and the engine">
            <Panel id="findings" span={4} title="Standing research program" question="The pre-registered questions the lab re-tests on your data." bare>
              <LabPanel />
            </Panel>
            <Panel id="signals" span={4} title="Clinical research signals" question="Published markers computed on your own numbers." bare>
              <ClinicalResearchPanel />
            </Panel>
            <Panel id="autonomic" span={4} title="Autonomic load" question="Stress and what WHOOP links it to." bare>
              <StressPanel />
              <BehaviorImpactPanel />
            </Panel>
            <Panel id="engine" span={4} title="Engine self-assessment" question="What the engine has fitted to you and how accurate it has been." bare>
              <EngineStatusPanel />
              <EngineReportCard />
            </Panel>
            <Panel id="subject" span={4} title="Subject dossier" question="How long the system has watched and how much is tuned to you." bare>
              <SubjectDossier />
            </Panel>
          </Section>
        </div>
      </GuideProvider>
    </SurfaceShell>
  );
}
