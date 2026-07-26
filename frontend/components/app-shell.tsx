"use client";

import type { ReactNode } from "react";

import { AmbientHue } from "@/components/ambient-hue";
import { DashboardClock } from "@/components/dashboard-clock";
import { LiveBadge } from "@/components/live-badge";
import { HeaderHUD } from "@/components/header-hud";
import { RouteToggle } from "@/components/route-toggle";
import { SectionNav } from "@/components/section-nav";
import { SyncStatus } from "@/components/sync-status";
import { ErrorBoundary } from "@/components/error-boundary";

type SectionItem = { id: string; label: string };

/**
 * The chrome every surface shares: wordmark, the canonical readiness HUD, the
 * route toggle, and the section nav.
 *
 * Previously each route hand-rolled this header, and the stack ran four bars
 * deep — wordmark, HUD, toggle, ticker, nav — which cost ~550px before any
 * content on a phone. The decorative ticker is gone (every number in it was
 * already on screen elsewhere) and the rest lives here once.
 */
export function AppShell({
  sections,
  children,
}: {
  sections: readonly SectionItem[];
  children: ReactNode;
}) {
  return (
    <main className="min-h-screen px-5 pb-20 pt-5 max-w-[1600px] mx-auto">
      <AmbientHue />
      <header className="flex items-center justify-between flex-wrap pb-3 border-b border-[var(--hairline)] mb-3 gap-x-4 gap-y-2">
        <div className="flex items-baseline gap-3 shrink-0">
          <h1 className="flex items-baseline gap-[0.5em]">
            <span className="sl-wordmark-savage">Savage</span>
            <span className="sl-wordmark-labs">Labs</span>
          </h1>
          <span className="sl-wordmark-beta">β</span>
          <LiveBadge />
        </div>
        <div className="order-last w-full md:order-none md:w-auto md:flex-1 flex min-w-0">
          <HeaderHUD />
        </div>
        <div className="shrink-0 flex items-center gap-3">
          <RouteToggle />
          <DashboardClock />
        </div>
      </header>

      <SectionNav sections={sections} />

      <div className="mb-4">
        <SyncStatus />
      </div>

      <ErrorBoundary label="Page">{children}</ErrorBoundary>
    </main>
  );
}
