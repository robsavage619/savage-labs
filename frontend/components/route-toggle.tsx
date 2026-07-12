"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

export function RouteToggle() {
  const path = usePathname();
  const items = [
    { href: "/", label: "Dashboard" },
    { href: "/lab", label: "Lab" },
  ] as const;

  return (
    <div
      className="flex items-center gap-0.5 rounded-full border border-[var(--hairline)] p-0.5"
      style={{ background: "oklch(0.09 0.006 250)" }}
    >
      {items.map(({ href, label }) => {
        const active = href === "/" ? path === "/" : path.startsWith(href);
        return (
          <Link
            key={href}
            href={href}
            className={
              "no-tactile px-3 py-1 rounded-full text-[11px] uppercase tracking-wider transition-colors " +
              (active
                ? "text-[var(--text-primary)] bg-[oklch(1_0_0_/_0.07)]"
                : "text-[var(--text-dim)] hover:text-[var(--text-muted)]")
            }
            style={{ fontFamily: "var(--font-orbitron)" }}
          >
            {label}
          </Link>
        );
      })}
    </div>
  );
}
