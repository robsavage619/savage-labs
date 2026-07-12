"use client";

import { useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { SubjectDossier } from "@/components/subject-dossier";
import { LabExperiments } from "@/components/lab-experiments";
import { LabPanel } from "@/components/lab-panel";
import { EngineStatusPanel } from "@/components/engine-status-panel";
import { ClinicalResearchPanel } from "@/components/clinical-research-panel";
import { CorrelationCards } from "@/components/correlation-cards";
import { TrendIntelligence } from "@/components/trend-intelligence";
import { SectionNav } from "@/components/section-nav";
import { CollapsibleSection } from "@/components/collapsible-section";
import { ErrorBoundary } from "@/components/error-boundary";
import { AmbientHue } from "@/components/ambient-hue";
import { DashboardClock } from "@/components/dashboard-clock";
import { LiveBadge } from "@/components/live-badge";
import { HeaderHUD } from "@/components/header-hud";
import { ProtocolStrip } from "@/components/protocol-strip";
import { RouteToggle } from "@/components/route-toggle";
import { SyncStatus } from "@/components/sync-status";
import { SuggestedExperiments } from "@/components/suggested-experiments";
import { api } from "@/lib/api";

const LAB_SECTIONS = [
  { id: "dossier", label: "Subject" },
  { id: "studies", label: "Studies" },
  { id: "findings", label: "Findings" },
  { id: "engine", label: "Engine" },
  { id: "clinical", label: "Clinical" },
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
    <main className="min-h-screen px-5 pb-20 pt-6 max-w-[1600px] mx-auto">
      <AmbientHue />
      <header className="flex items-stretch justify-between flex-wrap pb-5 border-b border-[var(--hairline)] mb-5 gap-4">
        <div className="flex flex-col justify-end gap-2 shrink-0">
          <div className="flex items-baseline gap-3 flex-wrap">
            <h1 className="flex items-baseline gap-[0.5em]">
              <span className="sl-wordmark-savage">Savage</span>
              <span className="sl-wordmark-labs">Labs</span>
            </h1>
            <span className="sl-wordmark-beta">β</span>
            <LiveBadge />
            <span className="sl-classified-badge">INTERNAL // AUTH</span>
          </div>
          <div className="sl-wordmark-bar" />
        </div>
        <div className="order-last w-full md:order-none md:w-auto md:flex-1 flex min-w-0">
          <HeaderHUD />
        </div>
        <div className="shrink-0 flex items-end gap-3">
          <RouteToggle />
          <DashboardClock />
        </div>
      </header>

      <ProtocolStrip />

      <SectionNav sections={LAB_SECTIONS} />

      <div className="mb-4">
        <SyncStatus />
      </div>

      <div className="space-y-4">
        {/* ── SUBJECT DOSSIER ── */}
        <section id="dossier" className="scroll-mt-20">
          <ErrorBoundary label="Subject dossier">
            <SubjectDossier />
          </ErrorBoundary>
        </section>

        {/* ── STUDIES (n-of-1 + suggestions) ── */}
        <CollapsibleSection id="studies" title="Active studies · n-of-1 trials">
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
        <CollapsibleSection id="findings" title="Standing research program">
          <ErrorBoundary label="Research lab">
            <LabPanel />
          </ErrorBoundary>
        </CollapsibleSection>

        {/* ── ENGINE SELF-ASSESSMENT ── */}
        <CollapsibleSection id="engine" title="Engine self-assessment">
          <ErrorBoundary label="Engine status">
            <EngineStatusPanel />
          </ErrorBoundary>
        </CollapsibleSection>

        {/* ── CLINICAL RESEARCH SIGNALS ── */}
        <CollapsibleSection id="clinical" title="Clinical research signals">
          <ErrorBoundary label="Clinical research">
            <ClinicalResearchPanel />
          </ErrorBoundary>
        </CollapsibleSection>

        {/* ── WHAT MOVES YOUR HRV ── */}
        <CollapsibleSection id="correlations" title="What moves your HRV">
          <ErrorBoundary label="HRV correlations">
            <CorrelationCards />
          </ErrorBoundary>
        </CollapsibleSection>

        {/* ── LONGITUDINAL OBSERVATIONS ── */}
        <CollapsibleSection id="trends" title="Longitudinal observations">
          <ErrorBoundary label="Trends">
            <TrendIntelligence />
          </ErrorBoundary>
        </CollapsibleSection>
      </div>
    </main>
  );
}
