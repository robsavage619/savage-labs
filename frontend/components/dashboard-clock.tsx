"use client";

import { useEffect, useState } from "react";

export function DashboardClock() {
  const [now, setNow] = useState<Date | null>(null);

  useEffect(() => {
    setNow(new Date());
    const id = setInterval(() => setNow(new Date()), 1_000);
    return () => clearInterval(id);
  }, []);

  if (!now) return null;

  const weekday = now.toLocaleDateString("en-US", { weekday: "short" }).toUpperCase();
  const day = String(now.getDate()).padStart(2, "0");
  const month = now.toLocaleDateString("en-US", { month: "short" }).toUpperCase();
  const rawHours = now.getHours();
  const hours = String(rawHours % 12 || 12);
  const minutes = String(now.getMinutes()).padStart(2, "0");
  const seconds = String(now.getSeconds()).padStart(2, "0");
  const ampm = rawHours < 12 ? "AM" : "PM";

  return (
    <div className="flex flex-col items-end gap-0.5 select-none">
      {/* Date eyebrow */}
      <div
        style={{
          fontFamily: "var(--font-orbitron)",
          fontSize: 9,
          fontWeight: 500,
          letterSpacing: "0.22em",
          color: "var(--text-dim)",
        }}
      >
        {weekday}&nbsp;·&nbsp;{day}&nbsp;{month}
      </div>

      {/* Time readout */}
      <div className="flex items-baseline gap-[3px]">
        <span
          style={{
            fontFamily: "var(--font-orbitron)",
            fontSize: 22,
            fontWeight: 900,
            letterSpacing: "0.06em",
            lineHeight: 1,
            color: "var(--text-primary)",
            fontVariantNumeric: "tabular-nums",
          }}
        >
          {hours}:{minutes}
        </span>
        <span
          style={{
            fontFamily: "var(--font-orbitron)",
            fontSize: 11,
            fontWeight: 500,
            letterSpacing: "0.06em",
            lineHeight: 1,
            color: "var(--text-faint)",
            fontVariantNumeric: "tabular-nums",
            marginBottom: 1,
          }}
        >
          {seconds}
        </span>
        <span
          style={{
            fontFamily: "var(--font-orbitron)",
            fontSize: 8,
            fontWeight: 500,
            letterSpacing: "0.12em",
            color: "var(--text-dim)",
            marginBottom: 2,
          }}
        >
          {ampm}
        </span>
      </div>
    </div>
  );
}
