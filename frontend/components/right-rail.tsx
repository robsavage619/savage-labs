"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Eyebrow } from "@/components/ui/metric";

function StreakCard() {
  const stats = useQuery({ queryKey: ["stats-summary"], queryFn: api.statsSummary });
  const rec = stats.data?.streaks.recovery_above_60 ?? 0;
  const slp = stats.data?.streaks.sleep_above_7h ?? 0;
  return (
    <div className="shc-card shc-enter p-4 space-y-3">
      <Eyebrow>Streaks</Eyebrow>
      <div className="space-y-2.5">
        <StreakRow label="Recovery >60" value={rec} tone={rec >= 7 ? "positive" : rec >= 3 ? "neutral" : "negative"} />
        <StreakRow label="Sleep >7h" value={slp} tone={slp >= 5 ? "positive" : slp >= 2 ? "neutral" : "negative"} />
        <StreakRow label="Training on plan" value={0} tone="neutral" ghost />
      </div>
    </div>
  );
}

function StreakRow({ label, value, tone, ghost }: { label: string; value: number; tone: "positive" | "neutral" | "negative"; ghost?: boolean }) {
  const color = tone === "positive" ? "var(--positive)" : tone === "negative" ? "var(--negative)" : "var(--neutral)";
  return (
    <div className="flex items-baseline justify-between gap-3">
      <span className="text-[11.5px] text-[var(--text-muted)]">{label}</span>
      <div className="flex items-baseline gap-1.5">
        {ghost ? (
          <span className="text-[11px] text-[var(--text-faint)]">P2</span>
        ) : (
          <>
            <span className="metric-md tabular-nums" style={{ color }}>{value}</span>
            <span className="text-[10px] text-[var(--text-dim)]">days</span>
          </>
        )}
      </div>
    </div>
  );
}

function PersonalBestsCard() {
  const pb = useQuery({ queryKey: ["personal-bests"], queryFn: api.personalBests });
  const rows = [
    ...(pb.data?.top_hrv.slice(0, 2).map((r) => ({ label: "HRV peak", date: r.date, value: `${r.value.toFixed(1)} ms` })) ?? []),
    ...(pb.data?.lowest_rhr.slice(0, 1).map((r) => ({ label: "RHR low", date: r.date, value: `${r.value} bpm` })) ?? []),
    ...(pb.data?.longest_sleep.slice(0, 2).map((r) => ({ label: "Long sleep", date: r.date, value: `${r.value.toFixed(1)} h` })) ?? []),
  ];
  return (
    <div className="shc-card shc-enter p-4">
      <Eyebrow>Personal bests</Eyebrow>
      <div className="mt-2.5 space-y-1.5">
        {rows.length === 0
          ? Array.from({ length: 3 }).map((_, i) => <div key={i} className="shc-skeleton h-[18px]" />)
          : rows.map((r, i) => (
              <div key={i} className="flex items-baseline justify-between text-[11.5px]">
                <span className="text-[var(--text-muted)]">{r.label}</span>
                <span className="tabular-nums text-[var(--text-primary)]">{r.value}</span>
              </div>
            ))}
      </div>
    </div>
  );
}

function toneFor(score: number | null): "positive" | "neutral" | "negative" | "empty" {
  if (score == null) return "empty";
  if (score >= 67) return "positive";
  if (score >= 34) return "neutral";
  return "negative";
}

function WeekStripCard() {
  const week = useQuery({ queryKey: ["week-summary"], queryFn: api.weekSummary });
  return (
    <div className="shc-card shc-enter p-4">
      <Eyebrow>This week</Eyebrow>
      <div className="grid grid-cols-7 gap-1 mt-2.5">
        {(week.data ?? []).map((d) => {
          const t = toneFor(d.recovery);
          const bg =
            t === "positive"
              ? "var(--positive-soft)"
              : t === "negative"
              ? "var(--negative-soft)"
              : t === "neutral"
              ? "var(--neutral-soft)"
              : "oklch(1 0 0 / 0.03)";
          const border =
            t === "positive"
              ? "var(--positive)"
              : t === "negative"
              ? "var(--negative)"
              : t === "neutral"
              ? "var(--neutral)"
              : "var(--hairline)";
          return (
            <div
              key={d.date}
              className="aspect-square rounded-sm flex flex-col items-center justify-center gap-0.5 text-[9px]"
              style={{
                background: bg,
                border: `1px solid ${border}`,
                outline: d.is_today ? "1px solid var(--text-primary)" : "none",
                outlineOffset: 1,
                opacity: d.is_future ? 0.35 : 1,
              }}
              title={`${d.label} ${d.date} · recovery ${d.recovery ?? "—"}`}
            >
              <span className="text-[var(--text-dim)]">{d.label[0]}</span>
              <span className="tabular-nums text-[var(--text-primary)]">{d.recovery != null ? Math.round(d.recovery) : "·"}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function GoalsCard() {
  return (
    <div className="shc-card shc-enter p-4">
      <Eyebrow>Goal · 30d HRV &gt; 70</Eyebrow>
      <div className="mt-2.5">
        <div className="flex items-baseline justify-between">
          <span className="metric-md tabular-nums text-[var(--text-primary)]">12<span className="text-[10px] text-[var(--text-dim)] ml-1">/30</span></span>
          <span className="text-[10.5px] text-[var(--text-dim)] tabular-nums">40%</span>
        </div>
        <div className="mt-2 h-1.5 rounded-full bg-[oklch(1_0_0/0.06)]">
          <div className="h-full rounded-full" style={{ width: "40%", background: "var(--positive)" }} />
        </div>
        <p className="text-[10.5px] text-[var(--text-dim)] mt-2">Edit in Onboarding (P3)</p>
      </div>
    </div>
  );
}

export function RightRail() {
  return (
    <aside className="space-y-3 w-full">
      <WeekStripCard />
      <StreakCard />
      <PersonalBestsCard />
      <GoalsCard />
    </aside>
  );
}
