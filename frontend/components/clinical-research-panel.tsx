"use client";

import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";

import { api } from "@/lib/api";
import { Eyebrow, Metric } from "@/components/ui/metric";

function tone(value: number | null, good: number, bad: number, dir: "high" | "low" = "high"): "positive" | "neutral" | "negative" {
  if (value == null) return "neutral";
  if (dir === "high") {
    if (value >= good) return "positive";
    if (value <= bad) return "negative";
    return "neutral";
  }
  if (value <= good) return "positive";
  if (value >= bad) return "negative";
  return "neutral";
}

function toneColor(t: "positive" | "neutral" | "negative"): string {
  return t === "positive" ? "var(--positive)" : t === "negative" ? "var(--negative)" : "var(--text-primary)";
}

function bandColor(t: "positive" | "neutral" | "negative"): string {
  return t === "positive" ? "var(--positive)" : t === "negative" ? "var(--negative)" : "var(--neutral)";
}

type Band = { label: string; range: string; tone: "positive" | "neutral" | "negative" };

/** Visible range scale: every band labelled, the one you're in today highlighted. */
function BandScale({ bands, active }: { bands: Band[]; active: "positive" | "neutral" | "negative" }) {
  return (
    <ul className="mt-2 space-y-0.5">
      {bands.map((b) => {
        const on = b.tone === active;
        return (
          <li
            key={b.label}
            className="flex items-center gap-1.5 text-[10px] tabular-nums"
            style={{ opacity: on ? 1 : 0.38 }}
          >
            <span
              className="inline-block w-1.5 h-1.5 rounded-full shrink-0"
              style={{ background: bandColor(b.tone) }}
            />
            <span
              className="uppercase tracking-wide"
              style={{ color: on ? "var(--text-primary)" : "var(--text-muted)", fontWeight: on ? 600 : 400 }}
            >
              {b.label}
            </span>
            <span className="ml-auto text-[var(--text-dim)]">{b.range}</span>
          </li>
        );
      })}
    </ul>
  );
}

function Meaning({ children }: { children: ReactNode }) {
  return <p className="mt-1 text-[11px] text-[var(--text-muted)] leading-snug">{children}</p>;
}

/** Per-tile provenance. The panel used to carry one blanket "peer-reviewed"
 *  badge while two of six tiles cited a vendor blog and a self-published
 *  training method. Provenance is a property of the metric, not the panel. */
function SourceTag({ label, peerReviewed }: { label: string; peerReviewed: boolean }) {
  return (
    <p className="text-[10px] uppercase tracking-wider" style={{ color: peerReviewed ? "var(--text-dim)" : "var(--warning, oklch(0.75 0.18 75))" }}>
      {label}
      {!peerReviewed && " · vendor"}
    </p>
  );
}

function monthsSince(iso: string | null): number | null {
  if (!iso) return null;
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return null;
  return (Date.now() - then) / (1000 * 60 * 60 * 24 * 30.44);
}

