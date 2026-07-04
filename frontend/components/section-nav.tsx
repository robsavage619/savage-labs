"use client";

import { useEffect, useState } from "react";

const SECTIONS = [
  { id: "today", label: "Today" },
  { id: "signals", label: "Signals" },
  { id: "plan", label: "Plan" },
  { id: "engine", label: "Engine" },
  { id: "training", label: "Training" },
  { id: "body", label: "Body" },
  { id: "intel", label: "Intelligence" },
] as const;

export function SectionNav() {
  const [active, setActive] = useState<string>("today");

  useEffect(() => {
    const els = SECTIONS.map((s) => document.getElementById(s.id)).filter(
      (e): e is HTMLElement => e != null,
    );
    if (els.length === 0) return;

    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => b.intersectionRatio - a.intersectionRatio);
        if (visible[0]) setActive(visible[0].target.id);
      },
      { rootMargin: "-30% 0px -60% 0px", threshold: [0, 0.25, 0.5, 1] },
    );
    els.forEach((el) => observer.observe(el));
    return () => observer.disconnect();
  }, []);

  const go = (id: string) => {
    // Update the hash without a jump, then fire hashchange so a collapsed
    // section's listener can expand itself before we smooth-scroll to it.
    window.history.replaceState(null, "", `#${id}`);
    window.dispatchEvent(new HashChangeEvent("hashchange"));
    requestAnimationFrame(() => {
      document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
    setActive(id);
  };

  return (
    <nav
      className="sticky top-0 z-30 -mx-5 px-5 py-2 mb-4 border-b border-[var(--hairline)] backdrop-blur-md"
      style={{ background: "oklch(0.11 0.006 250 / 0.78)" }}
      aria-label="Dashboard sections"
    >
      <div className="flex items-center gap-1 overflow-x-auto no-scrollbar">
        {SECTIONS.map((s) => {
          const on = active === s.id;
          return (
            <button
              key={s.id}
              type="button"
              onClick={() => go(s.id)}
              className="shrink-0 px-3 py-1 rounded-full text-[11px] uppercase tracking-wider transition-colors"
              style={{
                fontFamily: "var(--font-orbitron)",
                color: on ? "var(--text-primary)" : "var(--text-dim)",
                background: on ? "oklch(1 0 0 / 0.06)" : "transparent",
                border: `1px solid ${on ? "var(--hairline)" : "transparent"}`,
              }}
            >
              {s.label}
            </button>
          );
        })}
      </div>
    </nav>
  );
}
