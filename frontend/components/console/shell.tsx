"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import "@/components/console/console.css";

/**
 * The chrome the three boards share.
 *
 * Boards, not pages of accordions: Ops is what to do today, Signals is what
 * the body is doing, Research is what the system has learned. Each is one
 * screen of grid at 1600px, and nothing on any of them collapses — the width
 * does the work the accordions were doing.
 */
const BOARDS = [
  { href: "/ops", label: "Ops" },
  { href: "/signals", label: "Signals" },
  { href: "/research", label: "Research" },
] as const;

export function ConsoleShell({ children }: { children: ReactNode }) {
  const path = usePathname();

  return (
    <div className="cx">
      <div className="cx-wrap">
        <div className="cx-top">
          <span className="cx-word">
            Savage <em>Labs</em>
          </span>

          <nav className="cx-boards" aria-label="Boards">
            {BOARDS.map((b) => (
              <Link
                key={b.href}
                href={b.href}
                className="no-tactile"
                aria-current={path === b.href ? "page" : undefined}
              >
                {b.label}
              </Link>
            ))}
            <span className="cx-boards-sep" aria-hidden="true" />
            <Link href="/" className="no-tactile cx-boards-old">
              Classic
            </Link>
          </nav>

          <span className="cx-when">
            {new Date().toLocaleDateString("en-US", {
              weekday: "short",
              month: "short",
              day: "numeric",
            })}
          </span>
        </div>

        {children}
      </div>
    </div>
  );
}
