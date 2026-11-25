"use client";

import { useEffect, type ReactNode } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { api } from "@/lib/api";
import { SURFACES } from "@/lib/sections";
import { HeaderHUD } from "@/components/header-hud";
import { Freshness, SyncStatus } from "@/components/sync-status";
import { RefreshButton } from "@/components/refresh-button";
import { QueryErrors } from "@/components/query-errors";
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
 * SyncStatus sits beside LIVE as a chip: it carries the WHOOP reauth link, the
 * one control nothing else in the app can substitute for, without a page-wide bar.
 */
/** Phone tab bar glyphs, one stroked path each on a 24px grid. */
const TAB_ICON: Record<string, string> = {
  today: "M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6l1.4 1.4M17 17l1.4 1.4M5.6 18.4 7 17M17 7l1.4-1.4M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8Z",
  training: "M3 12h18M6 7v10M18 7v10M3.5 9.5v5M20.5 9.5v5",
  recovery: "M3 12h4l2-5 4 10 2-5h6",
  body: "M12 3a2 2 0 1 0 0 4 2 2 0 0 0 0-4ZM6 10h12M12 10v5M12 15l-3 6M12 15l3 6",
  healthspan: "M12 20s-7-4.4-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 5.6-7 10-7 10Z",
  lab: "M9 3h6M10 3v6l-5 9a2 2 0 0 0 1.8 3h10.4A2 2 0 0 0 19 18l-5-9V3M7.5 15h9",
};

export function SurfaceShell({ children }: { children: ReactNode }) {
  const path = usePathname();
  useEffect(() => {
    api.recordView(path);
  }, [path]);

  return (
    <main className="sl-shell min-h-screen max-w-[1680px] mx-auto">
      <header className="flex items-center justify-between flex-wrap gap-x-6 gap-y-3 pb-4 mb-5 border-b border-[var(--hairline)]">
        <div className="flex items-baseline flex-wrap gap-x-3 gap-y-2 min-w-0">
          <h1 className="flex items-baseline gap-[0.4em]">
            <span className="sl-wordmark-savage">Savage</span>
            <span className="sl-wordmark-labs">Labs</span>
          </h1>
          <LiveBadge />
          <SyncStatus />
          <Freshness />
          <QueryErrors />
          <RefreshButton />
        </div>

        <nav className="sl-shell-nav flex items-center gap-1" aria-label="Surfaces">
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

      <ErrorBoundary label="Page">{children}</ErrorBoundary>
      <CommandPalette />

      {/* Phones only (CSS): the top tab row can't fit five surfaces at 390px. */}
      <nav className="sl-tabbar" aria-label="Surfaces">
        {SURFACES.map((s) => {
          const active = s.route === "/" ? path === "/" : path.startsWith(s.route);
          return (
            <Link
              key={s.id}
              href={s.route}
              aria-current={active ? "page" : undefined}
              className="sl-tab no-tactile"
              onClick={(e) => {
                // Tapping the surface you are on returns to its top, as a phone tab bar does.
                if (!active) return;
                e.preventDefault();
                window.scrollTo({ top: 0, behavior: "smooth" });
              }}
            >
              <i aria-hidden="true" />
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path d={TAB_ICON[s.id]} />
              </svg>
              {s.label}
            </Link>
          );
        })}
      </nav>
    </main>
  );
}