export function ClinicalResearchPanel() {
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["clinical-research"],
    queryFn: api.clinicalResearch,
    refetchInterval: 5 * 60_000,
  });

  // An errored query must not render as a loading skeleton. React Query clears
  // isLoading on error but leaves data undefined, so the old `isLoading || !data`
  // guard showed a shimmer forever when the endpoint 500'd — which is exactly
  // what happened for the whole life of the DuckDB QUALIFY bug.
  if (isError) {
    return (
      <div className="shc-card shc-enter p-6">
        <Eyebrow>Clinical research signals</Eyebrow>
        <p className="mt-3 text-sm text-[var(--negative)]">
          Signals unavailable — {error instanceof Error ? error.message : "request failed"}.
        </p>
        <button onClick={() => refetch()} className="mt-3 text-[11px] uppercase tracking-wider underline">
          Retry
        </button>
      </div>
    );
  }

  if (isLoading || !data) {
    return (
      <div className="shc-card shc-enter p-6">
        <Eyebrow>Clinical research signals</Eyebrow>
        <div className="shc-skeleton h-[180px] mt-3" />
      </div>
    );
  }

  const sriData = data.sleep_regularity_index;
  const sri = sriData.value;
  const sriTone = tone(sri, 80, 60, "high");

  const ln = data.ln_rmssd;
  // The verdict is noise-relative, not threshold-relative: a delta inside Rob's
  // own smallest worthwhile change is neutral whatever its sign.
  const lnTone: "positive" | "neutral" | "negative" =
    ln.delta == null || ln.within_noise !== false ? "neutral" : ln.delta > 0 ? "positive" : "negative";

  const streak = data.recovery_deficit_streak.consecutive_red_days;
  const streakTone: "positive" | "neutral" | "negative" =
    streak >= 3 ? "negative" : streak >= 1 ? "neutral" : "positive";

  const alData = data.allostatic_load;
  const al = alData.score_0_10;
  const alTone = tone(al, 3, 6, "low");
  const staleMarkers = Object.entries(alData.input_dates)
    .map(([k, d]) => [k, monthsSince(d)] as const)
    .filter(([, m]) => m != null && m > 12);

  return (
    <div className="shc-card shc-enter p-6">
      <div className="flex items-baseline justify-between flex-wrap gap-3">
        <Eyebrow>Clinical research signals</Eyebrow>
        <span className="text-[10.5px] text-[var(--text-dim)] uppercase tracking-wider">
          published thresholds
        </span>
      </div>

      <div className="mt-4 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-x-5 gap-y-6">
        {/* Sleep Regularity Index */}
        <div title={sriData.ref}>
          <SourceTag label="SRI · Phillips '17" peerReviewed={sriData.peer_reviewed} />
          <Metric
            value={sri != null ? sri.toFixed(0) : "—"}
            unit={sri != null ? "/100" : undefined}
            size="lg"
            tone={sriTone}
          />
          <Meaning>
            How consistent your sleep &amp; wake times are, scored across the full 24h day
            over {sriData.n_nights} nights.
          </Meaning>
          <BandScale
            active={sriTone}
            bands={[
              { label: "Tight", range: "≥ 80", tone: "positive" },
              { label: "Fair", range: "60–79", tone: "neutral" },
              { label: "Irregular", range: "< 60", tone: "negative" },
            ]}
          />
        </div>

        {/* lnRMSSD vs personal baseline, banded by SWC */}
        <div title={ln.ref}>
          <SourceTag label="lnRMSSD · Buchheit '14" peerReviewed={ln.peer_reviewed} />
          <Metric value={ln.today != null ? ln.today.toFixed(2) : "—"} size="lg" tone={lnTone} />
          {ln.delta != null && ln.baseline_7d != null && (
            <p className="text-[10.5px] tabular-nums" style={{ color: toneColor(lnTone) }}>
              {ln.delta > 0 ? "+" : ""}
              {ln.delta.toFixed(3)} vs 7d baseline
              {ln.swc != null && (
                <span className="text-[var(--text-dim)]"> · SWC ±{ln.swc.toFixed(3)}</span>
              )}
            </p>
          )}
          {ln.within_noise === true && (
            <p className="text-[10px] uppercase tracking-wider text-[var(--text-faint)]">
              inside your noise floor
            </p>
          )}
          <Meaning>
            {"Today's HRV against your own 7-day baseline. The band is your smallest worthwhile change — half your baseline SD — not a population constant."}
          </Meaning>
          <BandScale
            active={lnTone}
            bands={[
              { label: "Adapting", range: "> +SWC", tone: "positive" },
              { label: "Within noise", range: "± SWC", tone: "neutral" },
              { label: "Fatiguing", range: "< −SWC", tone: "negative" },
            ]}
          />
        </div>

        {/* Recovery deficit streak */}
        <div title={data.recovery_deficit_streak.ref}>
          <SourceTag
            label="Red-streak · WHOOP"
            peerReviewed={data.recovery_deficit_streak.peer_reviewed}
          />
          <Metric
            value={streak.toString()}
            unit={streak === 1 ? "day" : "days"}
            size="lg"
            tone={streakTone}
          />
          <Meaning>
            Days in a row WHOOP scored you red. Vendor-defined banding — for an injury-risk
            read with literature behind it, use ACWR.
          </Meaning>
          <BandScale
            active={streakTone}
            bands={[
              { label: "Clear", range: "0 days", tone: "positive" },
              { label: "Watch", range: "1–2 days", tone: "neutral" },
              { label: "Alarm", range: "3+ days", tone: "negative" },
            ]}
          />
        </div>

        {/* Cardiometabolic load (Seeman subset) */}
        <div title={`${alData.ref} — ${alData.scope}`}>
          <SourceTag label="Cardiometabolic · Seeman '01" peerReviewed={alData.peer_reviewed} />
          <Metric
            value={al != null ? al.toFixed(1) : "—"}
            unit={al != null ? "/10" : undefined}
            size="lg"
            tone={alTone}
          />
          <Meaning>
            Cumulative “wear &amp; tear” across {alData.n_markers} markers
            ({alData.axes_covered.join(" + ")}). A subset of Seeman&apos;s index — no
            neuroendocrine or immune markers exist in this data.
          </Meaning>
          {staleMarkers.length > 0 && (
            <p className="mt-1 text-[10px] text-[oklch(0.75_0.18_75)] leading-snug">
              {staleMarkers.length} marker{staleMarkers.length > 1 ? "s" : ""} over a year old
              ({staleMarkers.map(([k]) => k).join(", ")}) — the score blends panels drawn years apart.
            </p>
          )}
          <BandScale
            active={alTone}
            bands={[
              { label: "Low", range: "≤ 3", tone: "positive" },
              { label: "Moderate", range: "4–5", tone: "neutral" },
              { label: "High", range: "≥ 6", tone: "negative" },
            ]}
          />
        </div>
      </div>
    </div>
  );
}
