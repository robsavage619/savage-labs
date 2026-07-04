"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, type Experiment } from "@/lib/api";
import { Eyebrow } from "@/components/ui/metric";

const VERDICT: Record<string, { color: string; label: string }> = {
  CONFIRMED: { color: "var(--positive)", label: "CONFIRMED" },
  REFUTED: { color: "var(--negative)", label: "REFUTED" },
  INCONCLUSIVE: { color: "var(--neutral)", label: "INCONCLUSIVE" },
  INSUFFICIENT_N: { color: "var(--text-muted)", label: "INSUFFICIENT N" },
};

function ArmProgress({ label, arm, need }: { label: string; arm?: Experiment["arms"][string]; need: number }) {
  const adhered = arm?.adhered ?? 0;
  const pct = Math.min(100, (adhered / Math.max(1, need)) * 100);
  return (
    <div className="flex-1 min-w-0">
      <div className="flex items-baseline justify-between text-[10px] text-[var(--text-dim)] mb-1">
        <span className="truncate">{label}</span>
        <span className="tabular-nums shrink-0">
          {adhered}/{need}
        </span>
      </div>
      <div className="h-1 rounded-full bg-[var(--hairline)] overflow-hidden">
        <div className="h-full rounded-full bg-[var(--text-muted)]" style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

export function LabExperiments() {
  const qc = useQueryClient();
  const exps = useQuery({ queryKey: ["experiments"], queryFn: api.experiments, refetchInterval: 60_000 });
  const [todayArm, setTodayArm] = useState<Record<string, string>>({});

  const logMut = useMutation({
    mutationFn: (slug: string) => api.experimentLog(slug, { adhered: true }),
    onSuccess: (r) => {
      setTodayArm((m) => ({ ...m, [r.slug]: r.assigned_arm }));
      qc.invalidateQueries({ queryKey: ["experiments"] });
    },
  });
  const scoreMut = useMutation({
    mutationFn: (slug: string) => api.experimentScore(slug),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["experiments"] }),
  });

  const data = exps.data ?? [];

  return (
    <div className="shc-card shc-enter p-5">
      <div className="flex items-baseline justify-between flex-wrap gap-3">
        <div>
          <Eyebrow>Self-experiments · n-of-1, pre-registered</Eyebrow>
          <p className="text-[10.5px] text-[var(--text-dim)] mt-0.5">
            Designed single-subject trials — you manipulate one variable, a balanced randomized
            design isolates the causal effect. Confirmed effects feed the engine.
          </p>
        </div>
      </div>

      {data.length === 0 ? (
        <p className="text-[12px] text-[var(--text-dim)] mt-4">
          No studies registered yet. Register one via the API / chat (pre-registration locks the
          hypothesis, design, and analysis before any data is seen), then log adherence here daily.
        </p>
      ) : (
        <div className="mt-4 space-y-3">
          {data.map((e) => {
            const meta = e.result ? VERDICT[e.result.verdict] : null;
            const r = e.result;
            return (
              <div
                key={e.id}
                className="rounded-md border border-[var(--hairline)] p-3 hover:border-[var(--text-faint)] transition-colors"
              >
                <div className="flex items-start justify-between gap-2 mb-1.5">
                  <h3 className="text-[12.5px] font-medium text-[var(--text-primary)] leading-snug">
                    {e.hypothesis}
                  </h3>
                  {meta && (
                    <span
                      className="text-[9.5px] uppercase tracking-[0.12em] px-1.5 py-0.5 rounded shrink-0"
                      style={{ color: meta.color, border: `1px solid ${meta.color}40` }}
                    >
                      {meta.label}
                    </span>
                  )}
                </div>

                <p className="text-[11px] text-[var(--text-muted)] leading-snug mb-2">
                  <span className="text-[var(--text-dim)]">A</span> {e.condition_a}
                  {"  ·  "}
                  <span className="text-[var(--text-dim)]">B</span> {e.condition_b}
                  {"  ·  "}
                  <span className="text-[var(--text-faint)]">{e.outcome_metric}</span>
                </p>

                <div className="flex items-center gap-4 mb-2">
                  <ArmProgress label={`A · ${e.condition_a}`} arm={e.arms.A} need={e.min_per_arm} />
                  <ArmProgress label={`B · ${e.condition_b}`} arm={e.arms.B} need={e.min_per_arm} />
                </div>

                {r && r.effect != null && (
                  <p className="text-[11.5px] text-[var(--text-primary)] leading-snug mb-2 tabular-nums">
                    effect{" "}
                    <span style={{ color: meta?.color }}>
                      {r.effect > 0 ? "+" : ""}
                      {r.effect}
                    </span>
                    {r.effect_ci_low != null && r.effect_ci_high != null && (
                      <span className="text-[var(--text-dim)]">
                        {"  "}95% CI [{r.effect_ci_low}, {r.effect_ci_high}]
                      </span>
                    )}
                    {r.p_value != null && (
                      <span className="text-[var(--text-dim)]">
                        {"  "}p = {r.p_value < 0.001 ? "<.001" : r.p_value.toFixed(3)}
                      </span>
                    )}
                  </p>
                )}

                {e.prior && (
                  <p className="text-[10.5px] mb-2" style={{ color: "var(--positive)" }}>
                    → active engine prior: {e.prior.key} {e.prior.effect > 0 ? "+" : ""}
                    {e.prior.effect}%
                  </p>
                )}

                <div className="flex items-center gap-2 flex-wrap pt-1">
                  <button
                    onClick={() => logMut.mutate(e.slug)}
                    disabled={logMut.isPending}
                    className="text-[10px] uppercase tracking-wider px-2.5 py-1 rounded border border-[var(--hairline)] text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:border-[var(--text-faint)] disabled:opacity-50"
                  >
                    Log today
                  </button>
                  <button
                    onClick={() => scoreMut.mutate(e.slug)}
                    disabled={scoreMut.isPending}
                    className="text-[10px] uppercase tracking-wider px-2.5 py-1 rounded bg-[var(--text-primary)] text-[var(--bg)] disabled:opacity-50 hover:opacity-90"
                  >
                    {scoreMut.isPending ? "scoring…" : "Score"}
                  </button>
                  {todayArm[e.slug] && (
                    <span className="text-[10px] text-[var(--text-dim)]">
                      today assigned:{" "}
                      <span className="text-[var(--text-primary)]">
                        {todayArm[e.slug]} ·{" "}
                        {todayArm[e.slug] === "B" ? e.condition_b : e.condition_a}
                      </span>
                    </span>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      <p className="mt-4 pt-3 text-[10.5px] text-[var(--text-dim)] leading-snug border-t border-[var(--hairline)]">
        <span className="text-[var(--text-muted)]">How to read this. </span>
        Each study is pre-registered — hypothesis, design, and the smallest effect worth acting on
        are fixed before any data is seen. Your daily arm is assigned by a balanced randomized
        schedule you can&apos;t game. &quot;Log today&quot; records adherence (and reveals today&apos;s
        arm); &quot;Score&quot; pulls the outcome from your training data and reports an effect with a
        95% CI, N-gated. A CONFIRMED study writes a causal prior the plan can lean on.
      </p>
    </div>
  );
}
