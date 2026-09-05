"use client";

import { useEffect, useRef, type ReactNode } from "react";
import { SurfaceShell } from "@/components/surface-shell";
import { useQueryClient } from "@tanstack/react-query";

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
 */
function BoardCard({
  id,
  label,
  span,
  children,
}: {
  id?: string;
  label: string;
  span: Span;
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
        <BoardCard id="subject" label="Subject dossier" span={4}>
          <SubjectDossier />
        </BoardCard>

        {/* Four list panels of comparable density — no chart, no table wide
            enough to need three columns — so an even 2+2 on each row, with
            each companion card kept beside the anchored card it belongs to. */}
        <div className="board-rule">n-of-1 program</div>

        <BoardCard id="trials" label="Active trials" span={2}>
          <LabExperiments />
        </BoardCard>

        <BoardCard label="Suggested studies" span={2}>
          <SuggestedExperiments />
        </BoardCard>

        <BoardCard id="findings" label="Standing research program" span={2}>
          <LabPanel />
        </BoardCard>

        <BoardCard id="engine" label="Engine self-assessment" span={2}>
          <EngineStatusPanel />
        </BoardCard>

        {/* Ordered so each companion pair lands SIDE BY SIDE rather than
            stacked across a row break: the derived-signal panels take the
            first row, then autonomic load with the behaviour impact that
            annotates it. Both pairs are middling-height list panels, so an
            even 2+2 split is the right footprint for all four. */}
        <div className="board-rule">Physiological signals</div>

        <BoardCard id="signals" label="Clinical research signals" span={2}>
          <ClinicalResearchPanel />
        </BoardCard>

        <BoardCard id="correlations" label="What moves your HRV" span={2}>
          <CorrelationCards />
        </BoardCard>

        <BoardCard id="autonomic" label="Autonomic load" span={2}>
          <StressPanel />
        </BoardCard>

        <BoardCard label="WHOOP behaviour impact" span={2}>
          <BehaviorImpactPanel />
        </BoardCard>
      </div>
    </SurfaceShell>
  );
}
