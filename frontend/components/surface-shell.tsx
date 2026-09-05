"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { SURFACES } from "@/lib/sections";
import { HeaderHUD } from "@/components/header-hud";
import { SyncStatus } from "@/components/sync-status";
import { LiveBadge } from "@/components/live-badge";
import { CommandPalette } from "@/components/command-palette";
import { ErrorBoundary } from "@/components/error-boundary";

/**
 * The chrome all four surfaces share.
 *
 * Replaces AppShell's stack of wordmark + HUD + route toggle + section nav +
 * sync bar. The section nav is gone: it listed cluster ids that did not match
 * any section on the page, so every click scrolled to an inert divider, and at
 * 1728px a board that shows everything has nothing to jump past. Finding a
 * specific card is ⌘K's job now, over the same manifest the pages render from.
 *
 * SyncStatus stays because it carries the WHOOP reauth link — the one control
 * that, when it is needed, nothing else in the app can substitute for.
 */
export function SurfaceShell({ children }: { children: ReactNode }) {
  const path = usePathname();

  return (
    <main className="min-h-screen px-8 pb-24 pt-5 max-w-[1680px] mx-auto">
      <header className="flex items-center justify-between flex-wrap gap-x-6 gap-y-3 pb-4 mb-5 border-b border-[var(--hairline)]">
        <div className="flex items-baseline gap-3 shrink-0">
          <h1 className="flex items-baseline gap-[0.4em]">
            <span className="sl-wordmark-savage">Savage</span>
            <span className="sl-wordmark-labs">Labs</span>
          </h1>
          <LiveBadge />
        </div>

        <nav className="flex items-center gap-1" aria-label="Surfaces">
          {SURFACES.map((s) => {
            const active = s.route === "/" ? path === "/" : path.startsWith(s.route);
            return (
              <Link
                key={s.id}
                href={s.route}
                title={s.purpose}
                aria-current={active ? "page" : undefined}
                className="no-tactile px-3.5 py-1.5 rounded-full transition-colors"
                style={{
                  fontFamily: "var(--font-data)",
                  fontSize: "var(--fs-label)",
                  letterSpacing: "0.1em",
                  textTransform: "uppercase",
                  color: active ? "var(--text-primary)" : "var(--text-faint)",
                  background: active ? "var(--card-hover)" : "transparent",
                }}
              >
                {s.label}
              </Link>
            );
          })}
          <button
            type="button"
            className="no-tactile ml-2 px-3 py-1.5 rounded-full border"
            style={{
              fontFamily: "var(--font-data)",
              fontSize: "10px",
              letterSpacing: "0.08em",
              color: "var(--text-faint)",
              borderColor: "var(--hairline)",
              background: "transparent",
            }}
            onClick={() =>
              document.dispatchEvent(new KeyboardEvent("keydown", { key: "k", metaKey: true }))
            }
          >
            ⌘K
          </button>
        </nav>

        <div className="shrink-0 min-w-0">
          <HeaderHUD />
        </div>
      </header>

      <SyncStatus />

      <ErrorBoundary label="Page">{children}</ErrorBoundary>
      <CommandPalette />
    </main>
  );
}
