"use client";

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  api,
  type ClinicalOverview as ClinicalOverviewData,
  type ClinicalRisk,
  type LabPanel,
  type RiskZone,
} from "@/lib/api";
import { Eyebrow } from "@/components/ui/metric";

// ── Zone palette ─────────────────────────────────────────────────────────────

const ZONE_COLOR: Record<RiskZone, string> = {
  optimal: "var(--positive)",
  normal: "var(--positive)",
  near_optimal: "var(--positive)",
  elevated: "var(--neutral)",
  borderline: "var(--neutral)",
  overweight: "var(--neutral)",
  prediabetic: "var(--neutral)",
  stage1: "var(--neutral)",
  high: "var(--negative)",
  stage2: "var(--negative)",
  very_high: "var(--negative)",
  obese: "var(--negative)",
  diabetic: "var(--negative)",
  underweight: "var(--negative)",
};

const ZONE_LABEL: Record<RiskZone, string> = {
  optimal: "Optimal",
  normal: "Normal",
  near_optimal: "Near optimal",
  elevated: "Elevated",
  borderline: "Borderline",
  overweight: "Overweight",
  prediabetic: "Prediabetic",
  stage1: "Stage 1 HTN",
  high: "High",
  stage2: "Stage 2 HTN",
  very_high: "Very high",
  obese: "Obese",
  diabetic: "Diabetic",
  underweight: "Underweight",
};

// ── Helpers ──────────────────────────────────────────────────────────────────

function fmtDate(s: string | null | undefined): string {
  if (!s) return "—";
  const d = new Date(s.includes("T") ? s : s + "T00:00:00");
  if (Number.isNaN(d.getTime())) return s.slice(0, 10);
  return d.toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" });
}

function timeSince(s: string | null | undefined): string {
  if (!s) return "—";
  // Postgres/DuckDB hand back "2026-09-04 15:17:00-07:00" — a space, not a T, and
  // Safari refuses that. Normalise before parsing, and only add a midnight time
  // to a bare date.
  const iso = /^\d{4}-\d{2}-\d{2}$/.test(s) ? `${s}T00:00:00` : s.replace(" ", "T");
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const days = Math.floor((Date.now() - d.getTime()) / 86_400_000);
  if (days < 30) return `${days}d ago`;
  const mo = Math.floor(days / 30);
  if (mo < 24) return `${mo}mo ago`;
  return `${Math.floor(mo / 12)}y ago`;
}

// ── Cardiometabolic risk strip ──────────────────────────────────────────────

function RiskTile({ kpi }: { kpi: ClinicalRisk["cardiometabolic"][number] }) {
  const color = ZONE_COLOR[kpi.zone];
  return (
    <div
      className="rounded-[var(--r-md)] p-3 border"
      style={{
        background: `linear-gradient(135deg, ${color}10 0%, transparent 80%)`,
        borderColor: `${color}30`,
      }}
    >
      <p
        className="text-[9px] uppercase tracking-[0.18em] text-[var(--text-dim)] mb-1"
        style={{ fontFamily: "var(--font-orbitron)" }}
      >
        {kpi.label}
      </p>
      <div className="flex items-baseline gap-1">
        <span
          className="text-[28px] leading-none font-light tabular-nums"
          style={{ fontFamily: "var(--font-orbitron)", color }}
        >
          {kpi.value}
        </span>
        <span className="text-[10.5px] text-[var(--text-faint)]">{kpi.unit}</span>
      </div>
      <div className="flex items-center gap-1.5 mt-1.5">
        <span
          className="text-[9px] uppercase tracking-[0.14em] px-1.5 py-px rounded-sm border"
          style={{ color, borderColor: `${color}50`, background: `${color}10` }}
        >
          {ZONE_LABEL[kpi.zone]}
        </span>
        <span className="text-[9.5px] text-[var(--text-faint)] tabular-nums">{timeSince(kpi.ts)}</span>
      </div>
    </div>
  );
}

