"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookIcon } from "@/components/ui/icons";
import { api, type ExperimentSuggestion } from "@/lib/api";
import { Eyebrow } from "@/components/ui/metric";

export function SuggestedExperiments() {
  const qc = useQueryClient();
  const suggestions = useQuery({
    queryKey: ["experiment-suggestions"],
    queryFn: api.experimentSuggestions,
    refetchInterval: 5 * 60_000,
  });

  const registerMut = useMutation({
    mutationFn: async (s: ExperimentSuggestion) => {
      const r = await fetch(`${process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000"}/api/experiments`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(process.env.NEXT_PUBLIC_SHC_KEY
            ? { "X-SHC-Key": process.env.NEXT_PUBLIC_SHC_KEY }
            : {}),
        },
        body: JSON.stringify({
          slug: s.slug,
          hypothesis: s.hypothesis,
          manipulated: s.manipulated,
          condition_a: s.condition_a,
          condition_b: s.condition_b,
          outcome_metric: s.outcome_metric,
          outcome_direction: s.outcome_direction,
          min_per_arm: s.min_per_arm,
          min_effect: s.min_effect,
        }),
      });
      if (!r.ok) throw new Error(`register ${r.status}`);
      return r.json();
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["experiments"] });
      qc.invalidateQueries({ queryKey: ["experiment-suggestions"] });
    },
  });

  const data = suggestions.data ?? [];

  if (suggestions.isLoading) return null;
  if (data.length === 0) return null;

  return (
    <div className="shc-card shc-enter p-5">
      <Eyebrow>Suggested studies · derived from standing research</Eyebrow>
      <p className="text-[10.5px] text-[var(--text-dim)] mt-0.5">
        Unresolved lab findings with a controllable behavioral exposure — candidates for a
        pre-registered n-of-1 trial. Registering locks the hypothesis and design before any data
        is seen.
      </p>

      <div className="mt-4 space-y-3">
        {data.map((s) => (
          <div
            key={s.slug}
            className="rounded-md border border-[var(--hairline)] p-3 hover:border-[var(--text-faint)] transition-colors"
          >
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <p className="text-[12px] font-medium text-[var(--text-primary)] leading-snug mb-1">
                  {s.hypothesis}
                </p>
                <p className="text-[11px] text-[var(--text-muted)] leading-snug">
                  <span className="text-[var(--text-dim)]">A</span> {s.condition_a}
                  {"  ·  "}
                  <span className="text-[var(--text-dim)]">B</span> {s.condition_b}
                </p>
                {s.vault_ref && (
                  <p className="text-[10px] text-[var(--text-faint)] mt-1">
                    <BookIcon size={10} className="inline mr-1 align-middle opacity-60" />
                    {s.vault_ref}
                  </p>
                )}
              </div>
              <button
                onClick={() => registerMut.mutate(s)}
                disabled={registerMut.isPending}
                className="shrink-0 text-[10px] uppercase tracking-wider px-2.5 py-1 rounded border border-[var(--hairline)] text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:border-[var(--text-faint)] disabled:opacity-50"
              >
                Register
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
