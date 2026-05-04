"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

const MED_IMPACT: Record<string, string> = {
  "Propranolol": "β-blocker — may suppress RHR",
  "Escitalopram": "SSRI — may suppress HRV",
  "FLUoxetine": "SSRI — may suppress HRV",
  "Fluoxetine": "SSRI — may suppress HRV",
};

function medImpact(name: string): string | null {
  for (const [key, val] of Object.entries(MED_IMPACT)) {
    if (name.toLowerCase().includes(key.toLowerCase())) return val;
  }
  return null;
}

export function ClinicalOverview() {
  const { data, isLoading } = useQuery({
    queryKey: ["clinical"],
    queryFn: api.clinicalOverview,
    refetchInterval: 3_600_000,
  });

  const activeMeds = data?.medications.filter(m => !m.name.toLowerCase().includes("discontinued")) ?? [];
  const activeConditions = data?.conditions.filter(c => c.status === "active") ?? [];
  const keyLabs = data?.key_labs.slice(0, 8) ?? [];

  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
      {/* Conditions */}
      <div className="rounded-xl border p-5" style={{ background: "oklch(0.15 0 0)", borderColor: "oklch(1 0 0 / 0.07)" }}>
        <h3 className="text-xs uppercase tracking-wider mb-3" style={{ color: "oklch(0.5 0 0)" }}>Active Conditions</h3>
        {isLoading ? <div className="h-32 animate-pulse rounded" style={{ background: "oklch(0.2 0 0)" }} /> : (
          <div className="space-y-2">
            {activeConditions.map(c => (
              <div key={c.name} className="flex items-start gap-2">
                <div className="w-1.5 h-1.5 rounded-full mt-1.5 flex-shrink-0" style={{ background: "oklch(0.65 0.18 75)" }} />
                <div>
                  <p className="text-xs leading-snug" style={{ color: "oklch(0.78 0 0)" }}>{c.name}</p>
                  {c.onset && <p className="text-[10px]" style={{ color: "oklch(0.4 0 0)" }}>{c.onset.slice(0, 7)}</p>}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Medications */}
      <div className="rounded-xl border p-5" style={{ background: "oklch(0.15 0 0)", borderColor: "oklch(1 0 0 / 0.07)" }}>
        <h3 className="text-xs uppercase tracking-wider mb-3" style={{ color: "oklch(0.5 0 0)" }}>Current Medications</h3>
        {isLoading ? <div className="h-32 animate-pulse rounded" style={{ background: "oklch(0.2 0 0)" }} /> : (
          <div className="space-y-2">
            {activeMeds.slice(0, 8).map(m => {
              const impact = medImpact(m.name);
              return (
                <div key={m.name + m.started} className="flex flex-col gap-0.5">
                  <p className="text-xs leading-snug" style={{ color: "oklch(0.78 0 0)" }}>{m.name.split("(")[0].trim()}</p>
                  {impact && (
                    <p className="text-[10px]" style={{ color: "oklch(0.55 0.12 75)" }}>{impact}</p>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Key Labs */}
      <div className="rounded-xl border p-5" style={{ background: "oklch(0.15 0 0)", borderColor: "oklch(1 0 0 / 0.07)" }}>
        <h3 className="text-xs uppercase tracking-wider mb-3" style={{ color: "oklch(0.5 0 0)" }}>Key Labs</h3>
        {isLoading ? <div className="h-32 animate-pulse rounded" style={{ background: "oklch(0.2 0 0)" }} /> : (
          <div className="space-y-2">
            {keyLabs.map(l => (
              <div key={l.name + l.collected_at} className="flex items-center justify-between">
                <span className="text-xs truncate mr-2" style={{ color: "oklch(0.65 0 0)" }}>{l.name}</span>
                <span className="text-xs font-mono tabular-nums flex-shrink-0" style={{ color: "oklch(0.88 0 0)" }}>
                  {l.value} <span style={{ color: "oklch(0.4 0 0)" }}>{l.unit ?? ""}</span>
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
