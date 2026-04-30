"use client";

import { useQuery } from "@tanstack/react-query";
import { api, Correlation } from "@/lib/api";
import { Eyebrow } from "@/components/ui/metric";

const QUESTION_LABELS: Record<string, string> = {
  "Have any alcoholic drinks?": "Alcohol",
  "Hydrated sufficiently?": "Hydration",
  "Have any caffeine? ": "Caffeine",
  "Feeling sick or ill?": "Illness",
  "Viewed a screen device in bed?": "Screen in bed",
  "Read (non-screened device) while in bed?": "Reading in bed",
  "See direct sunlight upon waking up?": "Morning sunlight",
  "Consumed protein?": "Protein",
  "Eat any food close to bedtime?": "Late eating",
  "Share your bed?": "Shared bed",
  "Connected with family and/or friends?": "Social connection",
  "Have an injury or wound": "Injury",
  "Take prescription sleep medication?": "Sleep medication",
};

function DeltaBar({ delta, max }: { delta: number; max: number }) {
  const pct = Math.min(Math.abs(delta) / max, 1) * 100;
  const positive = delta >= 0;
  return (
    <div className="flex items-center gap-2 mt-1.5">
      <div className="flex-1 h-1 rounded-full overflow-hidden" style={{ background: "oklch(1 0 0 / 0.06)" }}>
        <div
          className="h-full rounded-full transition-all"
          style={{ width: `${pct}%`, background: positive ? "var(--positive)" : "var(--negative)" }}
        />
      </div>
      <span className="text-[10px] font-mono tabular-nums w-14 text-right" style={{ color: positive ? "var(--positive)" : "var(--negative)" }}>
        {positive ? "+" : ""}{delta.toFixed(1)} ms
      </span>
    </div>
  );
}

function coachLine(c: Correlation): string {
  const delta = Math.abs(c.hrv_delta!).toFixed(1);
  const q = c.question.toLowerCase();
  if (q.includes("alcohol")) return `Alcohol nights cost ~${delta}ms HRV next morning`;
  if (q.includes("hydrated")) return `Well-hydrated days show +${delta}ms HRV vs dehydrated`;
  if (q.includes("caffeine")) return `Caffeine days: ${c.hrv_delta! > 0 ? "+" : ""}${delta}ms HRV vs no caffeine`;
  if (q.includes("sick")) return `Illness suppresses HRV by ~${delta}ms`;
  if (q.includes("sunlight")) return `Morning sunlight correlates with ${delta}ms higher HRV`;
  if (q.includes("screen")) return `Screen in bed: ${delta}ms ${c.hrv_delta! < 0 ? "lower" : "higher"} HRV`;
  if (q.includes("bedtime")) return `Late eating: ${delta}ms ${c.hrv_delta! < 0 ? "lower" : "higher"} HRV`;
  return "";
}

export function CorrelationCards() {
  const { data = [], isLoading } = useQuery({
    queryKey: ["correlations"],
    queryFn: api.insightsCorrelations,
    refetchInterval: 3_600_000,
  });

  const significant = data.filter(c => c.hrv_delta != null && Math.abs(c.hrv_delta) >= 1);
  const maxDelta = significant.length ? Math.max(...significant.map(c => Math.abs(c.hrv_delta!))) : 10;

  if (isLoading) {
    return (
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {[...Array(6)].map((_, i) => <div key={i} className="h-20 shc-skeleton rounded-lg" />)}
      </div>
    );
  }

  if (significant.length === 0) {
    const days = data[0]?.sample_days ?? 0;
    const remaining = Math.max(0, 14 - days);
    return (
      <div className="space-y-3">
        <p className="shc-helptext">
          <span className="text-[var(--text-muted)]">How to read this. </span>
          Each card shows the avg HRV difference between days where the journal answer
          was Yes vs No. Bars are scaled to the largest effect; positive (green) means
          higher HRV.
        </p>
        <div className="rounded-[var(--r-md)] border border-dashed border-[var(--hairline-strong)] p-6 text-center">
          <p className="text-[13px] text-[var(--text-muted)]">Not enough journal data yet.</p>
          <p className="text-[11.5px] text-[var(--text-dim)] mt-1">
            {days > 0
              ? `${days} paired days so far · ${remaining} more days unlock first correlations`
              : "Log the WHOOP journal nightly. After ~14 paired days, factor effects appear here."}
          </p>
        </div>
        <ul className="text-[11px] text-[var(--text-dim)] space-y-1 pt-1">
          <li>• Sleep, hydration, alcohol, and screen time are the highest-signal factors.</li>
          <li>• Effects ≥ 1ms HRV are surfaced; below that they&apos;re statistical noise.</li>
        </ul>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-baseline justify-between">
        <Eyebrow>What moves your HRV</Eyebrow>
        <span className="text-[10.5px] text-[var(--text-dim)]">
          {significant.length} factors · {data[0]?.sample_days ?? 0}+ days
        </span>
      </div>
      <p className="shc-helptext">
        <span className="text-[var(--text-muted)]">How to read this. </span>
        Each bar is the average HRV difference (next-morning) between days when this
        factor was on vs off. Green = HRV-positive, red = HRV-negative. Bigger bar = bigger effect.
      </p>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {significant.map(c => {
          const label = QUESTION_LABELS[c.question] ?? c.question;
          const line = coachLine(c);
          return (
            <div
              key={c.question}
              className="rounded-lg border border-[var(--hairline)] p-4 hover:border-[var(--hairline-strong)] transition-colors"
            >
              <div className="flex items-center justify-between">
                <span className="text-[12px] font-medium text-[var(--text-muted)]">{label}</span>
                <span className="text-[10px] font-mono text-[var(--text-faint)]">{c.sample_days}d</span>
              </div>
              <DeltaBar delta={c.hrv_delta!} max={maxDelta} />
              {line && <p className="text-[11px] mt-2 leading-snug text-[var(--text-dim)]">{line}</p>}
            </div>
          );
        })}
      </div>
    </div>
  );
}
