"use client";

import { useState } from "react";
import Model from "react-body-highlighter";
import type { IMuscleStats } from "react-body-highlighter";

export type Soreness = Record<string, number>;

const SEV_COLORS = [
  "rgba(245,200,80,0.90)",   // mild    — amber
  "rgba(240,130,50,0.95)",   // moderate — orange
  "rgba(220,60,60,1.00)",    // acute    — red
];
const SEV_LABEL = ["", "mild", "moderate", "acute"];

// Maps backend muscle keys → react-body-highlighter Muscle strings.
const TO_LIB: Record<string, string[]> = {
  chest:       ["chest"],
  biceps:      ["biceps"],
  triceps:     ["triceps"],
  front_delts: ["front-deltoids"],
  side_delts:  ["front-deltoids"],
  rear_delts:  ["back-deltoids"],
  abs:         ["abs"],
  obliques:    ["obliques"],
  quads:       ["quadriceps"],
  adductors:   ["adductor"],
  calves:      ["calves"],
  traps:       ["trapezius"],
  traps_mid:   ["upper-back"],
  lats:        ["upper-back"],
  mid_back:    ["upper-back"],
  lower_back:  ["lower-back"],
  glutes:      ["gluteal"],
  hamstrings:  ["hamstring"],
  forearms:    ["forearm"],
};

// Maps library muscle string back to the canonical backend key we track.
const FROM_LIB: Record<string, string> = {
  chest:           "chest",
  biceps:          "biceps",
  triceps:         "triceps",
  "front-deltoids": "front_delts",
  "back-deltoids":  "rear_delts",
  abs:             "abs",
  obliques:        "obliques",
  quadriceps:      "quads",
  adductor:        "adductors",
  calves:          "calves",
  trapezius:       "traps",
  "upper-back":    "lats",
  "lower-back":    "lower_back",
  gluteal:         "glutes",
  hamstring:       "hamstrings",
  forearm:         "forearms",
};

function buildData(soreness: Soreness) {
  // Group backend keys by severity (1=mild, 2=moderate, 3=acute).
  const groups: string[][] = [[], [], []];
  for (const [key, sev] of Object.entries(soreness)) {
    if (sev < 1 || sev > 3) continue;
    const libMuscles = TO_LIB[key];
    if (libMuscles) {
      for (const m of libMuscles) {
        if (!groups[sev - 1].includes(m)) groups[sev - 1].push(m);
      }
    }
  }
  return groups
    .map((muscles, i) =>
      muscles.length ? { name: `sev${i + 1}`, muscles, frequency: i + 1 } : null,
    )
    .filter(Boolean) as { name: string; muscles: string[]; frequency: number }[];
}

export function BodyDiagram({
  value,
  onChange,
}: {
  value: Soreness;
  onChange: (next: Soreness) => void;
}) {
  const [view, setView] = useState<"front" | "back">("front");

  function handleClick(stats: IMuscleStats) {
    const key = FROM_LIB[stats.muscle];
    if (!key) return;
    const cur = value[key] ?? 0;
    const next = (cur + 1) % 4;
    const out = { ...value };
    if (next === 0) delete out[key];
    else out[key] = next;
    onChange(out);
  }

  const data = buildData(value);
  const flagged = Object.values(value).filter((s) => s > 0).length;
  const flaggedEntries = Object.entries(value).filter(([, s]) => s > 0).sort(([, a], [, b]) => b - a);

  return (
    <div className="space-y-2">
      <div className="flex items-baseline justify-between">
        <span className="text-[11.5px] text-[var(--text-muted)]">Muscle soreness</span>
        <div className="flex items-center gap-2">
          {flagged > 0 && (
            <span className="text-[10px] text-[var(--text-faint)] tabular-nums">
              {flagged} flagged
            </span>
          )}
          <div className="inline-flex rounded-full border border-[var(--hairline-strong)] overflow-hidden">
            {(["front", "back"] as const).map((v) => {
              const active = view === v;
              return (
                <button
                  key={v}
                  type="button"
                  onClick={() => setView(v)}
                  className="px-2.5 py-0.5 text-[10.5px] font-medium transition-colors capitalize"
                  style={{
                    background: active ? "var(--text-primary)" : "transparent",
                    color: active ? "var(--bg)" : "var(--text-muted)",
                  }}
                >
                  {v}
                </button>
              );
            })}
          </div>
        </div>
      </div>

      <div className="flex items-start gap-4">
        <div style={{ width: 160, flexShrink: 0 }}>
          <Model
            data={data}
            type={view === "front" ? "anterior" : "posterior"}
            bodyColor="oklch(0.42 0.04 240 / 0.85)"
            highlightedColors={SEV_COLORS}
            onClick={handleClick}
            style={{ width: "100%", cursor: "pointer" }}
            svgStyle={{ width: "100%", height: "auto" }}
          />
        </div>

        <div className="flex-1 min-w-0 space-y-2">
          <div className="text-[11px] text-[var(--text-muted)] leading-relaxed">
            Tap a muscle to cycle:{" "}
            <span className="text-[var(--text-primary)]">none → mild → moderate → acute</span>.
            Acute soreness will forbid that muscle group in tomorrow's plan.
          </div>
          <div className="space-y-1">
            {flaggedEntries.map(([k, s]) => (
              <div key={k} className="flex items-center justify-between text-[12px] tabular-nums">
                <span className="text-[var(--text-primary)] capitalize">
                  {k.replace(/_/g, " ")}
                </span>
                <span
                  className="px-2 py-0.5 rounded-sm text-[11px] font-medium"
                  style={{
                    background: SEV_COLORS[s - 1] ?? "transparent",
                    color: "oklch(1 0 0)",
                    border: `1px solid ${SEV_COLORS[s - 1] ?? "transparent"}`,
                  }}
                >
                  {SEV_LABEL[s]}
                </span>
              </div>
            ))}
            {flagged === 0 && (
              <div className="text-[11.5px] text-[var(--text-muted)] italic">
                No soreness flagged.
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