function CardiometabolicStrip({ risk }: { risk: ClinicalRisk | undefined }) {
  if (!risk?.cardiometabolic.length) return null;
  return (
    <div>
      <div className="flex items-baseline justify-between mb-2">
        <Eyebrow>Cardiometabolic risk</Eyebrow>
        <span className="text-[9.5px] text-[var(--text-faint)]">latest snapshot</span>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        {risk.cardiometabolic.map((kpi) => <RiskTile key={kpi.key} kpi={kpi} />)}
      </div>
    </div>
  );
}

// ── Labs table with H/L flags + sparkline ───────────────────────────────────

/**
 * Where one result sits inside its own reference interval.
 *
 * This column used to be a sparkline, which was the wrong mark for the data:
 * 46 of the 52 labs on record have exactly one draw, so 88% of the column
 * rendered an em-dash. A single result still carries the clinically useful
 * comparison — value against interval — and that is what this draws.
 *
 * The domain is the reference interval padded by 55% on each side, so a normal
 * result sits in the middle two-thirds and an abnormal one visibly breaks the
 * band without ever leaving the track. Out-of-domain extremes clamp to the edge
 * and keep their flag colour, so "high" never reads as "just inside".
 */
function RangeTrack({
  value,
  low,
  high,
  flag,
  unit,
}: {
  value: number;
  low: number | null;
  high: number | null;
  flag: string | null;
  unit: string | null;
}) {
  if (low == null && high == null) {
    return <span className="text-[9px] text-[var(--text-faint)]">—</span>;
  }

  // One-sided intervals ("≤239", "≥40") get an implied opposite bound so the
  // band still has width to draw; it is derived from the stated bound, never
  // from the measured value, so the marker position stays meaningful.
  const lo = low ?? (high != null ? high - Math.abs(high) * 0.6 : 0);
  const hi = high ?? (low != null ? low + Math.abs(low) * 0.6 : 1);
  const span = hi - lo || Math.abs(hi) || 1;
  const dMin = lo - span * 0.55;
  const dMax = hi + span * 0.55;
  const pct = (v: number) => Math.max(1.5, Math.min(98.5, ((v - dMin) / (dMax - dMin)) * 100));

  const color =
    flag === "H" ? "var(--negative)" : flag === "L" ? "var(--neutral)" : "var(--positive)";
  const bandLeft = pct(lo);
  const bandRight = pct(hi);

  return (
    <div
      className="relative h-[7px] w-[76px] inline-block rounded-full align-middle"
      style={{ background: "var(--hairline)" }}
      title={`${value}${unit ? " " + unit : ""} — reference ${low ?? "−∞"}–${high ?? "∞"}`}
    >
      <div
        className="absolute inset-y-0 rounded-full"
        style={{
          left: `${bandLeft}%`,
          width: `${Math.max(2, bandRight - bandLeft)}%`,
          background: "var(--positive)",
          opacity: 0.22,
        }}
      />
      <div
        className="absolute rounded-full"
        style={{
          left: `${pct(value)}%`,
          top: -2,
          bottom: -2,
          width: 2.5,
          marginLeft: -1.25,
          background: color,
          boxShadow: `0 0 0 1.5px var(--card)`,
        }}
      />
    </div>
  );
}

