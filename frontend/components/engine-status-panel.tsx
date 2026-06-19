"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Eyebrow } from "@/components/ui/metric";

function accuracyColor(v: number): string {
  if (v >= 0.7) return "var(--positive)";
  if (v >= 0.5) return "var(--warn)";
  return "var(--negative)";
}

// Tiny inline sparkline of weekly accuracy snapshots.
function Sparkline({ points }: { points: { overall: number | null }[] }) {
  const vals = points.map((p) => p.overall).filter((v): v is number => v != null);
  if (vals.length < 2) return null;
  const w = 96;
  const h = 20;
  const min = Math.min(...vals);
  const max = Math.max(...vals);
  const span = max - min || 1;
  const step = w / (vals.length - 1);
  const d = vals
    .map((v, i) => `${i === 0 ? "M" : "L"}${(i * step).toFixed(1)},${(h - ((v - min) / span) * h).toFixed(1)}`)
    .join(" ");
  const last = vals[vals.length - 1];
  return (
    <svg width={w} height={h} className="overflow-visible">
      <path d={d} fill="none" stroke={accuracyColor(last)} strokeWidth={1.5} strokeLinejoin="round" />
      <circle cx={w} cy={h - ((last - min) / span) * h} r={2} fill={accuracyColor(last)} />
    </svg>
  );
}

export function EngineStatusPanel() {
  const status = useQuery({
    queryKey: ["self-learning-status"],
    queryFn: api.trainingSelfLearning,
    refetchInterval: 10 * 60_000,
  });

  if (status.isLoading || status.isError || !status.data) return null;

  const { prescription_accuracy, accuracy_history, deload_calibration, acwr_bands, volume_landmarks } =
    status.data;

  const overall = prescription_accuracy.overall;
  const personalLandmarks = volume_landmarks.filter((l) => l.source !== "population").length;
  const deloadFitted = !deload_calibration.using_population_defaults;

  return (
    <div className="rounded-lg border border-[var(--hairline)] p-4 space-y-3">
      <div className="flex items-baseline justify-between">
        <Eyebrow>Engine self-assessment</Eyebrow>
        <span className="text-[10px] text-[var(--text-faint)]">self-learning controller</span>
      </div>

      {/* Prescription accuracy + drift sparkline */}
      <div className="flex items-center justify-between">
        <div>
          <div className="text-[11px] text-[var(--text-muted)]">Prescription accuracy</div>
          <div className="text-[10px] text-[var(--text-faint)]">
            {prescription_accuracy.n_scored} call{prescription_accuracy.n_scored === 1 ? "" : "s"} backtested
          </div>
        </div>
        <div className="flex items-center gap-3">
          <Sparkline points={accuracy_history} />
          <span
            className="tabular-nums text-[18px] font-medium"
            style={{ color: overall != null ? accuracyColor(overall) : "var(--text-faint)" }}
          >
            {overall != null ? `${Math.round(overall * 100)}%` : "—"}
          </span>
        </div>
      </div>

      {/* Parameter sources: how much of the engine is personalized vs population */}
      <div className="grid grid-cols-3 gap-2 pt-2 border-t border-[var(--hairline)]">
        <SourceStat
          label="Deload trigger"
          value={deloadFitted ? `${deload_calibration.threshold} muscles` : `${deload_calibration.population_threshold} (default)`}
          personal={deloadFitted}
        />
        <SourceStat
          label="ACWR bands"
          value={acwr_bands.source === "personal" ? `personal · ${acwr_bands.sample_weeks}w` : "population"}
          personal={acwr_bands.source === "personal"}
        />
        <SourceStat
          label="Volume landmarks"
          value={personalLandmarks > 0 ? `${personalLandmarks} fitted` : "population"}
          personal={personalLandmarks > 0}
        />
      </div>

      <p className="text-[10px] text-[var(--text-faint)] leading-relaxed pt-1 border-t border-[var(--hairline)]">
        {deload_calibration.message}
      </p>
    </div>
  );
}

function SourceStat({ label, value, personal }: { label: string; value: string; personal: boolean }) {
  return (
    <div className="space-y-0.5">
      <div className="text-[10px] text-[var(--text-faint)]">{label}</div>
      <div
        className="text-[11px] tabular-nums"
        style={{ color: personal ? "var(--positive)" : "var(--text-dim)" }}
      >
        {value}
      </div>
    </div>
  );
}
