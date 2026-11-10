"use client";

import { useEffect, useRef, useSyncExternalStore } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ClinicalResearchPanel } from "@/components/clinical-research-panel";
import { EngineReportCard } from "@/components/engine-report-card";
import { EngineStatusPanel } from "@/components/engine-status-panel";
import { GuideProvider, Panel, Section } from "@/components/kit";
import { BeliefLenses, Coverage, ForecastDesk, Masthead, Misses, Pipeline, Threads } from "@/components/lab-floor";
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

// Sections that live on the Trials & instruments tab: a deep link to any of
// them (from the command palette) opens that tab.
const INSTRUMENT_IDS = new Set(["instruments", "trial-progress", "effects", "priors", "engine-bullets", "hrv-drivers", "trials", "suggested", "findings", "signals", "autonomic", "engine", "subject"]);

const subscribeHash = (cb: () => void) => {
  window.addEventListener("hashchange", cb);
  return () => window.removeEventListener("hashchange", cb);
};
const readHash = () => window.location.hash.slice(1);

/**
 * LAB: the research team's workspace.
 *
 * The research floor leads: the team's forecast of your next morning, what
 * it believes as probability curves, the questions moving through blind
 * review, the agents' own exchanges, where the forecast is wrong, and what
 * data the team can see. The n-of-1 trials, the standing research program and
 * the engine detail sit on the Trials & instruments tab.
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

  const hash = useSyncExternalStore(subscribeHash, readHash, () => "");
  const tab = INSTRUMENT_IDS.has(hash) ? "instruments" : "floor";

  return (
    <SurfaceShell>
      <GuideProvider>
        <div className="lf-page">
          <nav className="lf-tabs" aria-label="Lab views">
            <a href="#floor" className={tab === "floor" ? "on" : ""} aria-current={tab === "floor" ? "page" : undefined}>
              Research floor
            </a>
            <a href="#instruments" className={tab === "instruments" ? "on" : ""} aria-current={tab === "instruments" ? "page" : undefined}>
              Trials &amp; instruments
            </a>
          </nav>
          {tab === "floor" ? (
            <>
              <Masthead />
              <Block id="forecast" n="01" kicker="Forecast desk" title="Can the team predict you?">
                <ForecastDesk />
              </Block>
              <Block id="beliefs" n="02" kicker="Belief ledger" title="What the team believes about you">
                <BeliefLenses />
              </Block>
              <Block id="questions" n="03" kicker="Pipeline" title="Questions in flight">
                <Pipeline />
              </Block>
              <Block id="notebook" n="04" kicker="Notebook" title="The team's conversation" lede="Proposals, blind reviews and results, as the agents wrote them.">
                <Threads />
              </Block>
              <Block id="misses" n="05" kicker="Misses" title="Where the lab is still wrong" lede="The analyst's agenda: patterns in the forecast's errors that no belief explains yet.">
                <Misses />
              </Block>
              <Block id="coverage" n="06" kicker="Data" title="What the team can see">
                <Coverage />
              </Block>
            </>
          ) : (
            <div className="k-page">
            <Section n="01" title="The trials">
              <Panel
                id="trial-progress"
                span={4}
                title="How close is each trial to a real answer?"
                question="Days in each condition against the days needed to detect the effect it was set up to find."
                guide={{
                  what: "For each running trial, the qualifying days in conditions A and B against a power estimate: how many days it takes to see the hypothesised effect 80% of the time.",
                  read: "Cyan bars have enough days; copper still need more. The estimate uses the outcome's own day-to-day spread and how much one day resembles the next. Observational trials classify days after the fact; randomized ones assign them up front, which is stronger evidence.",
                  why: "A trial scored before it has enough days can only miss. This says which trials can answer, when, and the smallest effect each can see today.",
                  ctx: "Next-morning HRV is noisy, so small HRV effects take many months of days. That's the true cost of the question, not a fault in the trial.",
                }}
              >
                <TrialProgress />
              </Panel>
              <Panel
                id="effects"
                span={4}
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
          )}
        </div>
      </GuideProvider>
    </SurfaceShell>
  );
}

function Block({ id, n, kicker, title, lede, children }: { id: string; n: string; kicker: string; title: string; lede?: string; children: React.ReactNode }) {
  return (
    <section id={id} className="lf-block scroll-mt-24">
      <header className="lf-bhead">
        <span className="lf-n">{n}</span>
        <div>
          <span className="lf-kicker">{kicker}</span>
          <h2>{title}</h2>
          {lede && <p>{lede}</p>}
        </div>
      </header>
      {children}
    </section>
  );
}
