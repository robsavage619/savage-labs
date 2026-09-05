"use client";

import { useEffect, useState, type ReactNode } from "react";
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

const TYPES = [
  { id: "studio", label: "Studio" },
  { id: "swiss", label: "Swiss" },
  { id: "plain", label: "Plain" },
] as const;
type TypeId = (typeof TYPES)[number]["id"];

export function ConsoleShell({ children }: { children: ReactNode }) {
  const path = usePathname();
  const [type, setType] = useState<TypeId>("studio");
  useEffect(() => {
    try {
      const v = localStorage.getItem("cx_type") as TypeId | null;
      if (v && TYPES.some((t) => t.id === v)) setType(v);
    } catch {
      // localStorage unavailable — keep the default
    }
  }, []);
  const pick = (t: TypeId) => {
    setType(t);
    try {
      localStorage.setItem("cx_type", t);
    } catch {
      // fine
    }
  };

  return (
    <div className="cx" data-type={type}>
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

          <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
            <div className="cx-type" role="group" aria-label="Type system">
              {TYPES.map((t) => (
                <button key={t.id} type="button" className="no-tactile"
                  aria-pressed={type === t.id} onClick={() => pick(t.id)}>
                  {t.label}
                </button>
              ))}
            </div>
            <span className="cx-when">
              {new Date().toLocaleDateString("en-US", {
                weekday: "short", month: "short", day: "numeric",
              })}
            </span>
          </div>
        </div>

        {children}
      </div>
    </div>
  );
}
