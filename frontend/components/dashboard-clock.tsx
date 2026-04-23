"use client";

import { useEffect, useState } from "react";

export function DashboardClock() {
  const [now, setNow] = useState<Date | null>(null);

  useEffect(() => {
    setNow(new Date());
    const id = setInterval(() => setNow(new Date()), 60_000);
    return () => clearInterval(id);
  }, []);

  if (!now) return null;

  const dayLabel = now.toLocaleDateString("en-US", { weekday: "long", month: "short", day: "numeric" });
  const timeLabel = now.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });

  return (
    <div className="text-[11px] text-[var(--text-dim)] tabular-nums flex gap-3">
      <span>{dayLabel}</span>
      <span className="text-[var(--text-faint)]">·</span>
      <span>{timeLabel}</span>
    </div>
  );
}
