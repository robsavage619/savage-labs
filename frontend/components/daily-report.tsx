"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Eyebrow } from "@/components/ui/metric";

const CALL_COLOR: Record<string, string> = {
  Push: "var(--sl-accent)",
  Train: "var(--positive)",
  Maintain: "var(--text-primary)",
  Easy: "var(--text-muted)",
  Rest: "var(--negative)",
};

export function DailyReport() {
  const { data, isLoading } = useQuery({
    queryKey: ["daily-report"],
    queryFn: () => api.dailyReport(),
    refetchInterval: 300_000,
  });
  const [copied, setCopied] = useState(false);

  const copyPrompt = async () => {
    const { prompt } = await api.dailyReportPrompt();
    await navigator.clipboard.writeText(prompt);
    setCopied(true);
    setTimeout(() => setCopied(false), 2500);
  };

  const r = data?.report;

  return (
    <section
      id="daily-report"
      className="scroll-mt-20 rounded-xl border p-4 space-y-3"
      style={{ borderColor: "var(--hairline-strong)", background: "var(--card-hover)" }}
    >
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-baseline gap-3">
          <Eyebrow>Daily report</Eyebrow>
          {r?.training_call && (
            <span
              className="text-[11px] font-mono uppercase tracking-wide px-2 py-0.5 rounded"
              style={{ color: CALL_COLOR[r.training_call] ?? "var(--text-primary)", border: "1px solid var(--hairline-strong)" }}
            >
              {r.training_call}
            </span>
          )}
          {r && (
            <span className="text-[10px] text-[var(--text-faint)] font-mono">
              {r.report_date}
            </span>
          )}
        </div>
        <button
          onClick={copyPrompt}
          className="border rounded px-3 py-1 text-[11px] font-mono"
          style={{ borderColor: "var(--hairline-strong)" }}
        >
          {copied ? "copied — run in Claude Code" : "generate daily report"}
        </button>
      </div>

      {r?.readiness_headline && (
        <p className="text-[13px] text-[var(--text-primary)] leading-snug">{r.readiness_headline}</p>
      )}

      {isLoading ? (
        <div className="h-24 shc-skeleton rounded" />
      ) : r ? (
        <div className="space-y-3">
          {r.sections.map((s, i) => (
            <div key={i} className="space-y-1">
              <span className="text-[9.5px] font-mono uppercase tracking-wide" style={{ color: "var(--sl-accent)" }}>
                {s.title}
              </span>
              <p className="whitespace-pre-wrap text-[12px] leading-relaxed text-[var(--text-primary)]">
                {s.body_md}
              </p>
            </div>
          ))}
        </div>
      ) : (
        <p className="text-[12px] text-[var(--text-faint)]">
          No report yet. Click “generate daily report”, run the prompt in Claude Code — it pulls
          everything (readiness, training, body composition) and posts one complete report back here.
        </p>
      )}
    </section>
  );
}
