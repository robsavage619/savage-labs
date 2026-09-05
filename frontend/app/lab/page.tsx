"use client";

import { useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { SubjectDossier } from "@/components/subject-dossier";
import { LabExperiments } from "@/components/lab-experiments";
import { LabPanel } from "@/components/lab-panel";
import { EngineStatusPanel } from "@/components/engine-status-panel";
import { ClinicalResearchPanel } from "@/components/clinical-research-panel";
import { CorrelationCards } from "@/components/correlation-cards";
import { BehaviorImpactPanel, StressPanel } from "@/components/stress-panel";
import { TrendIntelligence } from "@/components/trend-intelligence";
import { AppShell } from "@/components/app-shell";
import { CollapsibleSection } from "@/components/collapsible-section";
import { ErrorBoundary } from "@/components/error-boundary";
import { SuggestedExperiments } from "@/components/suggested-experiments";
import { api } from "@/lib/api";

const LAB_SECTIONS = [
  { id: "dossier", label: "Subject" },
  { id: "studies", label: "Studies" },
  { id: "findings", label: "Findings" },
  { id: "engine", label: "Engine" },
  { id: "clinical", label: "Clinical" },
  { id: "stress", label: "Autonomic" },
  { id: "correlations", label: "HRV" },
  { id: "trends", label: "Trends" },
] as const;

const LAB_RUN_THROTTLE_KEY = "lab_last_run_ms";
const LAB_RUN_THROTTLE_MS = 6 * 60 * 60 * 1000; // 6 hours

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
    <AppShell sections={LAB_SECTIONS}>
      <div className="space-y-4">
        {/* ── SUBJECT DOSSIER ── */}
        <section id="dossier" className="scroll-mt-20">
          <ErrorBoundary label="Subject dossier">
            <SubjectDossier />
          </ErrorBoundary>
        </section>

        {/* ── STUDIES (n-of-1 + suggestions) ── */}
        <CollapsibleSection id="studies" title="Active studies · n-of-1 trials" defaultOpen>
          <div className="space-y-4">
            <ErrorBoundary label="Self-experiments">
              <LabExperiments />
            </ErrorBoundary>
            <ErrorBoundary label="Suggested studies">
              <SuggestedExperiments />
            </ErrorBoundary>
          </div>
        </CollapsibleSection>

        {/* ── STANDING RESEARCH PROGRAM ── */}
        <CollapsibleSection id="findings" title="Standing research program" defaultOpen>
          <ErrorBoundary label="Research lab">
            <LabPanel />
          </ErrorBoundary>
        </CollapsibleSection>

        {/* ── ENGINE SELF-ASSESSMENT ── */}
        <CollapsibleSection id="engine" title="Engine self-assessment" defaultOpen>
          <ErrorBoundary label="Engine status">
            <EngineStatusPanel />
          </ErrorBoundary>
        </CollapsibleSection>

        {/* ── CLINICAL RESEARCH SIGNALS ── */}
        <CollapsibleSection id="clinical" title="Clinical research signals" defaultOpen>
          <ErrorBoundary label="Clinical research">
            <ClinicalResearchPanel />
          </ErrorBoundary>
        </CollapsibleSection>

        {/* ── AUTONOMIC LOAD ── */}
        <CollapsibleSection id="stress" title="Autonomic load" defaultOpen>
          <div className="space-y-5">
            <ErrorBoundary label="Stress">
              <StressPanel />
            </ErrorBoundary>
            <ErrorBoundary label="WHOOP behavior impact">
              <BehaviorImpactPanel />
            </ErrorBoundary>
          </div>
        </CollapsibleSection>

        {/* ── WHAT MOVES YOUR HRV ── */}
        <CollapsibleSection id="correlations" title="What moves your HRV" defaultOpen>
          <ErrorBoundary label="HRV correlations">
            <CorrelationCards />
          </ErrorBoundary>
        </CollapsibleSection>

        {/* ── LONGITUDINAL OBSERVATIONS ── */}
        <CollapsibleSection id="trends" title="Longitudinal observations" defaultOpen>
          <ErrorBoundary label="Trends">
            <TrendIntelligence />
          </ErrorBoundary>
        </CollapsibleSection>
      </div>
    </AppShell>
  );
}
