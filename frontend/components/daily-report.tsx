"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Area, AreaChart, ResponsiveContainer } from "recharts";
import { api } from "@/lib/api";
import { Eyebrow, Metric, DeltaPill } from "@/components/ui/metric";
import { Markdown } from "@/components/ui/markdown";
import { ObsidianMark, ObsidianSourceTag } from "@/components/obsidian-badge";

const CALL_COLOR: Record<string, string> = {
  Push:     "var(--sl-accent)",
  Train:    "var(--positive)",
  Maintain: "var(--text-primary)",
  Easy:     "var(--text-muted)",
  Rest:     "var(--negative)",
};

// Section accent colours — cycles through a palette for visual variety
const SECTION_ACCENTS = [
  "var(--sl-accent)",
  "var(--sl-accent-teal)",
  "var(--positive)",
  "oklch(0.72 0.18 260)",
  "oklch(0.72 0.20 45)",
  "var(--sl-accent)",
];

function Ring({ score, size = 80 }: { score: number | null; size?: number }) {
  const pct = score != null ? Math.max(0, Math.min(100, score)) / 100 : 0;
  const color =
    score == null ? "var(--text-faint)" : score >= 67 ? "var(--positive)" : score >= 34 ? "var(--sl-accent)" : "var(--negative)";
  const r = (size - 10) / 2;
  const c = 2 * Math.PI * r;
  const cx = size / 2;
  return (
    <div className="relative shrink-0" style={{ width: size, height: size }}>
      <svg width={size} height={size} style={{ transform: "rotate(-90deg)" }}>
        <circle cx={cx} cy={cx} r={r} fill="none" stroke="var(--hairline-strong)" strokeWidth={7} />
        <circle
          cx={cx} cy={cx} r={r} fill="none" stroke={color} strokeWidth={7} strokeLinecap="round"
          strokeDasharray={c} strokeDashoffset={c * (1 - pct)}
          style={{ filter: `drop-shadow(0 0 6px ${color})`, transition: "stroke-dashoffset 700ms ease" }}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-[22px] font-semibold tabular-nums leading-none" style={{ color }}>{score ?? "—"}</span>
        <span className="text-[8px] font-mono uppercase tracking-[0.18em] mt-0.5" style={{ color: "var(--text-faint)" }}>ready</span>
      </div>
    </div>
  );
}

function Spark({ data, dataKey, color }: { data: { [k: string]: number | string }[]; dataKey: string; color: string }) {
  if (!data.length) return null;
  return (
    <ResponsiveContainer width={76} height={28}>
      <AreaChart data={data} margin={{ top: 2, bottom: 2, left: 0, right: 0 }}>
        <Area type="monotone" dataKey={dataKey} stroke={color} strokeWidth={1.5} fill={color} fillOpacity={0.12} dot={false} isAnimationActive={false} />
      </AreaChart>
    </ResponsiveContainer>
  );
}

function Stat({
  label, value, unit, delta, deltaUnit, tone, spark,
}: {
  label: string; value: string | number; unit?: string;
  delta?: number; deltaUnit?: string;
  tone?: "default" | "positive" | "neutral" | "negative";
  spark?: React.ReactNode;
}) {
  return (
    <div
      className="flex flex-col gap-1.5 px-3.5 py-2.5 rounded-xl min-w-[100px]"
      style={{
        border: "1px solid var(--hairline-strong)",
        background: "oklch(0.14 0.01 220 / 0.7)",
        backdropFilter: "blur(8px)",
      }}
    >
      <Eyebrow>{label}</Eyebrow>
      <div className="flex items-baseline gap-1.5">
        <Metric value={value} unit={unit} size="md" tone={tone} />
        {delta != null && <DeltaPill value={delta} unit={deltaUnit} />}
      </div>
      {spark}
    </div>
  );
}

