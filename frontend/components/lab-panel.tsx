"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { Eyebrow } from "@/components/ui/metric";
import { BookIcon } from "@/components/ui/icons";

type Finding = Awaited<ReturnType<typeof api.labFindings>>[number];

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

function FindingCard({ f }: { f: Finding }) {
  const meta = VERDICT_META[f.verdict ?? "insufficient"] ?? VERDICT_META.insufficient;
  return (
    <div
      className="rounded-md border border-[var(--hairline)] p-3 hover:border-[var(--text-faint)] transition-colors"
      style={{
        background: meta.bg.startsWith("var")
          ? `oklch(from ${meta.bg.split("/")[0]} l c h / ${meta.bg.split("/")[1] ?? "0.05"})`
          : undefined,
      }}
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

      <p className="text-[11px] text-[var(--text-muted)] leading-snug mb-2">{f.hypothesis}</p>

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
              {f.effect_size > 0 ? "+" : ""}
              {f.effect_size}
              {f.effect_unit ? f.effect_unit : ""}
            </span>
          </span>
        )}
        {f.n != null && <span>n = {f.n}</span>}
        {f.p_value != null && (
          <span>p = {f.p_value < 0.001 ? "<.001" : f.p_value.toFixed(3)}</span>
        )}
        <span className="text-[var(--text-faint)]">{f.test_type}</span>
        {f.status === "answered" && (
          <span className="text-[var(--text-faint)]">
            answered {relativeAge(f.answered_at)} · re-checked {relativeAge(f.run_at)}
          </span>
        )}
      </div>

      {f.vault_ref && (
        <p className="mt-2 text-[10px] text-[var(--text-faint)]">
          <BookIcon size={11} className="inline mr-1 align-middle opacity-60" />
          {f.vault_ref}
        </p>
      )}
    </div>
  );
}

/** Definitive answers first — CONFIRMED above REFUTED, then everything still open. */
const ANSWER_ORDER: Record<string, number> = { confirmed: 0, refuted: 1 };

export function LabPanel() {
  const qc = useQueryClient();
  const findings = useQuery({
    queryKey: ["lab-findings"],
    queryFn: api.labFindings,
    refetchInterval: 60_000,
  });
  const runMut = useMutation({
    mutationFn: api.labRun,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["lab-findings"] }),
  });

  const all = findings.data ?? [];
  const lastRun =
    all.reduce<string | null>((acc, f) => {
      if (!f.run_at) return acc;
      if (!acc) return f.run_at;
      return f.run_at > acc ? f.run_at : acc;
    }, null) ?? null;

  // A question retires the moment it reaches a stable definitive verdict, so
  // "answered" IS the output of the program. Showing only open questions — which
  // is what this panel did — meant it could never display a conclusion.
  const answered = all
    .filter((f) => f.status === "answered")
    .sort(
      (a, b) =>
        (ANSWER_ORDER[a.verdict ?? ""] ?? 9) - (ANSWER_ORDER[b.verdict ?? ""] ?? 9),
    );
  const open = all.filter((f) => f.status !== "answered");
  const confirmedCount = answered.filter((f) => f.verdict === "confirmed").length;
  const refutedCount = answered.filter((f) => f.verdict === "refuted").length;

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

      {all.length === 0 ? (
        <p className="text-[12px] text-[var(--text-dim)] mt-4">No hypotheses registered yet.</p>
      ) : (
        <>
          {answered.length > 0 && (
            <section className="mt-4">
              <div className="flex items-baseline gap-2 mb-2">
                <h4 className="text-[10px] uppercase tracking-[0.18em] text-[var(--text-muted)]">
                  Answered
                </h4>
                <span className="text-[10px] text-[var(--text-faint)] tabular-nums">
                  {confirmedCount} confirmed · {refutedCount} refuted
                </span>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {answered.map((f) => (
                  <FindingCard key={f.id} f={f} />
                ))}
              </div>
            </section>
          )}

          <section className="mt-5">
            <div className="flex items-baseline gap-2 mb-2">
              <h4 className="text-[10px] uppercase tracking-[0.18em] text-[var(--text-muted)]">
                Under test
              </h4>
              <span className="text-[10px] text-[var(--text-faint)] tabular-nums">
                {open.length} open
              </span>
            </div>
            {open.length === 0 ? (
              <p className="text-[11.5px] text-[var(--text-dim)]">
                Every registered hypothesis has been answered — the question bank is empty.
                Register another to keep the program running.
              </p>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {open.map((f) => (
                  <FindingCard key={f.id} f={f} />
                ))}
              </div>
            )}
          </section>
        </>
      )}
    </div>
  );
}
