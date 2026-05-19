"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Eyebrow } from "@/components/ui/metric";
import { WarningIcon } from "@/components/ui/icons";
import { ObsidianMark } from "@/components/obsidian-badge";

// Human-readable muscle group labels
const MUSCLE_LABELS: Record<string, string> = {
  chest: "Chest",
  back: "Back",
  quads: "Quads",
  hamstrings: "Hamstrings",
  glutes: "Glutes",
  front_delts: "Front Delts",
  side_delts: "Side Delts",
  rear_delts: "Rear Delts",
  biceps: "Biceps",
  triceps: "Triceps",
  traps: "Traps",
  calves: "Calves",
  core: "Core",
  brachialis: "Brachialis",
};

function volumeZone(sets: number, mev: number | null, mav: number | null, mrv: number | null): {
  label: string;
  color: string;
  bg: string;
} {
  if (mev == null) return { label: "no target", color: "var(--text-faint)", bg: "transparent" };
  if (sets < mev) return { label: "below MEV", color: "oklch(0.65 0.14 220)", bg: "oklch(0.65 0.14 220 / 0.12)" };
  if (mav != null && sets < mav) return { label: "productive", color: "var(--positive)", bg: "oklch(0.62 0.16 145 / 0.12)" };
  if (mrv != null && sets < mrv) return { label: "approaching MRV", color: "var(--warn)", bg: "oklch(0.65 0.16 80 / 0.12)" };
  return { label: "over MRV", color: "var(--negative)", bg: "oklch(0.55 0.22 25 / 0.12)" };
}

function MuscleBar({
  muscle,
  weekly_sets,
  mev,
  mav,
  mrv,
}: {
  muscle: string;
  weekly_sets: number;
  mev: number | null;
  mav: number | null;
  mrv: number | null;
}) {
  const zone = volumeZone(weekly_sets, mev, mav, mrv);
  const max = mrv != null ? mrv * 1.2 : Math.max(weekly_sets * 1.5, 20);
  const pct = (v: number) => `${Math.min(100, (v / max) * 100)}%`;
  const label = MUSCLE_LABELS[muscle] ?? muscle.replace(/_/g, " ");

  return (
    <div className="space-y-1">
      <div className="flex items-baseline justify-between text-[11.5px]">
        <span className="capitalize text-[var(--text-muted)]">{label}</span>
        <div className="flex items-center gap-2">
          <span className="tabular-nums text-[var(--text-primary)]">{weekly_sets.toFixed(0)}</span>
          <span className="text-[var(--text-faint)] text-[10px]">sets</span>
          <span
            className="text-[10px] px-1.5 py-[1px] rounded-sm"
            style={{
              color: zone.color,
              border: `1px solid ${zone.color}`,
              background: zone.bg,
            }}
          >
            {zone.label}
          </span>
        </div>
      </div>
      <div className="relative h-[12px] rounded-sm overflow-hidden bg-[var(--hairline)]">
        {/* Zone fill bands */}
        {mev != null && (
          <div className="absolute inset-y-0 left-0" style={{ width: pct(mev), background: "oklch(0.4 0.04 60 / 0.4)" }} />
        )}
        {mev != null && mav != null && (
          <div
            className="absolute inset-y-0"
            style={{ left: pct(mev), width: `calc(${pct(mav)} - ${pct(mev)})`, background: "oklch(0.55 0.16 145 / 0.35)" }}
          />
        )}
        {mav != null && mrv != null && (
          <div
            className="absolute inset-y-0"
            style={{ left: pct(mav), width: `calc(${pct(mrv)} - ${pct(mav)})`, background: "oklch(0.6 0.16 80 / 0.4)" }}
          />
        )}
        {mrv != null && (
          <div className="absolute inset-y-0" style={{ left: pct(mrv), right: 0, background: "oklch(0.5 0.22 25 / 0.4)" }} />
        )}
        {/* Actual sets marker */}
        <div
          className="absolute inset-y-0 w-[2.5px] bg-[var(--text-primary)]"
          style={{ left: pct(weekly_sets), boxShadow: "0 0 0 1px var(--bg)" }}
        />
        {/* Landmark ticks */}
        {[mev, mav, mrv].filter(Boolean).map((t) => (
          <div
            key={t}
            className="absolute inset-y-0 w-px bg-[var(--bg)] opacity-60"
            style={{ left: pct(t!) }}
          />
        ))}
      </div>
      {(mev != null || mav != null || mrv != null) && (
        <div className="relative h-[10px] text-[8.5px] text-[var(--text-faint)] tabular-nums">
          {mev != null && (
            <span className="absolute" style={{ left: pct(mev), transform: "translateX(-50%)" }}>MEV {mev}</span>
          )}
          {mav != null && (
            <span className="absolute" style={{ left: pct(mav), transform: "translateX(-50%)" }}>MAV {mav}</span>
          )}
          {mrv != null && (
            <span className="absolute" style={{ left: pct(mrv), transform: "translateX(-50%)" }}>MRV {mrv}</span>
          )}
        </div>
      )}
    </div>
  );
}