function LabsTable({
  data,
  overdue,
}: {
  data: ClinicalOverviewData | undefined;
  overdue: ClinicalRisk["overdue_labs"];
}) {
  const overdueByName = useMemo(() => {
    const m: Record<string, ClinicalRisk["overdue_labs"][number]> = {};
    for (const o of overdue) m[o.name] = o;
    return m;
  }, [overdue]);

  if (!data?.key_labs.length) {
    return <p className="text-[11px] text-[var(--text-faint)]">No labs on record yet — run <code>shc ingest-clinical-profile</code>.</p>;
  }

  return (
    <div className="rounded-lg border border-[var(--hairline)] overflow-hidden">
      <table className="w-full text-[11.5px]">
        <thead className="text-[9.5px] text-[var(--text-faint)] uppercase tracking-wider" style={{ borderBottom: "1px solid var(--hairline)" }}>
          <tr>
            <th className="px-3 py-2 text-left font-normal">Lab</th>
            <th className="px-3 py-2 text-right font-normal">Value</th>
            <th className="px-3 py-2 text-right font-normal">Range</th>
            <th className="px-3 py-2 text-right font-normal">In range</th>
            <th className="px-3 py-2 text-right font-normal">Drawn</th>
          </tr>
        </thead>
        <tbody>
          {data.key_labs.map((l) => {
            const flagColor =
              l.flag === "H" ? "var(--negative)" : l.flag === "L" ? "var(--neutral)" : "var(--positive)";
            const overdueInfo = overdueByName[l.name];
            const range =
              l.ref_low != null && l.ref_high != null
                ? `${l.ref_low}–${l.ref_high}`
                : l.ref_high != null
                  ? `≤${l.ref_high}`
                  : l.ref_low != null
                    ? `≥${l.ref_low}`
                    : "—";
            return (
              <tr key={l.name} className="border-b border-[var(--hairline)] last:border-b-0 hover:bg-[oklch(1_0_0/0.02)]">
                <td className="px-3 py-2 text-[var(--text-muted)]">
                  <div className="flex items-center gap-1.5">
                    <span>{l.name}</span>
                    {overdueInfo && (
                      <span
                        className="text-[8.5px] uppercase tracking-[0.12em] px-1 rounded-sm"
                        style={{
                          background: "var(--negative-soft)",
                          color: "var(--negative)",
                          fontFamily: "var(--font-orbitron)",
                        }}
                        title={`Last drawn ${overdueInfo.months_since.toFixed(1)}mo ago — recommended every ${overdueInfo.interval_months}mo`}
                      >
                        Overdue
                      </span>
                    )}
                  </div>
                </td>
                <td className="px-3 py-2 text-right tabular-nums">
                  <span style={{ color: flagColor, fontWeight: l.flag ? 500 : 400 }}>
                    {l.value}
                  </span>
                  <span className="text-[var(--text-faint)] text-[9.5px] ml-0.5">{l.unit}</span>
                  {l.flag && (
                    <span
                      className="ml-1 text-[8.5px] font-medium px-1 rounded-sm"
                      style={{ background: `${flagColor}25`, color: flagColor }}
                    >
                      {l.flag}
                    </span>
                  )}
                </td>
                <td className="px-3 py-2 text-right text-[var(--text-faint)] tabular-nums">{range}</td>
                <td className="px-3 py-2 text-right">
                  <RangeTrack
                    value={l.value}
                    low={l.ref_low}
                    high={l.ref_high}
                    flag={l.flag}
                    unit={l.unit}
                  />
                </td>
                <td className="px-3 py-2 text-right text-[var(--text-faint)] tabular-nums whitespace-nowrap">
                  {timeSince(l.collected_at)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ── Panel results (qualitative + numeric, grouped by order) ─────────────────

function PanelsList({ panels }: { panels: LabPanel[] }) {
  return (
    <div className="space-y-3">
      {panels.map((p) => {
        const abnormalCount = p.results.filter((r) => r.is_abnormal).length;
        return (
          <details
            key={`${p.panel}-${p.collected_at}`}
            className="rounded-lg border border-[var(--hairline)] overflow-hidden group"
            open={abnormalCount > 0}
          >
            <summary className="flex items-baseline justify-between gap-3 px-3 py-2 cursor-pointer select-none hover:bg-[oklch(1_0_0/0.02)]">
              <div className="flex items-baseline gap-2">
                <span className="text-[12px] text-[var(--text-primary)]">{p.panel}</span>
                {abnormalCount > 0 && (
                  <span
                    className="text-[8.5px] uppercase tracking-[0.12em] px-1 rounded-sm"
                    style={{
                      background: "var(--negative-soft)",
                      color: "var(--negative)",
                      fontFamily: "var(--font-orbitron)",
                    }}
                  >
                    {abnormalCount} abnormal
                  </span>
                )}
              </div>
              <span className="text-[10px] text-[var(--text-faint)] tabular-nums">
                {fmtDate(p.collected_at)} · {p.results.length} results
              </span>
            </summary>
            <table className="w-full text-[11.5px]" style={{ borderTop: "1px solid var(--hairline)" }}>
              <thead className="text-[9.5px] text-[var(--text-faint)] uppercase tracking-wider">
                <tr>
                  <th className="px-3 py-1.5 text-left font-normal">Test</th>
                  <th className="px-3 py-1.5 text-right font-normal">Value</th>
                  <th className="px-3 py-1.5 text-right font-normal">Reference</th>
                </tr>
              </thead>
              <tbody>
                {p.results.map((r) => {
                  const range = r.ref_text
                    ? r.ref_text
                    : r.ref_low != null && r.ref_high != null
                      ? `${r.ref_low}–${r.ref_high}`
                      : r.ref_high != null
                        ? `≤${r.ref_high}`
                        : r.ref_low != null
                          ? `≥${r.ref_low}`
                          : "—";
                  const valueColor = r.is_abnormal ? "var(--negative)" : "var(--text-primary)";
                  return (
                    <tr key={r.name} className="border-t border-[var(--hairline)]">
                      <td className="px-3 py-1.5 text-[var(--text-muted)]">{r.name}</td>
                      <td className="px-3 py-1.5 text-right tabular-nums">
                        <span style={{ color: valueColor, fontWeight: r.is_abnormal ? 500 : 400 }}>
                          {r.display}
                        </span>
                        {r.unit && (
                          <span className="text-[var(--text-faint)] text-[9.5px] ml-0.5">{r.unit}</span>
                        )}
                        {r.is_abnormal && (
                          <span
                            className="ml-1 text-[8.5px] font-medium px-1 rounded-sm"
                            style={{ background: "var(--negative-soft)", color: "var(--negative)" }}
                          >
                            ABN
                          </span>
                        )}
                      </td>
                      <td className="px-3 py-1.5 text-right text-[var(--text-faint)] tabular-nums">{range}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </details>
        );
      })}
    </div>
  );
}

// ── Medications with safety advisories ──────────────────────────────────────

function MedicationsCard({
  data,
  risk,
}: {
  data: ClinicalOverviewData | undefined;
  risk: ClinicalRisk | undefined;
}) {
  const advisoriesByMed = useMemo(() => {
    const m: Record<string, ClinicalRisk["med_advisories"]> = {};
    for (const a of risk?.med_advisories ?? []) {
      m[a.med] = [...(m[a.med] ?? []), a];
    }
    return m;
  }, [risk]);

  const onsetByMed = useMemo(() => {
    const m: Record<string, ClinicalRisk["onset_windows"][number]> = {};
    for (const o of risk?.onset_windows ?? []) m[o.med] = o;
    return m;
  }, [risk]);

  return (
    <div className="space-y-3">
      <Eyebrow>Current medications</Eyebrow>
      {!data ? (
        <div className="h-32 shc-skeleton rounded" />
      ) : data.medications.length === 0 ? (
        <p className="text-[11px] text-[var(--text-faint)]">None on record</p>
      ) : (
        <ul className="space-y-3">
          {data.medications.map((m) => {
            const display = m.name.split("(")[0].trim();
            const advisories = advisoriesByMed[display] ?? [];
            const onset = onsetByMed[display];
            return (
              <li
                key={m.name + (m.started ?? "")}
                className="rounded-md border p-2.5"
                style={{ borderColor: "var(--hairline)", background: "oklch(1 0 0 / 0.015)" }}
              >
                <div className="flex items-baseline justify-between gap-2">
                  <p className="text-[12px] text-[var(--text-primary)] leading-snug">
                    <span className="font-medium">{display}</span>
                    {m.dose && (
                      <span className="text-[var(--text-faint)] text-[10.5px] ml-1.5 tabular-nums">{m.dose}</span>
                    )}
                  </p>
                  {m.started && (
                    <span className="text-[9.5px] text-[var(--text-faint)] tabular-nums shrink-0">
                      {timeSince(m.started)}
                    </span>
                  )}
                </div>
                {m.frequency && (
                  <p className="text-[10.5px] text-[var(--text-dim)] mt-0.5">{m.frequency}</p>
                )}
                {onset && (
                  <p
                    className="text-[10px] mt-1.5 inline-block px-1.5 py-px rounded-sm"
                    style={{
                      background: onset.phase === "onset" ? "oklch(0.78 0.15 85 / 0.10)" : "oklch(0.72 0.18 145 / 0.08)",
                      color: onset.phase === "onset" ? "var(--neutral)" : "var(--positive)",
                    }}
                  >
                    {onset.phase === "onset"
                      ? `Onset window · day ${onset.days_since_start} of ~${Math.min(28, onset.full_effect_days)}`
                      : onset.phase === "active"
                        ? `Active · ${onset.days_since_start}d in, full effect ~${onset.full_effect_days}d`
                        : `Established · ${(onset.days_since_start / 365).toFixed(1)}y on therapy`}
                  </p>
                )}
                {advisories.map((a, i) => (
                  <p
                    key={i}
                    className="text-[10.5px] mt-1.5 leading-snug px-2 py-1 rounded-sm border-l-2"
                    style={{
                      borderColor: a.severity === "warning" ? "var(--negative)" : "var(--neutral)",
                      background: a.severity === "warning" ? "var(--negative-soft)" : "oklch(1 0 0 / 0.025)",
                      color: a.severity === "warning" ? "var(--negative)" : "var(--text-muted)",
                    }}
                  >
                    <span className="font-medium uppercase tracking-wider text-[9px] mr-1">
                      {a.severity === "warning" ? "Caution" : "Note"}
                    </span>
                    {a.text}
                  </p>
                ))}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

// ── Conditions card ──────────────────────────────────────────────────────────

function ConditionsCard({ data }: { data: ClinicalOverviewData | undefined }) {
  const active = data?.conditions.filter((c) => c.status !== "resolved") ?? [];
  return (
    <div className="space-y-3">
      <Eyebrow>Active conditions</Eyebrow>
      {!data ? (
        <div className="h-32 shc-skeleton rounded" />
      ) : active.length === 0 ? (
        <p className="text-[11px] text-[var(--text-faint)]">None on record</p>
      ) : (
        <ul className="space-y-2">
          {active.map((c) => (
            <li key={c.name + (c.onset ?? "")} className="flex items-start gap-2">
              <span className="w-1.5 h-1.5 rounded-full mt-1.5 flex-shrink-0 bg-[var(--neutral)]" />
              <div className="min-w-0 flex-1">
                <div className="flex items-baseline justify-between gap-2">
                  <p className="text-[12px] leading-snug text-[var(--text-muted)]">{c.name}</p>
                  {c.icd10 && (
                    <span className="text-[9px] text-[var(--text-faint)] tabular-nums shrink-0 font-mono">
                      {c.icd10}
                    </span>
                  )}
                </div>
                {c.onset && (
                  <p className="text-[10px] text-[var(--text-faint)] tabular-nums">since {fmtDate(c.onset)}</p>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// ── Care gaps card ──────────────────────────────────────────────────────────

function CareGapsCard({ risk }: { risk: ClinicalRisk | undefined }) {
  const gaps = risk?.overdue_labs ?? [];
  if (gaps.length === 0) return null;
  return (
    <div
      className="shc-card p-5 space-y-2.5"
      style={{ borderColor: "var(--negative)40" }}
    >
      <div className="flex items-baseline justify-between">
        <Eyebrow>
          <span style={{ color: "var(--negative)" }}>Care gaps</span>
        </Eyebrow>
        <span className="text-[9.5px] text-[var(--text-faint)]">{gaps.length} overdue</span>
      </div>
      <ul className="space-y-1.5">
        {gaps.map((g) => (
          <li key={g.name} className="text-[11.5px] flex items-baseline justify-between gap-2">
            <div className="min-w-0">
              <span className="text-[var(--text-muted)]">{g.name}</span>
              <span className="text-[9.5px] text-[var(--text-faint)] ml-2 tabular-nums">
                last {g.months_since.toFixed(1)}mo · interval {g.interval_months}mo
              </span>
            </div>
            <span className="text-[10.5px] tabular-nums" style={{ color: "var(--negative)" }}>
              +{Math.round(g.days_overdue / 30)}mo overdue
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

// ── Timeline (kept from prior design, simplified) ───────────────────────────

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
    if (m.started)
      evts.push({
        date: m.started,
        kind: "med",
        label: m.name.split("(")[0].trim(),
        detail: m.dose,
      });
  }
  for (const l of d.key_labs.slice(0, 8)) {
    if (l.collected_at)
      evts.push({
        date: l.collected_at,
        kind: "lab",
        label: l.name,
        detail: `${l.value}${l.unit ? ` ${l.unit}` : ""}${l.flag ? ` (${l.flag})` : ""}`,
      });
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

// ── Main pane ────────────────────────────────────────────────────────────────

export function ClinicalOverview() {
  const overviewQ = useQuery({
    queryKey: ["clinical"],
    queryFn: api.clinicalOverview,
    refetchInterval: 3_600_000,
  });
  const riskQ = useQuery({
    queryKey: ["clinical-risk"],
    queryFn: api.clinicalRisk,
    refetchInterval: 3_600_000,
  });

  const data = overviewQ.data;
  const risk = riskQ.data;
  const timeline = useMemo(() => buildTimeline(data).slice(0, 14), [data]);

  return (
    <div className="space-y-5">
      <CardiometabolicStrip risk={risk} />

      <CareGapsCard risk={risk} />

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="shc-card p-5">
          <ConditionsCard data={data} />
        </div>
        <div className="shc-card p-5">
          <MedicationsCard data={data} risk={risk} />
        </div>
      </div>

      <div className="shc-card p-5 space-y-3">
        <div className="flex items-baseline justify-between">
          <Eyebrow>Recent labs</Eyebrow>
          <span className="text-[10px] text-[var(--text-faint)]">H/L flags vs reference range</span>
        </div>
        <LabsTable data={data} overdue={risk?.overdue_labs ?? []} />
      </div>

      {data?.panels && data.panels.length > 0 && (
        <div className="shc-card p-5 space-y-3">
          <div className="flex items-baseline justify-between">
            <Eyebrow>Panel results</Eyebrow>
            <span className="text-[10px] text-[var(--text-faint)]">qualitative + numeric, grouped by order</span>
          </div>
          <PanelsList panels={data.panels} />
        </div>
      )}

      <div className="shc-card p-5">
        <div className="flex items-baseline justify-between mb-3">
          <Eyebrow>Clinical timeline</Eyebrow>
          <span className="text-[10px] text-[var(--text-faint)]">
            most recent first · {timeline.length} events
          </span>
        </div>
        {timeline.length === 0 ? (
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
                  <p className="text-[10.5px] text-[var(--text-dim)] mt-0.5">{e.detail}</p>
                )}
              </li>
            ))}
          </ol>
        )}
      </div>
    </div>
  );
}
