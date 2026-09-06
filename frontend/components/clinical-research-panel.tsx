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

export function ClinicalResearchPanel() {
  const { data, isLoading } = useQuery({
    queryKey: ["clinical-research"],
    queryFn: api.clinicalResearch,
    refetchInterval: 5 * 60_000,
  });

  if (isLoading || !data) {
    return (
      <div className="shc-card shc-enter p-6">
        <Eyebrow>Clinical research signals</Eyebrow>
        <div className="shc-skeleton h-[180px] mt-3" />
      </div>
    );
  }

  const sri = data.sleep_regularity_index.value;
  const sriTone = tone(sri, 80, 60, "high");
  const ln = data.ln_rmssd;
  const lnTone = tone(ln.delta, 0.05, -0.05, "high");
  const streak = data.recovery_deficit_streak.consecutive_red_days;
  const streakTone: "positive" | "neutral" | "negative" =
    streak >= 3 ? "negative" : streak >= 1 ? "neutral" : "positive";
  const al = data.allostatic_load.score_0_10;
  const alTone = tone(al, 3, 6, "low");
  const drugs = data.hrv_drug_adjusted;
  const z2cv = data.z2_hr_consistency.cv_pct;
  const z2Tone = tone(z2cv, 4, 7, "low");

  return (
    <div className="shc-card shc-enter p-6">
      <div className="flex items-baseline justify-between flex-wrap gap-3">
        <Eyebrow>Clinical research signals</Eyebrow>
        <span className="text-[10.5px] text-[var(--text-dim)] uppercase tracking-wider">
          peer-reviewed
        </span>
      </div>

      <div className="mt-4 grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-x-5 gap-y-6">
        {/* Sleep Regularity Index */}
        <div title={data.sleep_regularity_index.ref}>
          <p className="text-[10px] text-[var(--text-dim)] uppercase tracking-wider">{"SRI · Phillips '17"}</p>
          <Metric
            value={sri != null ? sri.toFixed(0) : "—"}
            unit={sri != null ? "/100" : undefined}
            size="lg"
            tone={sriTone}
          />
          <Meaning>How consistent your sleep & wake times are, night to night.</Meaning>
          <BandScale
            active={sriTone}
            bands={[
              { label: "Tight", range: "≥ 80", tone: "positive" },
              { label: "Fair", range: "60–79", tone: "neutral" },
              { label: "Irregular", range: "< 60", tone: "negative" },
            ]}
          />
        </div>

        {/* lnRMSSD */}
        <div title={data.ln_rmssd.ref}>
          <p className="text-[10px] text-[var(--text-dim)] uppercase tracking-wider">{"lnRMSSD · Buchheit '14"}</p>
          <Metric value={ln.today != null ? ln.today.toFixed(2) : "—"} size="lg" tone={lnTone} />
          {ln.delta != null && ln.avg_4w != null && (
            <p className="text-[10.5px] tabular-nums" style={{ color: toneColor(lnTone) }}>
              {ln.delta > 0 ? "+" : ""}{ln.delta.toFixed(2)} vs 4w avg
            </p>
          )}
          <Meaning>{"Today's HRV vs your 4-week norm — the trend separates fitness gains from accumulating fatigue."}</Meaning>
          <BandScale
            active={lnTone}
            bands={[
              { label: "Adapting", range: "≥ +0.05", tone: "positive" },
              { label: "Steady", range: "± 0.05", tone: "neutral" },
              { label: "Fatiguing", range: "≤ −0.05", tone: "negative" },
            ]}
          />
        </div>

        {/* Recovery deficit streak */}
        <div title={data.recovery_deficit_streak.ref}>
          <p className="text-[10px] text-[var(--text-dim)] uppercase tracking-wider">{"Red-streak · WHOOP '22"}</p>
          <Metric
            value={streak.toString()}
            unit={streak === 1 ? "day" : "days"}
            size="lg"
            tone={streakTone}
          />
          <Meaning>Days in a row WHOOP scored you red (under-recovered). 3+ ≈ double the soft-tissue injury risk.</Meaning>
          <BandScale
            active={streakTone}
            bands={[
              { label: "Clear", range: "0 days", tone: "positive" },
              { label: "Watch", range: "1–2 days", tone: "neutral" },
              { label: "Alarm", range: "3+ days", tone: "negative" },
            ]}
          />
        </div>

        {/* Allostatic load */}
        <div title={data.allostatic_load.ref}>
          <p className="text-[10px] text-[var(--text-dim)] uppercase tracking-wider">{"Allostatic load · Seeman '01"}</p>
          <Metric
            value={al != null ? al.toFixed(1) : "—"}
            unit={al != null ? "/10" : undefined}
            size="lg"
            tone={alTone}
          />
          <Meaning>
            Cumulative “wear &amp; tear” from chronic stress, scored across {data.allostatic_load.n_markers} body markers.
          </Meaning>
          <BandScale
            active={alTone}
            bands={[
              { label: "Low", range: "≤ 3", tone: "positive" },
              { label: "Moderate", range: "4–5", tone: "neutral" },
              { label: "High", range: "≥ 6", tone: "negative" },
            ]}
          />
        </div>

        {/* Drug-adjusted HRV */}
        <div title={drugs.ref}>
          <p className="text-[10px] text-[var(--text-dim)] uppercase tracking-wider">{"Adj. HRV · Kemp '10"}</p>
          {drugs.adjusted != null ? (
            <>
              <Metric value={drugs.adjusted.toFixed(0)} unit="ms" size="lg" />
              {drugs.raw != null && drugs.factor !== 1 && (
                <p className="text-[10.5px] text-[var(--text-muted)] tabular-nums">
                  raw {drugs.raw.toFixed(0)}ms · ×{drugs.factor.toFixed(2)}
                </p>
              )}
              {drugs.active_drugs.length > 0 && (
                <p className="text-[10px] text-[var(--text-faint)] uppercase tracking-wider">
                  {drugs.active_drugs.join(" · ")}
                </p>
              )}
              <Meaning>
                Your HRV with the propranolol/SSRI dampening factored back out — a truer read of autonomic recovery.
              </Meaning>
            </>
          ) : (
            <>
              <Metric value="—" size="lg" />
              <Meaning>HRV corrected for HRV-suppressing meds. Shows a value only on days such a drug is active.</Meaning>
            </>
          )}
        </div>

        {/* Z2 HR drift */}
        <div title={data.z2_hr_consistency.ref}>
          <p className="text-[10px] text-[var(--text-dim)] uppercase tracking-wider">Z2 HR drift · Maffetone</p>
          <Metric
            value={z2cv != null ? z2cv.toFixed(1) : "—"}
            unit={z2cv != null ? "%CV" : undefined}
            size="lg"
            tone={z2Tone}
          />
          <Meaning>How steady your heart rate holds during easy Zone-2 cardio — a gauge of aerobic-base quality.</Meaning>
          <BandScale
            active={z2Tone}
            bands={[
              { label: "Stable", range: "≤ 4%", tone: "positive" },
              { label: "Drifting", range: "5–7%", tone: "neutral" },
              { label: "Unstable", range: "> 7%", tone: "negative" },
            ]}
          />
        </div>
      </div>
    </div>
  );
}