export function MuscleVolumePanel() {
  const volume = useQuery({
    queryKey: ["muscle-volume"],
    queryFn: api.muscleVolume,
    refetchInterval: 10 * 60_000,
  });

  if (volume.isLoading) return null;
  if (volume.isError) return null;

  const data = volume.data;
  if (!data || data.muscles.length === 0) {
    return (
      <div className="rounded-lg border border-[var(--hairline)] p-4">
        <Eyebrow>Per-muscle volume · this week</Eyebrow>
        <p className="mt-2 text-[11px] text-[var(--text-dim)]">
          No mapped exercises logged this week. Exercises need entries in exercise_muscle_map to appear here.
          {data?.unmapped_exercises && data.unmapped_exercises.length > 0 && (
            <span className="block mt-1 text-[10.5px] text-[var(--text-faint)]">
              Unmapped: {data.unmapped_exercises.slice(0, 6).join(", ")}
              {data.unmapped_exercises.length > 6 && ` +${data.unmapped_exercises.length - 6} more`}
            </span>
          )}
        </p>
      </div>
    );
  }

  // Sort: muscles with targets first, then by descending sets
  const sorted = [...data.muscles].sort((a, b) => {
    const aHasTarget = a.mev != null ? 1 : 0;
    const bHasTarget = b.mev != null ? 1 : 0;
    if (aHasTarget !== bHasTarget) return bHasTarget - aHasTarget;
    return b.weekly_sets - a.weekly_sets;
  });

  const weekLabel = new Date(data.week_start + "T12:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" });

  return (
    <div className="rounded-lg border border-[var(--hairline)] p-4 space-y-3">
      <div className="flex items-baseline justify-between">
        <Eyebrow>Per-muscle volume · wk of {weekLabel}</Eyebrow>
        <span className="inline-flex items-center gap-1.5 text-[10px] text-[var(--text-faint)]">
          <ObsidianMark size={10} />
          RP landmarks
        </span>
      </div>

      <div className="space-y-4">
        {sorted.map((m) => (
          <MuscleBar
            key={m.muscle}
            muscle={m.muscle}
            weekly_sets={m.weekly_sets}
            mev={m.mev}
            mav={m.mav}
            mrv={m.mrv}
          />
        ))}
      </div>

      {data.unmapped_exercises.length > 0 && (
        <div className="flex items-start gap-1.5 pt-2 border-t border-[var(--hairline)]">
          <WarningIcon className="w-3 h-3 text-[var(--text-faint)] mt-0.5 shrink-0" />
          <p className="text-[10px] text-[var(--text-faint)] leading-relaxed">
            Unmapped exercises (not counted): {data.unmapped_exercises.slice(0, 8).join(", ")}
            {data.unmapped_exercises.length > 8 && ` +${data.unmapped_exercises.length - 8} more`}
          </p>
        </div>
      )}

      <p className="text-[10px] text-[var(--text-faint)] leading-relaxed pt-1 border-t border-[var(--hairline)]">
        Below MEV → insufficient stimulus. MEV–MAV → productive growth zone. MAV–MRV → diminishing
        returns, rising injury risk. Above MRV → junk volume.
      </p>
    </div>
  );
}