export function DailyReport() {
  const { data, isLoading } = useQuery({ queryKey: ["daily-report"], queryFn: () => api.dailyReport(), refetchInterval: 300_000 });
  const { data: state } = useQuery({ queryKey: ["daily-state"], queryFn: () => api.dailyState() });
  const { data: hrv = [] } = useQuery({ queryKey: ["hrv-trend"], queryFn: () => api.hrvTrend(28) });
  const { data: rec = [] } = useQuery({ queryKey: ["recovery-trend"], queryFn: () => api.recoveryTrend(14) });
  const [copied, setCopied] = useState(false);
  const [expanded, setExpanded] = useState(false);

  const copyPrompt = async () => {
    const { prompt } = await api.dailyReportPrompt();
    await navigator.clipboard.writeText(prompt);
    setCopied(true);
    setTimeout(() => setCopied(false), 2500);
  };

  const r = data?.report;
  const rc = state?.recovery;
  const rhrDelta = rc?.rhr != null && rc?.rhr_baseline_28d != null ? +(rc.rhr - rc.rhr_baseline_28d).toFixed(0) : undefined;
  const acwr = state?.training_load?.acwr ?? null;
  const modeLabel = r?.mode === "post_workout" ? "Post-workout" : r?.mode === "pre_workout" ? "Pre-workout" : null;

  return (
    <section
      id="daily-report"
      className="scroll-mt-20 rounded-2xl border"
      style={{
        borderColor: "var(--hairline-strong)",
        background: "linear-gradient(145deg, oklch(0.16 0.01 220) 0%, oklch(0.115 0 0) 50%, oklch(0.14 0.025 260) 100%)",
      }}
    >
      {/* Top border glow */}
      <div className="h-px rounded-t-2xl" style={{ background: "linear-gradient(90deg, transparent 0%, var(--sl-accent) 35%, var(--sl-accent-teal) 65%, transparent 100%)", opacity: 0.5 }} />

      <div className="p-5 space-y-5">
        {/* Header row */}
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div className="flex items-center gap-3">
            <Eyebrow>Daily report</Eyebrow>
            {r?.training_call && (
              <span
                className="text-[11px] font-mono uppercase tracking-wider px-2.5 py-1 rounded-full"
                style={{
                  color: CALL_COLOR[r.training_call] ?? "var(--text-primary)",
                  border: `1px solid ${CALL_COLOR[r.training_call] ?? "var(--hairline-strong)"}`,
                  background: `color-mix(in oklch, ${CALL_COLOR[r.training_call] ?? "transparent"} 10%, transparent)`,
                }}
              >
                {r.training_call}
              </span>
            )}
            {modeLabel && (
              <span className="text-[10px] font-mono tracking-wide px-2 py-0.5 rounded-full" style={{ color: "var(--text-muted)", background: "var(--hairline)", border: "1px solid var(--hairline-strong)" }}>
                {modeLabel}
              </span>
            )}
            {r && <span className="text-[10px] text-[var(--text-faint)] font-mono">{r.report_date}</span>}
          </div>
          <button
            onClick={copyPrompt}
            className="rounded-lg px-3.5 py-1.5 text-[11.5px] font-semibold tracking-wide transition-all"
            style={{
              background: copied ? "var(--positive-soft)" : "var(--sl-accent-soft)",
              border: `1px solid ${copied ? "var(--positive)" : "var(--sl-accent-dim)"}`,
              color: copied ? "var(--positive)" : "var(--sl-accent)",
            }}
          >
            {copied ? "✓ copied — run in Claude Code" : "Generate daily report"}
          </button>
        </div>

        {/* Readiness headline */}
        {r?.readiness_headline && (
          <p className="text-[16px] font-medium leading-snug max-w-3xl" style={{ color: "var(--text-primary)" }}>
            {r.readiness_headline}
          </p>
        )}

        {/* Data strip */}
        {state && (
          <div className="flex items-center gap-3 flex-wrap">
            <Ring score={state.readiness?.score != null ? Math.round(state.readiness.score) : null} />
            <div className="flex gap-2 flex-wrap">
              <Stat label="HRV" value={rc?.hrv_ms != null ? rc.hrv_ms.toFixed(0) : "—"} unit="ms"
                delta={rc?.hrv_sigma != null ? +rc.hrv_sigma.toFixed(1) : undefined} deltaUnit="σ"
                tone={rc?.hrv_sigma != null && rc.hrv_sigma > 0 ? "positive" : "default"}
                spark={<Spark data={hrv as never} dataKey="hrv" color="var(--sl-accent)" />} />
              <Stat label="RHR" value={rc?.rhr ?? "—"} unit="bpm" delta={rhrDelta} deltaUnit="bpm"
                tone={rhrDelta != null && rhrDelta <= 0 ? "positive" : "default"} />
              <Stat label="Recovery" value={rc?.score != null ? Math.round(rc.score) : "—"}
                spark={<Spark data={rec as never} dataKey="score" color="var(--positive)" />} />
              <Stat label="T:C ratio" value={acwr != null ? acwr.toFixed(2) : "—"}
                tone={acwr != null && acwr > 1.5 ? "negative" : "default"} />
            </div>
          </div>
        )}

        {/* Sections — collapsed by default, expand on demand */}
        {isLoading ? (
          <div className="space-y-3">
            {[1, 2, 3].map((i) => <div key={i} className="h-28 shc-skeleton rounded-xl" />)}
          </div>
        ) : r ? (
          <>
            {/* Expand/collapse toggle */}
            <button
              onClick={() => setExpanded((x) => !x)}
              className="w-full no-tactile flex items-center justify-between gap-2 px-3.5 py-2.5 rounded-xl transition-colors"
              style={{
                border: "1px solid var(--hairline-strong)",
                background: expanded ? "oklch(0.14 0.01 220 / 0.6)" : "oklch(0.13 0.005 220 / 0.4)",
                color: "var(--text-muted)",
              }}
            >
              <span className="text-[11px] font-mono text-left leading-snug" style={{ color: "var(--text-dim)" }}>
                <span className="mr-2" style={{ color: "var(--sl-accent)" }}>{expanded ? "▾" : "▸"}</span>
                {r.sections.map((s) => s.title).join(" · ")}
              </span>
              <span className="text-[10px] tabular-nums shrink-0" style={{ color: "var(--text-faint)" }}>
                {expanded ? "collapse" : `${r.sections.length} sections`}
              </span>
            </button>

            {expanded && (
              <div className="space-y-3">
                {r.sections.map((s, i) => {
                  const accent = SECTION_ACCENTS[i % SECTION_ACCENTS.length];
                  return (
                    <div
                      key={i}
                      className="rounded-xl overflow-hidden"
                      style={{
                        border: "1px solid var(--hairline-strong)",
                        background: "oklch(0.13 0.005 220 / 0.8)",
                      }}
                    >
                      <div style={{ height: "1px", background: `linear-gradient(90deg, ${accent} 0%, ${accent} 30%, transparent 75%)` }} />
                      <div className="p-4 space-y-3">
                        <div className="flex items-baseline gap-3">
                          <span className="text-[10px] font-mono tabular-nums shrink-0 leading-none" style={{ color: accent, opacity: 0.7 }}>
                            {String(i + 1).padStart(2, "0")}
                          </span>
                          <h3 className="text-[13px] font-semibold tracking-tight" style={{ color: "var(--text-primary)" }}>
                            {s.title}
                          </h3>
                        </div>
                        <Markdown text={s.body_md} />
                      </div>
                    </div>
                  );
                })}

                {r.sources && r.sources.length > 0 && (
                  <div className="pt-2 space-y-2">
                    <div className="flex items-center gap-2" style={{ color: "var(--text-faint)" }}>
                      <div className="h-px flex-1" style={{ background: "var(--hairline)" }} />
                      <span className="flex items-center gap-1.5 text-[10px] font-mono uppercase tracking-wider">
                        <ObsidianMark size={11} /> Vault research cited
                      </span>
                      <div className="h-px flex-1" style={{ background: "var(--hairline)" }} />
                    </div>
                    <div className="flex flex-wrap">
                      {r.sources.map((s) => <ObsidianSourceTag key={s} source={s} />)}
                    </div>
                  </div>
                )}

                <p className="text-[10px] font-mono" style={{ color: "var(--text-faint)" }}>
                  Generated {new Date(r.generated_at).toLocaleString()} · {r.model} · synced metrics + vault research
                </p>
              </div>
            )}
          </>
        ) : (
          <div
            className="rounded-xl p-6 flex flex-col items-center gap-3 text-center"
            style={{ border: "1px dashed var(--hairline-strong)", background: "oklch(0.13 0 0 / 0.5)" }}
          >
            <p className="text-[13px]" style={{ color: "var(--text-muted)" }}>No report yet.</p>
            <p className="text-[12px] max-w-sm" style={{ color: "var(--text-faint)" }}>
              Click <strong style={{ color: "var(--sl-accent)" }}>Generate daily report</strong>, run the copied prompt in Claude Code — it syncs your data, builds the workout plan, and posts the full report here.
            </p>
          </div>
        )}
      </div>
    </section>
  );
}
