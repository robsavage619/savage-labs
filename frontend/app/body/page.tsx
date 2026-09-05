"use client";

import type { ReactNode } from "react";
import { SurfaceShell } from "@/components/surface-shell";

import { BodyPane } from "@/components/body-panel";
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
 * span, and the label rule.
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

export default function BodyPage() {
  return (
    <SurfaceShell>
      <div className="board">
        <div className="board-rule">Intake &amp; physique</div>

        <BoardCard id="fueling" label="Fuelling" span={2}>
          <FuelingPanel />
        </BoardCard>

        <BoardCard id="physique" label="Progress photos" span={2}>
          <ProgressPhotoPanel />
        </BoardCard>

        <div className="board-rule">The body itself</div>

        <BoardCard id="composition" label="Body composition" span={4}>
          <BodyPane />
        </BoardCard>

        {/* 649 lines of risk strip, meds, labs table and panel results — the
            widest surface in the app, and until now reachable only through a tab
            bar inside a collapsed accordion. */}
        <BoardCard id="clinical" label="Clinical record" span={4}>
          <ClinicalOverview />
        </BoardCard>
      </div>
    </SurfaceShell>
  );
}
