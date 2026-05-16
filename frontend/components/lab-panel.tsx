"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { Eyebrow } from "@/components/ui/metric";
import { BookIcon } from "@/components/ui/icons";

const VERDICT_META: Record<string, { color: string; label: string; bg: string }> = {
  confirmed: { color: "var(--positive)", label: "CONFIRMED", bg: "var(--positive)/0.08" },
  refuted: { color: "var(--negative)", label: "REFUTED", bg: "var(--negative)/0.08" },
  insufficient: { color: "var(--text-muted)", label: "INSUFFICIENT N", bg: "var(--hairline)" },
  inconclusive: { color: "var(--neutral)", label: "INCONCLUSIVE", bg: "var(--neutral)/0.05" },
};

function relativeAge(iso: string | null): string {
  if (!iso) return "never run";
  const t = new Date(iso).getTime();
  const days = (Date.now() - t) / 86400000;
  if (days < 1) return "today";
  if (days < 2) return "yesterday";
  return `${Math.floor(days)}d ago`;
}

export function LabPanel() {
  const qc = useQueryClient();
  const findings = useQuery({ queryKey: ["lab-findings"], queryFn: api.labFindings, refetchInterval: 60_000 });
  const runMut = useMutation({
    mutationFn: api.labRun,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["lab-findings"] }),
  });

  const lastRun = findings.data?.reduce<string | null>((acc, f) => {
    if (!f.run_at) return acc;
    if (!acc) return f.run_at;
    return f.run_at > acc ? f.run_at : acc;
  }, null) ?? null;

  return (
    <div className="shc-card shc-enter p-5">
      <div className="flex items-baseline justify-between flex-wrap gap-3">
        <div>
          <Eyebrow>Research Lab · pre-registered hypotheses</Eyebrow>
          <p className="text-[10.5px] text-[var(--text-dim)] mt-0.5">
            Each test is fixed in advance — only the data moves. Vault provides the methodology.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-[10.5px] text-[var(--text-dim)] tabular-nums">
            last run · {relativeAge(lastRun)}
          </span>
          <button
            onClick={() => runMut.mutate()}
            disabled={runMut.isPending}
            className="text-[10px] uppercase tracking-wider px-3 py-1.5 rounded bg-[var(--text-primary)] text-[var(--bg)] disabled:opacity-50 hover:opacity-90"
          >
            {runMut.isPending ? "running…" : "run all"}
          </button>
        </div>
      </div>

      {!findings.data || findings.data.length === 0 ? (
        <p className="text-[12px] text-[var(--text-dim)] mt-4">No hypotheses registered yet.</p>
      ) : (
        <div className="mt-4 grid grid-cols-1 md:grid-cols-2 gap-3">
          {findings.data.map((f) => {
            const meta = VERDICT_META[f.verdict ?? "insufficient"] ?? VERDICT_META.insufficient;
            return (
              <div
                key={f.id}
                className="rounded-md border border-[var(--hairline)] p-3 hover:border-[var(--text-faint)] transition-colors"
                style={{ background: meta.bg.startsWith("var") ? `oklch(from ${meta.bg.split("/")[0]} l c h / ${meta.bg.split("/")[1] ?? "0.05"})` : undefined }}
              >
                <div className="flex items-start justify-between gap-2 mb-1.5">
                  <h3 className="text-[12.5px] font-medium text-[var(--text-primary)] leading-snug">
                    {f.title}
                  </h3>
                  <span
                    className="text-[9.5px] uppercase tracking-[0.12em] px-1.5 py-0.5 rounded shrink-0"
                    style={{ color: meta.color, border: `1px solid ${meta.color}40` }}
                  >
                    {meta.label}
                  </span>
                </div>

                <p className="text-[11px] text-[var(--text-muted)] leading-snug mb-2">
                  {f.hypothesis}
                </p>

                {f.summary && (
                  <p className="text-[11.5px] text-[var(--text-primary)] leading-snug mb-2 italic">
                    {f.summary}
                  </p>
                )}

                <div className="flex items-center gap-3 text-[10.5px] text-[var(--text-dim)] tabular-nums flex-wrap">
                  {f.effect_size != null && (
                    <span>
                      effect{" "}
                      <span style={{ color: meta.color }}>
                        {f.effect_size > 0 ? "+" : ""}{f.effect_size}
                        {f.effect_unit ? f.effect_unit : ""}
                      </span>
                    </span>
                  )}
                  {f.n != null && <span>n = {f.n}</span>}
                  {f.p_value != null && <span>p = {f.p_value < 0.001 ? "<.001" : f.p_value.toFixed(3)}</span>}
                  <span className="text-[var(--text-faint)]">{f.test_type}</span>
                </div>

                {f.vault_ref && (
                  <p className="mt-2 text-[10px] text-[var(--text-faint)]">
                    <BookIcon size={11} className="inline mr-1 align-middle opacity-60" />{f.vault_ref}
                  </p>
                )}
              </div>
            );
          })}
        </div>
      )}

      <p className="mt-4 pt-3 text-[10.5px] text-[var(--text-dim)] leading-snug border-t border-[var(--hairline)]">
        <span className="text-[var(--text-muted)]">How to read this. </span>
        Each card is a question registered in advance — the test type and threshold are fixed
        before looking at the data, so you can't p-hack. Verdict is one of CONFIRMED (effect
        meets threshold and direction), REFUTED (effect runs the wrong way), INCONCLUSIVE
        (right direction but small effect), or INSUFFICIENT N (need more days). Run weekly via
        cron or hit "run all" to refresh on demand.
      </p>
    </div>
  );
}
