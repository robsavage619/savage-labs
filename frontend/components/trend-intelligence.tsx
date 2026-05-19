"use client";

import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { WarningIcon } from "@/components/ui/icons";
import {
  Area,
  ComposedChart,
  Line,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "@/lib/api";
import { Eyebrow } from "@/components/ui/metric";
import { ObsidianMark } from "@/components/obsidian-badge";
import { CorrelationCards } from "@/components/correlation-cards";
import { ClinicalOverview } from "@/components/clinical-overview";
import { BodyPane } from "@/components/body-panel";
import { PatternsPane } from "@/components/patterns-pane";
import { PerformanceCurvePane } from "@/components/performance-curve";
import { PickleballPane } from "@/components/pickleball-panel";
import { MuscleVolumePanel } from "@/components/muscle-volume-panel";

const TABS = ["Recovery", "Body", "Patterns", "Insights", "Performance", "Sport", "Clinical"] as const;
type Tab = (typeof TABS)[number];

// ──────────────────────────────────────────────────────────────────────────
// RECOVERY TAB
// ──────────────────────────────────────────────────────────────────────────

function dedupeByDate<T extends { date: string }>(rows: T[]): T[] {
  // Backend trend endpoints can return multiple rows per date when joined.
  // Keep the last occurrence per ISO date and sort ascending.
  const byDate = new Map<string, T>();
  for (const r of rows) byDate.set(r.date, r);
  return Array.from(byDate.values()).sort((a, b) => a.date.localeCompare(b.date));
}

function RecoveryTrendPane() {
  const trend = useQuery({ queryKey: ["recovery-trend-90"], queryFn: () => api.recoveryTrend(90) });
  const hrv = useQuery({ queryKey: ["hrv-90"], queryFn: () => api.hrvTrend(90) });
  const stats = useQuery({ queryKey: ["stats-summary"], queryFn: api.statsSummary });

  const trendRows = useMemo(() => dedupeByDate(trend.data ?? []), [trend.data]);
  const hrvRows = useMemo(() => dedupeByDate(hrv.data ?? []), [hrv.data]);

  return (
    <div className="space-y-6">
      <p className="shc-helptext">
        <span className="text-[var(--text-muted)]">How to read this. </span>
        The heatmap reveals weekly patterns — Mondays vs weekends, illness weeks, deload weeks.
        The HRV band shows your individual normal range. The alarm strip flags days where your
        body's three pre-illness signals (RHR rise, temp rise, HRV drop) coincide.
      </p>

      <RecoveryHeatmap data={trendRows} />
      <HRVTrendCard data={hrvRows} baseline={stats.data?.hrv.baseline_28d ?? null} />
      <PreIllnessStrip data={trendRows} hrv={hrvRows} />
      <MonthlyAverages data={trendRows} />
    </div>
  );
}

function RecoveryHeatmap({
  data,
}: {
  data: { date: string; score: number; hrv: number; rhr: number }[];
}) {
  // Build a 13×7 grid (13 weeks × 7 weekdays). Most-recent on the right.
  // Each cell is { date, score } or null. We anchor the right column to today's
  // weekday so the bottom-right cell == today.
  const grid = useMemo(() => buildHeatmapGrid(data, 13), [data]);
  const today = new Date().toISOString().slice(0, 10);
  const todayCell = data.find((d) => d.date === today);

  return (
    <div>
      <div className="flex items-baseline justify-between mb-2">
        <Eyebrow>Recovery · 90d heatmap</Eyebrow>
        <div className="flex items-center gap-3 text-[10px] text-[var(--text-faint)]">
          {todayCell && (
            <span className="tabular-nums">
              today <span className="text-[var(--text-muted)]">{todayCell.score.toFixed(0)}</span>
            </span>
          )}
          <HeatmapLegend />
        </div>
      </div>
      <div className="flex gap-[3px] items-start">
        {/* Weekday labels */}
        <div className="flex flex-col gap-[3px] pr-1.5 pt-[1px]">
          {["M", "T", "W", "T", "F", "S", "S"].map((d, i) => (
            <span key={i} className="text-[8.5px] text-[var(--text-faint)] h-[14px] leading-[14px]">
              {d}
            </span>
          ))}
        </div>
        <div className="flex gap-[3px] flex-1">
          {grid.map((week, wi) => (
            <div key={wi} className="flex flex-col gap-[3px] flex-1">
              {week.map((cell, di) => (
                <HeatmapCell key={di} cell={cell} />
              ))}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function HeatmapCell({ cell }: { cell: { date: string; score: number } | null }) {
  if (!cell) {
    return (
      <div
        className="h-[14px] w-full rounded-[2px]"
        style={{ background: "transparent", border: "1px dashed var(--hairline)" }}
      />
    );
  }
  const { fill, ring } = recoveryColor(cell.score);
  const sub34 = cell.score < 34;
  return (
    <div
      title={`${cell.date} · recovery ${cell.score.toFixed(0)}`}
      className="h-[14px] w-full rounded-[2px] transition-transform hover:scale-110"
      style={{
        background: fill,
        boxShadow: sub34 ? `inset 0 0 0 1px ${ring}` : undefined,
      }}
    />
  );
}

function HeatmapLegend() {
  return (
    <div className="flex items-center gap-1">
      <span className="text-[var(--text-faint)]">low</span>
      {[10, 30, 50, 70, 90].map((s) => (
        <div
          key={s}
          className="h-[10px] w-[10px] rounded-[2px]"
          style={{ background: recoveryColor(s).fill }}
        />
      ))}
      <span className="text-[var(--text-faint)]">high</span>
    </div>
  );
}

function recoveryColor(score: number): { fill: string; ring: string } {
  // Below 34 = red, 34-66 = yellow, 67+ = green. Saturation scales with magnitude.
  if (score < 34) {
    const t = Math.max(0.35, score / 34);
    return { fill: `oklch(0.42 0.18 25 / ${0.55 + (1 - t) * 0.4})`, ring: "oklch(0.65 0.22 25)" };
  }
  if (score < 67) {
    const t = (score - 34) / 33;
    return { fill: `oklch(${0.55 + t * 0.05} 0.14 80 / ${0.45 + t * 0.25})`, ring: "oklch(0.7 0.18 80)" };
  }
  const t = Math.min(1, (score - 67) / 33);
  return { fill: `oklch(${0.62 + t * 0.08} 0.16 145 / ${0.5 + t * 0.4})`, ring: "oklch(0.72 0.2 145)" };
}

function buildHeatmapGrid(
  data: { date: string; score: number }[],
  weeks: number,
): (({ date: string; score: number } | null)[])[] {
  // Map date → score for fast lookup.
  const byDate = new Map(data.map((d) => [d.date, d]));
  const today = new Date();
  // Walk backwards from today's weekday filling the rightmost column down.
  const totalDays = weeks * 7;
  const cells: ({ date: string; score: number } | null)[] = [];
  for (let i = totalDays - 1; i >= 0; i--) {
    const d = new Date(today);
    d.setDate(today.getDate() - i);
    const iso = d.toISOString().slice(0, 10);
    const hit = byDate.get(iso);
    cells.push(hit ? { date: hit.date, score: hit.score } : null);
  }
  // Reshape to [weeks][7] where row 0 = Monday, row 6 = Sunday.
  // Determine the column the leftmost day belongs to using its weekday.
  const grid: ({ date: string; score: number } | null)[][] = Array.from(
    { length: weeks },
    () => Array(7).fill(null),
  );
  for (let i = 0; i < cells.length; i++) {
    const d = new Date(today);
    d.setDate(today.getDate() - (cells.length - 1 - i));
    const dayIdx = (d.getDay() + 6) % 7; // Mon = 0
    const weekIdx = Math.floor(i / 7);
    if (weekIdx < weeks && grid[weekIdx]) grid[weekIdx][dayIdx] = cells[i];
  }
  return grid;
}

function HRVTooltip({ active, payload, label }: { active?: boolean; payload?: { dataKey: string; value: number | null }[]; label?: string }) {
  if (!active || !payload?.length) return null;
  const get = (key: string) => payload.find((p) => p.dataKey === key)?.value ?? null;
  const hrv = get("hrv");
  const avg = get("avg");
  const hi = get("bandHigh");
  const lo = get("bandLow");
  const hi7 = get("band7High");
  const lo7 = get("band7Low");
  if (hrv == null) return null;
  return (
    <div style={{
      background: "var(--card-hover)",
      border: "1px solid var(--hairline-strong)",
      borderRadius: 8,
      padding: "8px 12px",
      fontSize: 11,
      lineHeight: 1.7,
      minWidth: 148,
    }}>
      <div style={{ color: "var(--text-muted)", marginBottom: 4, fontSize: 10.5, letterSpacing: "0.04em" }}>{label}</div>
      <div style={{ color: "var(--chart-line)", fontWeight: 600 }}>HRV&nbsp;&nbsp;<span style={{ float: "right" }}>{hrv} ms</span></div>
      {avg != null && <div style={{ color: "var(--text-muted)" }}>28d avg&nbsp;&nbsp;<span style={{ float: "right" }}>{avg} ms</span></div>}
      {hi != null && lo != null && (
        <div style={{ color: "var(--text-dim)", marginTop: 2 }}>28d ±1σ&nbsp;&nbsp;<span style={{ float: "right" }}>{lo}–{hi}</span></div>
      )}
      {hi7 != null && lo7 != null && (
        <div style={{ color: "oklch(0.72 0.16 200 / 0.8)", marginTop: 2 }}>7d ±0.5σ&nbsp;&nbsp;<span style={{ float: "right" }}>{lo7}–{hi7}</span></div>
      )}
    </div>
  );
}

function HRVTrendCard({
  data,
  baseline,
}: {
  data: { date: string; hrv: number; avg: number; sd: number; hrv_7d_avg?: number | null; hrv_7d_sd?: number | null }[];
  baseline: number | null;
}) {
  const series = data.map((p) => ({
    date: p.date.slice(5),
    hrv: p.hrv ? +p.hrv.toFixed(1) : null,
    bandHigh: p.avg && p.sd ? +(p.avg + p.sd).toFixed(1) : null,
    bandLow: p.avg && p.sd ? +(p.avg - p.sd).toFixed(1) : null,
    avg: p.avg ? +p.avg.toFixed(1) : null,
    band7High: p.hrv_7d_avg && p.hrv_7d_sd ? +(p.hrv_7d_avg + 0.5 * p.hrv_7d_sd).toFixed(1) : null,
    band7Low: p.hrv_7d_avg && p.hrv_7d_sd ? +(p.hrv_7d_avg - 0.5 * p.hrv_7d_sd).toFixed(1) : null,
    avg7: p.hrv_7d_avg ? +p.hrv_7d_avg.toFixed(1) : null,
  }));
  const today = data.length ? data[data.length - 1] : null;
  const sigma = today && today.sd ? (today.hrv - today.avg) / today.sd : null;

  // Streak below 7d band (0.5 SD rule)
  const belowStreak = useMemo(() => {
    let streak = 0;
    for (let i = data.length - 1; i >= 0; i--) {
      const p = data[i];
      if (!p.hrv_7d_avg || !p.hrv_7d_sd) break;
      if (p.hrv < p.hrv_7d_avg - 0.5 * p.hrv_7d_sd) streak++;
      else break;
    }
    return streak;
  }, [data]);

  const has7dBand = data.some((p) => p.hrv_7d_avg != null);

  return (
    <div>
      <div className="flex items-baseline justify-between mb-2">
        <Eyebrow>HRV · 90d with ±1σ band</Eyebrow>
        <div className="flex items-center gap-3 text-[10.5px] tabular-nums">
          {belowStreak >= 3 && (
            <span style={{ color: "var(--warn)" }}>
              ↓ {belowStreak}d below 7d band
            </span>
          )}
          {sigma != null && (
            <span style={{ color: sigmaColor(sigma) }}>
              today {sigma >= 0 ? "+" : ""}
              {sigma.toFixed(2)}σ
            </span>
          )}
          {baseline && (
            <span className="text-[var(--text-dim)]">baseline {baseline.toFixed(1)}ms</span>
          )}
        </div>
      </div>
      <div className="h-[180px]">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={series} margin={{ top: 4, right: 8, left: -22, bottom: 0 }}>
            {/* 28d ±1σ band (wide) */}
            <Area dataKey="bandHigh" fill="var(--chart-band)" stroke="none" isAnimationActive={false} />
            <Area dataKey="bandLow" fill="var(--bg)" stroke="none" isAnimationActive={false} />
            {/* 7d ±0.5σ band (tighter, more actionable) */}
            {has7dBand && (
              <Area dataKey="band7High" fill="oklch(0.65 0.14 200 / 0.12)" stroke="none" isAnimationActive={false} />
            )}
            {has7dBand && (
              <Area dataKey="band7Low" fill="var(--bg)" stroke="none" isAnimationActive={false} />
            )}
            <Line dataKey="avg" stroke="var(--chart-baseline)" strokeWidth={1} strokeDasharray="4 3" dot={false} isAnimationActive={false} />
            <Line
              dataKey="hrv"
              stroke="var(--chart-line)"
              strokeWidth={1.8}
              dot={false}
              isAnimationActive={false}
              activeDot={{ r: 3 }}
            />
            {series.length > 0 && (
              <ReferenceLine x={series[series.length - 1].date} stroke="var(--accent)" strokeWidth={1.2} strokeDasharray="2 2" />
            )}
            <XAxis dataKey="date" tick={{ fontSize: 9.5, fill: "var(--text-faint)" }} axisLine={false} tickLine={false} interval={Math.floor(series.length / 6) || 1} />
            <YAxis tick={{ fontSize: 9.5, fill: "var(--text-faint)" }} axisLine={false} tickLine={false} width={30} />
            <Tooltip content={<HRVTooltip />} cursor={{ stroke: "var(--hairline-strong)", strokeWidth: 1 }} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      {has7dBand && (
        <div className="flex items-center gap-4 mt-1.5 text-[10px] text-[var(--text-faint)]">
          <span className="flex items-center gap-1">
            <span className="inline-block w-4 h-2 rounded-sm" style={{ background: "var(--chart-band)", opacity: 0.6 }} />
            28d ±1σ
          </span>
          <span className="flex items-center gap-1">
            <span className="inline-block w-4 h-2 rounded-sm" style={{ background: "oklch(0.65 0.14 200 / 0.4)" }} />
            7d ±0.5σ (guidance)
          </span>
        </div>
      )}
    </div>
  );
}

function sigmaColor(s: number): string {
  if (s <= -1) return "var(--negative)";
  if (s < 0) return "var(--text-muted)";
  if (s >= 1) return "var(--positive)";
  return "var(--text-primary)";
}

function PreIllnessStrip({
  data,
  hrv,
}: {
  data: { date: string; score: number; hrv: number; rhr: number }[];
  hrv: { date: string; hrv: number; avg: number; sd: number }[];
}) {
  // Multi-criteria pre-illness signal: research rule-of-thumb is
  // (RHR Δ ≥ +5 bpm vs 28d baseline) AND (HRV ≤ -1σ) — illness, infection,
  // and overload routinely trigger 2-3 days before symptoms. Skin temp would
  // strengthen this further; we approximate via combined RHR + HRV here.
  const last30 = data.slice(-30);
  const hrvByDate = new Map(hrv.map((h) => [h.date, h]));

  // 28d RHR baseline using all 90d we have.
  const rhrBaseline =
    data.length > 0
      ? data.slice(-28).reduce((s, d) => s + d.rhr, 0) / Math.min(28, data.length)
      : null;

  const cells = last30.map((d) => {
    const hrvPoint = hrvByDate.get(d.date);
    const sigma = hrvPoint && hrvPoint.sd ? (hrvPoint.hrv - hrvPoint.avg) / hrvPoint.sd : null;
    const rhrDelta = rhrBaseline != null ? d.rhr - rhrBaseline : null;
    const rhrFlag = rhrDelta != null && rhrDelta >= 5;
    const hrvFlag = sigma != null && sigma <= -1;
    const both = rhrFlag && hrvFlag;
    return {
      date: d.date,
      sigma,
      rhrDelta,
      rhrFlag,
      hrvFlag,
      both,
    };
  });

  const flagged = cells.filter((c) => c.both).length;

  return (
    <div>
      <div className="flex items-baseline justify-between mb-2">
        <Eyebrow>Pre-illness alarm · 30d</Eyebrow>
        <span className="text-[10px] text-[var(--text-faint)]">
          rule: RHR Δ ≥ +5 bpm AND HRV ≤ -1σ
          {flagged > 0 && (
            <span className="text-[var(--negative)] ml-2 tabular-nums">{flagged} hit</span>
          )}
        </span>
      </div>
      <div className="flex gap-[3px]">
        {cells.map((c) => {
          let bg = "var(--hairline)";
          let outline = "transparent";
          if (c.both) {
            bg = "oklch(0.5 0.22 25 / 0.85)";
            outline = "oklch(0.7 0.22 25)";
          } else if (c.rhrFlag || c.hrvFlag) {
            bg = "oklch(0.6 0.16 80 / 0.5)";
            outline = "oklch(0.7 0.18 80 / 0.7)";
          }
          return (
            <div
              key={c.date}
              title={`${c.date}\n${c.rhrDelta != null ? `RHR Δ ${c.rhrDelta >= 0 ? "+" : ""}${c.rhrDelta.toFixed(1)} bpm` : "no RHR"}\n${c.sigma != null ? `HRV ${c.sigma >= 0 ? "+" : ""}${c.sigma.toFixed(2)}σ` : "no HRV"}${c.both ? "\nboth flags hit" : ""}`}
              className="h-[24px] flex-1 rounded-[2px] transition-transform hover:scale-y-110"
              style={{ background: bg, boxShadow: `inset 0 0 0 1px ${outline}` }}
            />
          );
        })}
      </div>
      <div className="flex justify-between mt-1 text-[9.5px] text-[var(--text-faint)] tabular-nums">
        <span>{cells[0]?.date.slice(5)}</span>
        <span>{cells[cells.length - 1]?.date.slice(5)}</span>
      </div>
    </div>
  );
}

function MonthlyAverages({ data }: { data: { date: string; score: number; hrv: number }[] }) {
  const byMonth: Record<string, { scores: number[]; hrvs: number[] }> = {};
  data.forEach((p) => {
    const k = p.date.slice(0, 7);
    if (!byMonth[k]) byMonth[k] = { scores: [], hrvs: [] };
    if (p.score != null) byMonth[k].scores.push(p.score);
    if (p.hrv != null) byMonth[k].hrvs.push(p.hrv);
  });
  return (
    <div>
      <Eyebrow>Monthly averages</Eyebrow>
      <div className="mt-2 rounded-lg border border-[var(--hairline)] overflow-hidden">
        <table className="w-full text-[12px] tabular-nums">
          <thead className="text-[10px] text-[var(--text-dim)] uppercase tracking-wider">
            <tr className="border-b border-[var(--hairline)]">
              <th className="px-3 py-2 text-left font-normal">Month</th>
              <th className="px-3 py-2 text-right font-normal">Recovery</th>
              <th className="px-3 py-2 text-right font-normal">HRV</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(byMonth)
              .sort(([a], [b]) => b.localeCompare(a))
              .slice(0, 4)
              .map(([k, v]) => {
                const avgRec = v.scores.length ? v.scores.reduce((a, b) => a + b, 0) / v.scores.length : null;
                const avgHrv = v.hrvs.length ? v.hrvs.reduce((a, b) => a + b, 0) / v.hrvs.length : null;
                const label = new Date(k + "-01T12:00:00").toLocaleDateString("en-US", { month: "long", year: "numeric" });
                return (
                  <tr key={k} className="border-b border-[var(--hairline)] last:border-b-0 hover:bg-[oklch(1_0_0/0.02)]">
                    <td className="px-3 py-2 text-[var(--text-muted)]">{label}</td>
                    <td className="px-3 py-2 text-right">{avgRec ? avgRec.toFixed(0) : "—"}</td>
                    <td className="px-3 py-2 text-right">{avgHrv ? avgHrv.toFixed(1) : "—"}<span className="text-[var(--text-faint)] ml-1">ms</span></td>
                  </tr>
                );
              })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────────
// INSIGHTS TAB
// ──────────────────────────────────────────────────────────────────────────

function InsightsPane() {
  return (
    <div className="space-y-6">
      <p className="shc-helptext flex items-baseline gap-1.5 flex-wrap">
        <span className="text-[var(--text-muted)]">How to read this. </span>
        <span>
          Cards on this tab synthesise your live data with research from your
          {" "}
          <span className="inline-flex items-center gap-1 align-middle">
            <ObsidianMark size={11} />
            <span className="text-[var(--text-muted)]">Obsidian vault</span>
          </span>
          {" "}
          — Israetel volume landmarks, Helms set progression, Gabbett ACWR — to turn raw numbers
          into prescriptive signals.
        </span>
      </p>
      <ReadinessDecomposition />
      <VolumeLandmarks />
      <MuscleVolumePanel />
      <SleepDoseResponse />
      <ACWRDeloadCard />
      <CorrelationCards />
    </div>
  );
}

function ReadinessDecomposition() {
  const state = useQuery({ queryKey: ["daily-state"], queryFn: api.dailyState });
  const r = state.data?.readiness;
  if (!r || r.score == null) return null;
  const components = [
    { key: "hrv", label: "HRV", weight: r.weights.hrv, value: r.components.hrv ?? 0 },
    { key: "sleep", label: "Sleep", weight: r.weights.sleep, value: r.components.sleep ?? 0 },
    { key: "rhr", label: "RHR", weight: r.weights.rhr, value: r.components.rhr ?? 0 },
    { key: "subj", label: "Subjective", weight: r.weights.subj, value: r.components.subj ?? 0 },
  ];
  const tier = r.tier ?? "yellow";
  const tierColor =
    tier === "green" ? "var(--positive)" : tier === "red" ? "var(--negative)" : "var(--warn)";

  return (
    <div className="rounded-lg border border-[var(--hairline)] p-4 space-y-3">
      <div className="flex items-baseline justify-between">
        <Eyebrow>Why is today {tier}?</Eyebrow>
        <span className="tabular-nums text-[15px] font-medium" style={{ color: tierColor }}>
          {r.score.toFixed(0)}/100
        </span>
      </div>
      <div className="space-y-2">
        {components.map((c) => {
          const contribution = c.weight * c.value;
          return (
            <div key={c.key} className="space-y-0.5">
              <div className="flex items-baseline justify-between text-[11px]">
                <span className="text-[var(--text-muted)]">
                  {c.label}{" "}
                  <span className="text-[var(--text-faint)] tabular-nums">
                    × {(c.weight * 100).toFixed(0)}%
                  </span>
                </span>
                <span className="tabular-nums">
                  <span className="text-[var(--text-primary)]">{contribution.toFixed(1)}</span>
                  <span className="text-[var(--text-faint)] text-[10px]"> · raw {c.value.toFixed(0)}</span>
                </span>
              </div>
              <div className="h-[5px] rounded-full bg-[var(--hairline)] overflow-hidden">
                <div
                  className="h-full rounded-full"
                  style={{
                    width: `${Math.min(100, c.value)}%`,
                    background: c.value >= 67 ? "var(--positive)" : c.value >= 34 ? "var(--warn)" : "var(--negative)",
                  }}
                />
              </div>
            </div>
          );
        })}
      </div>
      {r.beta_blocker_adjusted && (
        <div className="text-[10.5px] text-[var(--text-muted)] italic">
          β-blocker adjusted — RHR/HRV de-weighted today.
        </div>
      )}
      <p className="text-[10px] text-[var(--text-faint)] leading-relaxed pt-1">
        Composite readiness uses the weights shown. Sub-component {"<"} 34 drags the score below the
        green threshold (67). HRV and sleep dominate — fixing the lower of those is the highest-ROI
        lever.
      </p>
    </div>
  );
}

// Israetel volume landmarks for grouped categories (combined sets/wk).
// Per-muscle MEV ~10 / MAV ~15 / MRV ~20 (Renaissance Periodization).
// Push  = chest + shoulders + triceps (3 muscles)
// Pull  = back + biceps + rear delts (3 muscles)
// Legs  = quads + hams + glutes + calves (4 muscles)
// Bands are conservative midpoints across the constituent muscles.
const VOLUME_LANDMARKS: Record<string, { mv: number; mev: number; mav: number; mrv: number }> = {
  push: { mv: 18, mev: 30, mav: 45, mrv: 60 },
  pull: { mv: 18, mev: 30, mav: 45, mrv: 60 },
  legs: { mv: 24, mev: 36, mav: 56, mrv: 72 },
  core: { mv: 0, mev: 8, mav: 16, mrv: 24 },
};

function VolumeLandmarks() {
  const balance = useQuery({
    queryKey: ["muscle-balance-4"],
    queryFn: () => api.trainingMuscleBalance(4),
  });
  if (!balance.data) return null;
  const groups = balance.data.groups.filter((g) => VOLUME_LANDMARKS[g.group]);

  return (
    <div className="rounded-lg border border-[var(--hairline)] p-4 space-y-3">
      <div className="flex items-baseline justify-between">
        <Eyebrow>Volume landmarks · weekly sets vs MEV/MAV/MRV</Eyebrow>
        <span className="inline-flex items-center gap-1.5 text-[10px] text-[var(--text-faint)]">
          <ObsidianMark size={10} />
          Israetel · RP
        </span>
      </div>
      <div className="space-y-3">
        {groups.map((g) => {
          const lm = VOLUME_LANDMARKS[g.group];
          const max = lm.mrv * 1.15;
          const pos = (v: number) => `${(v / max) * 100}%`;
          const status = classifyVolume(g.weekly_sets, lm);
          return (
            <div key={g.group} className="space-y-1">
              <div className="flex items-baseline justify-between text-[11.5px]">
                <span className="capitalize text-[var(--text-muted)]">{g.group}</span>
                <span className="tabular-nums">
                  <span className="text-[var(--text-primary)]">{g.weekly_sets.toFixed(1)}</span>
                  <span className="text-[var(--text-faint)] text-[10px] ml-1">sets/wk</span>
                  <span
                    className="ml-2 text-[10px] px-1.5 py-[1px] rounded-sm"
                    style={{
                      background: `${status.color} / 0.15`,
                      color: status.color,
                      border: `1px solid ${status.color}`,
                    }}
                  >
                    {status.label}
                  </span>
                </span>
              </div>
              <div className="relative h-[14px] rounded-sm overflow-hidden bg-[var(--hairline)]">
                {/* MV (under) */}
                <div
                  className="absolute inset-y-0 left-0"
                  style={{ width: pos(lm.mv), background: "oklch(0.4 0.04 60 / 0.5)" }}
                />
                {/* MEV-MAV (productive) */}
                <div
                  className="absolute inset-y-0"
                  style={{ left: pos(lm.mev), width: `calc(${pos(lm.mav)} - ${pos(lm.mev)})`, background: "oklch(0.55 0.16 145 / 0.35)" }}
                />
                {/* MAV-MRV (overreach edge) */}
                <div
                  className="absolute inset-y-0"
                  style={{ left: pos(lm.mav), width: `calc(${pos(lm.mrv)} - ${pos(lm.mav)})`, background: "oklch(0.6 0.16 80 / 0.4)" }}
                />
                {/* MRV+ junk */}
                <div
                  className="absolute inset-y-0"
                  style={{ left: pos(lm.mrv), right: 0, background: "oklch(0.5 0.22 25 / 0.5)" }}
                />
                {/* Marker for actual */}
                <div
                  className="absolute inset-y-0 w-[2.5px] bg-[var(--text-primary)]"
                  style={{ left: pos(g.weekly_sets), boxShadow: "0 0 0 1px var(--bg)" }}
                />
                {/* Landmark ticks */}
                {[lm.mev, lm.mav, lm.mrv].map((t) => (
                  <div
                    key={t}
                    className="absolute inset-y-0 w-px bg-[var(--bg)] opacity-50"
                    style={{ left: pos(t) }}
                  />
                ))}
              </div>
              <div className="relative h-[10px] text-[8.5px] text-[var(--text-faint)] tabular-nums">
                <span className="absolute" style={{ left: pos(lm.mev), transform: "translateX(-50%)" }}>
                  MEV {lm.mev}
                </span>
                <span className="absolute" style={{ left: pos(lm.mav), transform: "translateX(-50%)" }}>
                  MAV {lm.mav}
                </span>
                <span className="absolute" style={{ left: pos(lm.mrv), transform: "translateX(-50%)" }}>
                  MRV {lm.mrv}
                </span>
              </div>
            </div>
          );
        })}
      </div>
      <p className="text-[10px] text-[var(--text-faint)] leading-relaxed pt-2 border-t border-[var(--hairline)]">
        Volume bands per Renaissance Periodization (Israetel). Below MEV → not enough stimulus to
        grow. Between MEV and MAV → productive. Past MAV → overreach territory. Past MRV → junk
        volume that generates fatigue without proportional growth.
      </p>
    </div>
  );
}

function classifyVolume(
  sets: number,
  lm: { mv: number; mev: number; mav: number; mrv: number },
): { label: string; color: string } {
  if (sets < lm.mev) return { label: "below MEV", color: "oklch(0.7 0.18 80)" };
  if (sets < lm.mav) return { label: "productive", color: "oklch(0.72 0.2 145)" };
  if (sets < lm.mrv) return { label: "overreach", color: "oklch(0.7 0.16 60)" };
  return { label: "junk volume", color: "oklch(0.65 0.22 25)" };
}

function SleepDoseResponse() {
  const patterns = useQuery({ queryKey: ["whoop-patterns"], queryFn: api.whoopPatterns });
  const data = patterns.data?.sleep_vs_recovery ?? [];

  // Bin by sleep hours (4–10 in 1h bins) and average recovery.
  const bins = useMemo(() => {
    const buckets: Record<string, { sum: number; n: number; lo: number; hi: number }> = {};
    for (let h = 4; h < 10; h++) {
      buckets[`${h}-${h + 1}`] = { sum: 0, n: 0, lo: h, hi: h + 1 };
    }
    data.forEach((p) => {
      if (p.sleep_h == null || p.recovery == null) return;
      const h = Math.floor(p.sleep_h);
      const key = `${h}-${h + 1}`;
      if (buckets[key]) {
        buckets[key].sum += p.recovery;
        buckets[key].n += 1;
      }
    });
    return Object.entries(buckets).map(([range, b]) => ({
      range,
      sleep: b.lo + 0.5,
      recovery: b.n > 0 ? b.sum / b.n : null,
      n: b.n,
    }));
  }, [data]);

  // Research dose-response curve (logistic-shaped). Walker (2017), Watson (2015):
  // <6h sleep → ~5-15% strength loss + significant HRV depression; 7-9h optimal;
  // >9h diminishing returns (and sometimes oversleep correlates with poor health).
  const research = [
    { sleep: 4.5, recovery: 35 },
    { sleep: 5.5, recovery: 45 },
    { sleep: 6.5, recovery: 58 },
    { sleep: 7.5, recovery: 72 },
    { sleep: 8.5, recovery: 75 },
    { sleep: 9.5, recovery: 70 },
  ];

  const sweetSpot = bins
    .filter((b) => b.recovery != null && b.n >= 3)
    .reduce((best, cur) => (cur.recovery! > (best?.recovery ?? -1) ? cur : best), null as typeof bins[0] | null);

  return (
    <div className="rounded-lg border border-[var(--hairline)] p-4 space-y-3">
      <div className="flex items-baseline justify-between">
        <Eyebrow>Sleep dose-response · your data + research</Eyebrow>
        <span className="inline-flex items-center gap-1.5 text-[10px] text-[var(--text-faint)]">
          <ObsidianMark size={10} />
          Walker · Watson · Roenneberg
        </span>
      </div>
      <div className="h-[180px]">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart margin={{ top: 8, right: 8, left: -22, bottom: 0 }}>
            <XAxis
              type="number"
              dataKey="sleep"
              domain={[4, 10]}
              ticks={[4, 5, 6, 7, 8, 9, 10]}
              tick={{ fontSize: 9.5, fill: "var(--text-faint)" }}
              axisLine={false}
              tickLine={false}
              label={{ value: "sleep hours", position: "insideBottom", offset: -2, fontSize: 9, fill: "var(--text-faint)" }}
            />
            <YAxis
              domain={[0, 100]}
              tick={{ fontSize: 9.5, fill: "var(--text-faint)" }}
              axisLine={false}
              tickLine={false}
              width={30}
            />
            <ReferenceArea x1={7} x2={9} fill="oklch(0.6 0.16 145 / 0.08)" stroke="none" />
            <Line
              data={research}
              dataKey="recovery"
              stroke="var(--chart-baseline)"
              strokeWidth={1}
              strokeDasharray="4 3"
              dot={false}
              isAnimationActive={false}
              name="research"
            />
            <Line
              data={bins.filter((b) => b.recovery != null)}
              dataKey="recovery"
              stroke="var(--chart-line)"
              strokeWidth={1.8}
              dot={{ r: 3, fill: "var(--chart-line)" }}
              isAnimationActive={false}
              name="you"
            />
            <Tooltip
              contentStyle={{ background: "var(--card-hover)", border: "1px solid var(--hairline-strong)", borderRadius: 8, fontSize: 11 }}
              cursor={{ stroke: "var(--hairline-strong)" }}
              formatter={(v: number) => [v.toFixed(0), "recovery"]}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <div className="flex flex-wrap gap-3 text-[10.5px] text-[var(--text-muted)]">
        <span>
          <span
            className="inline-block w-3 h-[2px] align-middle mr-1"
            style={{ background: "var(--chart-line)" }}
          />
          your data
        </span>
        <span>
          <span
            className="inline-block w-3 h-[2px] align-middle mr-1"
            style={{ background: "var(--chart-baseline)", borderTop: "1px dashed var(--chart-baseline)" }}
          />
          research dose-response
        </span>
        <span className="text-[var(--text-faint)]">7–9h band shaded</span>
      </div>
      {sweetSpot && (
        <div className="text-[11px] text-[var(--text-muted)] pt-1 border-t border-[var(--hairline)]">
          Your sweet spot: <span className="text-[var(--text-primary)] tabular-nums">{sweetSpot.range}h</span> →
          avg recovery <span className="text-[var(--text-primary)] tabular-nums">{sweetSpot.recovery!.toFixed(0)}</span>{" "}
          <span className="text-[var(--text-faint)]">(n={sweetSpot.n})</span>
        </div>
      )}
    </div>
  );
}

function ACWRDeloadCard() {
  const state = useQuery({ queryKey: ["daily-state"], queryFn: api.dailyState });
  const stats = useQuery({ queryKey: ["stats-summary"], queryFn: api.statsSummary });
  const acwr = stats.data?.acwr;
  const gates = state.data?.gates;
  if (!acwr || !gates) return null;

  const ratio = acwr.ratio;
  const acute = acwr.acute;
  const chronic = acwr.chronic;
  const e1rm = gates.e1rm_regression_4wk_pct;
  const deload = gates.deload_required;

  // ACWR zones (Gabbett): undertraining <0.8, sweet spot 0.8-1.3, danger >1.5.
  const max = 2.0;
  const pct = (v: number) => `${Math.min(100, (v / max) * 100)}%`;

  return (
    <div className="rounded-lg border border-[var(--hairline)] p-4 grid md:grid-cols-2 gap-4">
      <div className="space-y-2">
        <div className="flex items-baseline justify-between">
          <Eyebrow>ACWR · Gabbett zones</Eyebrow>
          {ratio != null && (
            <span className="tabular-nums text-[14px] font-medium" style={{ color: acwrColor(ratio) }}>
              {ratio.toFixed(2)}
            </span>
          )}
        </div>
        <div className="relative h-[14px] rounded-sm overflow-hidden bg-[var(--hairline)]">
          <div className="absolute inset-y-0 left-0" style={{ width: pct(0.8), background: "oklch(0.6 0.14 80 / 0.4)" }} />
          <div className="absolute inset-y-0" style={{ left: pct(0.8), width: `calc(${pct(1.3)} - ${pct(0.8)})`, background: "oklch(0.6 0.18 145 / 0.45)" }} />
          <div className="absolute inset-y-0" style={{ left: pct(1.3), width: `calc(${pct(1.5)} - ${pct(1.3)})`, background: "oklch(0.6 0.16 60 / 0.4)" }} />
          <div className="absolute inset-y-0" style={{ left: pct(1.5), right: 0, background: "oklch(0.55 0.22 25 / 0.55)" }} />
          {ratio != null && (
            <div
              className="absolute inset-y-0 w-[2.5px] bg-[var(--text-primary)]"
              style={{ left: pct(ratio), boxShadow: "0 0 0 1px var(--bg)" }}
            />
          )}
        </div>
        <div className="relative h-[10px] text-[8.5px] text-[var(--text-faint)] tabular-nums">
          {[0.8, 1.3, 1.5].map((v) => (
            <span key={v} className="absolute" style={{ left: pct(v), transform: "translateX(-50%)" }}>
              {v}
            </span>
          ))}
        </div>
        <div className="grid grid-cols-2 gap-2 text-[10.5px] tabular-nums pt-1">
          <div>
            <span className="text-[var(--text-faint)]">acute 7d </span>
            <span className="text-[var(--text-primary)]">{acute?.toFixed(1) ?? "—"}</span>
          </div>
          <div>
            <span className="text-[var(--text-faint)]">chronic 28d </span>
            <span className="text-[var(--text-primary)]">{chronic?.toFixed(1) ?? "—"}</span>
          </div>
        </div>
        <p className="text-[10px] text-[var(--text-faint)] leading-relaxed pt-1">
          Gabbett (2016): sweet spot 0.8–1.3, danger zone {">"}1.5 (2-4× injury risk).
        </p>
      </div>

      <div className="space-y-2">
        <div className="flex items-baseline justify-between">
          <Eyebrow>Deload status</Eyebrow>
          <span
            className="text-[10.5px] px-2 py-0.5 rounded-full"
            style={{
              background: deload ? "oklch(0.5 0.22 25 / 0.18)" : "oklch(0.6 0.18 145 / 0.18)",
              color: deload ? "var(--negative)" : "var(--positive)",
              border: `1px solid ${deload ? "var(--negative)" : "var(--positive)"}`,
            }}
          >
            {deload ? "REQUIRED" : "ON TRACK"}
          </span>
        </div>
        {e1rm != null && (
          <div className="text-[11px] tabular-nums">
            <span className="text-[var(--text-faint)]">e1RM 4wk </span>
            <span style={{ color: e1rm < -3 ? "var(--negative)" : "var(--text-primary)" }}>
              {e1rm >= 0 ? "+" : ""}
              {e1rm.toFixed(1)}%
            </span>
          </div>
        )}
        {gates.reasons.length > 0 && (
          <ul className="space-y-1 text-[10.5px] text-[var(--text-muted)]">
            {gates.reasons.slice(0, 4).map((r, i) => (
              <li key={i} className="flex gap-1.5">
                <span className="text-[var(--text-faint)]">•</span>
                <span>{r}</span>
              </li>
            ))}
          </ul>
        )}
        <p className="text-[10px] text-[var(--text-faint)] leading-relaxed pt-1">
          Israetel (2020): mandatory deload every 3rd mesocycle, or earlier when e1RM regresses
          {" >"}3% on a primary lift. ~50% volume cut to MEV; load held.
        </p>
      </div>
    </div>
  );
}

function acwrColor(r: number): string {
  if (r < 0.8) return "var(--warn)";
  if (r <= 1.3) return "var(--positive)";
  if (r <= 1.5) return "var(--warn)";
  return "var(--negative)";
}

function ClinicalPane() {
  return <ClinicalOverview />;
}

export function TrendIntelligence() {
  const [tab, setTab] = useState<Tab>("Recovery");

  return (
    <div className="shc-card shc-enter p-5">
      <div className="flex items-baseline justify-between mb-4 gap-3 flex-wrap">
        <h2 className="shc-section-title">Trend Intelligence</h2>
        <div
          className="flex gap-0.5 p-0.5 rounded-[var(--r-md)]"
          style={{ background: "oklch(1 0 0 / 0.025)", border: "1px solid var(--hairline)" }}
        >
          {TABS.map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`px-3 py-1.5 text-[10.5px] rounded-[6px] transition-colors uppercase tracking-[0.16em] ${
                tab === t
                  ? "bg-[oklch(1_0_0/0.07)] text-[var(--text-primary)]"
                  : "text-[var(--text-dim)] hover:text-[var(--text-muted)]"
              }`}
              style={{ fontFamily: "var(--font-orbitron)" }}
            >
              {t}
            </button>
          ))}
        </div>
      </div>
      <div className="mt-2">
        {tab === "Recovery" && <RecoveryTrendPane />}
        {tab === "Body" && <BodyPane />}
        {tab === "Patterns" && <PatternsPane />}
        {tab === "Insights" && <InsightsPane />}
        {tab === "Performance" && <PerformanceCurvePane />}
        {tab === "Sport" && <PickleballPane />}
        {tab === "Clinical" && <ClinicalPane />}
      </div>
    </div>
  );
}
