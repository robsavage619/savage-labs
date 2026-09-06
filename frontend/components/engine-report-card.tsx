"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { Eyebrow, Metric } from "@/components/ui/metric";

/**
 * The engine grading itself on two different axes.
 *
 * CALIBRATION asks whether a prescribed load lands at the prescribed effort.
 * VALIDITY asks whether the readiness score relates to the session at all.
 * They are reported side by side because the answer is currently split — the
 * planner is accurate and readiness is not predictive — and either number on
 * its own tells the wrong story.
 *
 * Distinct from the `Engine self-assessment` card above it: that scores
 * per-muscle volume decisions against strength OUTCOMES, this scores
 * per-exercise effort against INTENT.
 */
export function EngineReportCard() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["engine-report-card"],
    queryFn: () => api.engineReportCard(),
    refetchInterval: 30 * 60_000,
  });

  if (isError) {
    return (
      <div className="shc-card shc-enter p-6">
        <Eyebrow>Report card</Eyebrow>
        <p className="mt-3 text-sm text-[var(--negative)]">Report card unavailable.</p>
      </div>
    );
  }
  if (isLoading || !data) {
    return (
      <div className="shc-card shc-enter p-6">
        <Eyebrow>Report card</Eyebrow>
        <div className="shc-skeleton h-[150px] mt-3" />
      </div>
    );
  }

  const cal = data.calibration;
  const val = data.predictive_validity;
  const pos = "var(--positive)";
  const neu = "var(--text-primary)";
  const neg = "var(--negative)";

  return (
    <div className="shc-card shc-enter p-6">
      <div className="flex items-baseline justify-between flex-wrap gap-3">
        <Eyebrow>Report card</Eyebrow>
        <span className="text-[10.5px] text-[var(--text-dim)] uppercase tracking-wider">
          last {Math.round(data.window_days / 30)} months
        </span>
      </div>

      <p className="mt-2 text-[12px] text-[var(--text-muted)] leading-snug">{data.summary}</p>

      <div className="mt-4 grid grid-cols-1 sm:grid-cols-2 gap-x-5 gap-y-5">
        {/* Calibration — does a prescribed load land at the prescribed effort? */}
        <div>
          <p className="text-[10px] text-[var(--text-dim)] uppercase tracking-wider">
            Prescription calibration
          </p>
          {cal.verdict === "insufficient" ? (
            <>
              <Metric value="—" size="lg" />
              <p className="mt-1 text-[11px] text-[var(--text-muted)]">
                {cal.n_matched} of {cal.n_prescribed} prescriptions matched to a logged RPE — not
                enough to grade yet.
              </p>
            </>
          ) : (
            <>
              <Metric
                value={(cal.within_target_pct ?? 0).toFixed(0)}
                unit="%"
                size="lg"
                tone={
                  (cal.within_target_pct ?? 0) >= 75
                    ? "positive"
                    : (cal.within_target_pct ?? 0) >= 55
                    ? "neutral"
                    : "negative"
                }
              />
              <p className="text-[10.5px] tabular-nums text-[var(--text-muted)]">
                within ±{cal.on_target_window_rpe} RPE of target · n={cal.n_matched}
              </p>
              <p className="mt-1 text-[11px] text-[var(--text-muted)] leading-snug">
                When the planner writes an RPE target, does the load it picked actually land there?
              </p>
              <p className="mt-1.5 text-[10.5px] tabular-nums" style={{ color: cal.verdict === "biased" ? neg : pos }}>
                bias {(cal.bias_rpe ?? 0) > 0 ? "+" : ""}
                {(cal.bias_rpe ?? 0).toFixed(2)} RPE
                <span className="text-[var(--text-dim)]">
                  {" "}
                  [{cal.bias_ci95?.[0].toFixed(2)}, {cal.bias_ci95?.[1].toFixed(2)}] ·{" "}
                  {cal.verdict === "biased" ? "systematic" : "unbiased"}
                </span>
              </p>
              <p className="mt-0.5 text-[10px] text-[var(--text-faint)] tabular-nums">
                {cal.harder_than_programmed_pct}% ran harder · {cal.easier_than_programmed_pct}% easier
              </p>
            </>
          )}
        </div>

        {/* Validity — does readiness relate to the session at all? */}
        <div>
          <p className="text-[10px] text-[var(--text-dim)] uppercase tracking-wider">
            Readiness predictive validity
          </p>
          <Metric
            value={val.informative ? "yes" : val.verdict === "insufficient" ? "—" : "none"}
            size="lg"
            tone={val.informative ? "positive" : "neutral"}
          />
          <p className="text-[10.5px] tabular-nums text-[var(--text-muted)]">
            n={val.n} training days
          </p>
          <p className="mt-1 text-[11px] text-[var(--text-muted)] leading-snug">
            Does the morning readiness score relate to the session that follows?
          </p>
          <ul className="mt-2 space-y-0.5">
            {Object.entries(val.correlations).map(([k, c]) => (
              <li key={k} className="flex items-center gap-1.5 text-[10px] tabular-nums">
                <span
                  className="inline-block w-1.5 h-1.5 rounded-full shrink-0"
                  style={{ background: c.excludes_zero ? pos : "var(--neutral)" }}
                />
                <span className="uppercase tracking-wide text-[var(--text-muted)]">
                  {k.replace(/_/g, " ")}
                </span>
                <span className="ml-auto" style={{ color: c.excludes_zero ? pos : neu }}>
                  {c.r != null ? (c.r > 0 ? "+" : "") + c.r.toFixed(2) : "—"}
                </span>
                <span className="text-[var(--text-dim)] w-[76px] text-right">
                  [{c.ci95[0]}, {c.ci95[1]}]
                </span>
              </li>
            ))}
          </ul>
          {!val.informative && val.caveat && (
            <p className="mt-1.5 text-[10px] text-[var(--text-faint)] leading-snug">{val.caveat}</p>
          )}
        </div>
      </div>
    </div>
  );
}
