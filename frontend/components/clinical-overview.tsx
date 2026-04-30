"use client";

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type ClinicalOverview as ClinicalOverviewData } from "@/lib/api";
import { Eyebrow } from "@/components/ui/metric";

const MED_IMPACT: Record<string, string> = {
  propranolol: "β-blocker — blunts RHR & HRV response",
  escitalopram: "SSRI — may suppress HRV",
  fluoxetine: "SSRI — may suppress HRV",
};

function medImpact(name: string): string | null {
  const lower = name.toLowerCase();
  for (const [key, val] of Object.entries(MED_IMPACT)) {
    if (lower.includes(key)) return val;
  }
  return null;
}

type TLEvent = {
  date: string;
  kind: "med" | "condition" | "lab";
  label: string;
  detail?: string | null;
};

function buildTimeline(d: ClinicalOverviewData | undefined): TLEvent[] {
  if (!d) return [];
  const evts: TLEvent[] = [];
  for (const c of d.conditions) {
    if (c.onset) evts.push({ date: c.onset, kind: "condition", label: c.name, detail: c.status });
  }
  for (const m of d.medications) {
    if (m.started) {
      const impact = medImpact(m.name);
      evts.push({
        date: m.started,
        kind: "med",
        label: m.name.split("(")[0].trim(),
        detail: impact ?? m.dose ?? null,
      });
    }
  }
  for (const l of d.key_labs.slice(0, 6)) {
    if (l.collected_at) {
      evts.push({
        date: l.collected_at,
        kind: "lab",
        label: l.name,
        detail: `${l.value}${l.unit ? ` ${l.unit}` : ""}`,
      });
    }
  }
  evts.sort((a, b) => b.date.localeCompare(a.date));
  return evts;
}

const KIND_COLOR: Record<TLEvent["kind"], string> = {
  med: "var(--chart-line)",
  condition: "var(--neutral)",
  lab: "var(--positive)",
};
const KIND_LABEL: Record<TLEvent["kind"], string> = {
  med: "Medication",
  condition: "Condition",
  lab: "Lab",
};

function fmtDate(s: string): string {
  const d = new Date(s.includes("T") ? s : s + "T00:00:00");
  if (Number.isNaN(d.getTime())) return s.slice(0, 10);
  return d.toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" });
}

export function ClinicalOverview() {
  const { data, isLoading } = useQuery({
    queryKey: ["clinical"],
    queryFn: api.clinicalOverview,
    refetchInterval: 3_600_000,
  });

  const activeMeds = data?.medications.filter((m) => !m.name.toLowerCase().includes("discontinued")) ?? [];
  const activeConditions = data?.conditions.filter((c) => c.status === "active") ?? [];
  const keyLabs = data?.key_labs.slice(0, 8) ?? [];
  const timeline = useMemo(() => buildTimeline(data).slice(0, 12), [data]);

  return (
    <div className="space-y-5">
      <p className="shc-helptext">
        <span className="text-[var(--text-muted)]">How to read this. </span>
        Active conditions, current meds, and recent labs in one place — plus a unified timeline
        so you can see how clinical events line up with biometric trends.
      </p>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="shc-card p-4 space-y-3">
          <Eyebrow>Active conditions</Eyebrow>
          {isLoading ? (
            <div className="h-32 shc-skeleton rounded" />
          ) : activeConditions.length === 0 ? (
            <p className="text-[11px] text-[var(--text-faint)]">None on record</p>
          ) : (
            <ul className="space-y-2">
              {activeConditions.map((c) => (
                <li key={c.name} className="flex items-start gap-2">
                  <span className="w-1.5 h-1.5 rounded-full mt-1.5 flex-shrink-0 bg-[var(--neutral)]" />
                  <div className="min-w-0">
                    <p className="text-[12px] leading-snug text-[var(--text-muted)]">{c.name}</p>
                    {c.onset && (
                      <p className="text-[10px] text-[var(--text-faint)] tabular-nums">since {fmtDate(c.onset)}</p>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="shc-card p-4 space-y-3">
          <Eyebrow>Current medications</Eyebrow>
          {isLoading ? (
            <div className="h-32 shc-skeleton rounded" />
          ) : activeMeds.length === 0 ? (
            <p className="text-[11px] text-[var(--text-faint)]">None on record</p>
          ) : (
            <ul className="space-y-2">
              {activeMeds.slice(0, 8).map((m) => {
                const impact = medImpact(m.name);
                return (
                  <li key={m.name + (m.started ?? "")} className="space-y-0.5">
                    <p className="text-[12px] leading-snug text-[var(--text-muted)]">
                      {m.name.split("(")[0].trim()}
                      {m.dose && (
                        <span className="text-[var(--text-faint)] text-[10.5px] ml-1.5 tabular-nums">{m.dose}</span>
                      )}
                    </p>
                    {impact && <p className="text-[10px] text-[var(--neutral)]">{impact}</p>}
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        <div className="shc-card p-4 space-y-3">
          <Eyebrow>Latest labs</Eyebrow>
          {isLoading ? (
            <div className="h-32 shc-skeleton rounded" />
          ) : keyLabs.length === 0 ? (
            <p className="text-[11px] text-[var(--text-faint)]">No lab data on record</p>
          ) : (
            <ul className="space-y-1.5">
              {keyLabs.map((l) => (
                <li key={l.name + (l.collected_at ?? "")} className="flex items-center justify-between gap-2">
                  <span className="text-[11px] truncate text-[var(--text-dim)]">{l.name}</span>
                  <span className="text-[11px] tabular-nums flex-shrink-0 text-[var(--text-primary)]">
                    {l.value} <span className="text-[var(--text-faint)]">{l.unit ?? ""}</span>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      {/* ── Unified timeline ───────────────────────────────────────────── */}
      <div className="shc-card p-4">
        <div className="flex items-baseline justify-between mb-3">
          <Eyebrow>Clinical timeline</Eyebrow>
          <span className="text-[10px] text-[var(--text-faint)]">
            most recent first · {timeline.length} events
          </span>
        </div>
        {isLoading ? (
          <div className="h-32 shc-skeleton rounded" />
        ) : timeline.length === 0 ? (
          <p className="text-[11px] text-[var(--text-faint)]">No dated clinical events yet.</p>
        ) : (
          <ol className="relative ml-2">
            <span
              aria-hidden
              className="absolute top-1 bottom-1 left-[6px] w-px"
              style={{ background: "var(--hairline)" }}
            />
            {timeline.map((e, i) => (
              <li key={`${e.date}-${e.label}-${i}`} className="relative pl-6 pb-3 last:pb-0">
                <span
                  className="absolute left-[1px] top-[5px] w-[11px] h-[11px] rounded-full border-2"
                  style={{ background: "var(--bg)", borderColor: KIND_COLOR[e.kind] }}
                />
                <div className="flex items-baseline justify-between gap-3">
                  <p className="text-[12px] text-[var(--text-primary)] leading-snug">
                    <span
                      className="text-[9px] uppercase tracking-[0.16em] mr-2"
                      style={{ color: KIND_COLOR[e.kind], fontFamily: "var(--font-orbitron)" }}
                    >
                      {KIND_LABEL[e.kind]}
                    </span>
                    {e.label}
                  </p>
                  <span className="text-[10px] text-[var(--text-faint)] tabular-nums shrink-0">
                    {fmtDate(e.date)}
                  </span>
                </div>
                {e.detail && (
                  <p className="text-[10.5px] text-[var(--text-dim)] mt-0.5 ml-0">{e.detail}</p>
                )}
              </li>
            ))}
          </ol>
        )}
      </div>
    </div>
  );
}
