"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Area, AreaChart, ResponsiveContainer } from "recharts";
import { api } from "@/lib/api";
import { Eyebrow, Metric, DeltaPill } from "@/components/ui/metric";
import { Markdown } from "@/components/ui/markdown";
import { ObsidianMark, ObsidianSourceTag } from "@/components/obsidian-badge";

const CALL_COLOR: Record<string, string> = {
  Push: "var(--sl-accent)",
  Train: "var(--positive)",
  Maintain: "var(--text-primary)",
  Easy: "var(--text-muted)",
  Rest: "var(--negative)",
};

function Ring({ score, size = 76 }: { score: number | null; size?: number }) {
  const pct = score != null ? Math.max(0, Math.min(100, score)) / 100 : 0;
  const color =
    score == null ? "var(--text-faint)" : score >= 67 ? "var(--positive)" : score >= 34 ? "var(--sl-accent)" : "var(--negative)";
  const r = (size - 9) / 2;
  const c = 2 * Math.PI * r;
  const cx = size / 2;
  return (
    <div className="relative shrink-0" style={{ width: size, height: size }}>
      <svg width={size} height={size} style={{ transform: "rotate(-90deg)" }}>
        <circle cx={cx} cy={cx} r={r} fill="none" stroke="var(--hairline-strong)" strokeWidth={6} />
        <circle
          cx={cx} cy={cx} r={r} fill="none" stroke={color} strokeWidth={6} strokeLinecap="round"
          strokeDasharray={c} strokeDashoffset={c * (1 - pct)}
          style={{ filter: `drop-shadow(0 0 5px ${color})`, transition: "stroke-dashoffset 600ms ease" }}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-[20px] font-semibold tabular-nums" style={{ color }}>{score ?? "—"}</span>
        <span className="text-[8px] font-mono uppercase tracking-[0.15em] text-[var(--text-faint)]">ready</span>
      </div>
    </div>
  );
}

function Spark({ data, dataKey, color }: { data: { [k: string]: number | string }[]; dataKey: string; color: string }) {
  if (!data.length) return null;
  return (
    <ResponsiveContainer width={72} height={26}>
      <AreaChart data={data} margin={{ top: 2, bottom: 2, left: 0, right: 0 }}>
        <Area type="monotone" dataKey={dataKey} stroke={color} strokeWidth={1.3} fill={color} fillOpacity={0.14} dot={false} isAnimationActive={false} />
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
    <div className="flex flex-col gap-1 px-3 py-2 rounded-lg border min-w-[96px]" style={{ borderColor: "var(--hairline)", background: "var(--bg-elevated)" }}>
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
  const modeLabel = r?.mode === "post_workout" ? "Post-workout brief" : r?.mode === "pre_workout" ? "Pre-workout plan" : null;

  return (
    <section
      id="daily-report"
      className="scroll-mt-20 rounded-xl border p-4 space-y-4"
      style={{
        borderColor: "var(--hairline-strong)",
        background: "linear-gradient(135deg, oklch(0.155 0 0) 0%, oklch(0.115 0 0) 55%, oklch(0.135 0.02 250) 100%)",
      }}
    >
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-3">
          <Eyebrow>Daily report</Eyebrow>
          {r?.training_call && (
            <span className="text-[11px] font-mono uppercase tracking-wide px-2 py-0.5 rounded" style={{ color: CALL_COLOR[r.training_call] ?? "var(--text-primary)", border: `1px solid ${CALL_COLOR[r.training_call] ?? "var(--hairline-strong)"}` }}>
              {r.training_call}
            </span>
          )}
          {modeLabel && <span className="text-[10px] font-mono text-[var(--text-muted)]">{modeLabel}</span>}
          {r && <span className="text-[10px] text-[var(--text-faint)] font-mono">{r.report_date}</span>}
        </div>
        <button onClick={copyPrompt} className="border rounded px-3 py-1 text-[11px] font-mono" style={{ borderColor: "var(--hairline-strong)" }}>
          {copied ? "copied — run in Claude Code" : "generate daily report"}
        </button>
      </div>

      {r?.readiness_headline && (
        <p className="text-[15px] font-medium leading-snug text-[var(--text-primary)] max-w-3xl">{r.readiness_headline}</p>
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
            <Stat label="ACWR" value={acwr != null ? acwr.toFixed(2) : "—"}
              tone={acwr != null && acwr > 1.5 ? "negative" : "default"} />
          </div>
        </div>
      )}

      {isLoading ? (
        <div className="h-24 shc-skeleton rounded" />
      ) : r ? (
        <div className="space-y-3">
          {r.sections.map((s, i) => (
            <div key={i} className="rounded-lg border p-3 space-y-2" style={{ borderColor: "var(--hairline)", background: "var(--bg-elevated)" }}>
              <div className="flex items-center gap-2">
                <span className="h-3 w-[2px] rounded" style={{ background: "var(--sl-accent)" }} />
                <h3 className="text-[12px] font-semibold tracking-tight text-[var(--text-primary)]">{s.title}</h3>
              </div>
              <Markdown text={s.body_md} />
            </div>
          ))}

          {r.sources && r.sources.length > 0 && (
            <div className="pt-1">
              <div className="flex items-center gap-1.5 text-[10px] font-mono uppercase tracking-wide text-[var(--text-faint)] mb-1">
                <ObsidianMark size={11} /> Vault research cited
              </div>
              <div className="flex flex-wrap">
                {r.sources.map((s) => <ObsidianSourceTag key={s} source={s} />)}
              </div>
            </div>
          )}

          <p className="text-[10px] text-[var(--text-faint)] pt-1">
            Generated {new Date(r.generated_at).toLocaleString()} · {r.model} · synced metrics + vault research
          </p>
        </div>
      ) : (
        <p className="text-[12px] text-[var(--text-faint)]">
          No report yet. Click “generate daily report”, run the prompt in Claude Code — it syncs your data,
          builds the workout, and posts one complete report back here.
        </p>
      )}
    </section>
  );
}
