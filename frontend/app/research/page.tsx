"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { ConsoleShell } from "@/components/console/shell";

/**
 * RESEARCH — what the system has learned about this particular body.
 *
 * The audit's worst finding lived here: /lab rendered as seven collapsed grey
 * rows, so the n-of-1 trials, the engine's own accuracy and the HRV
 * correlations — the most interesting things the system knows — were
 * indistinguishable from empty. All of it is on the page now.
 */

const VERDICT_COPY: Record<string, { label: string; tone: "ok" | "warn" | "dim" }> = {
  CONFIRMED: { label: "Confirmed", tone: "ok" },
  REFUTED: { label: "Ruled out", tone: "dim" },
  INCONCLUSIVE: { label: "No clear effect", tone: "dim" },
  INSUFFICIENT_N: { label: "Still collecting", tone: "warn" },
  confirmed: { label: "Confirmed", tone: "ok" },
  refuted: { label: "Ruled out", tone: "dim" },
  inconclusive: { label: "No clear effect", tone: "dim" },
  insufficient: { label: "Still collecting", tone: "warn" },
};

const TONE_VAR = { ok: "var(--ok)", warn: "var(--warn)", dim: "var(--c-dim)" } as const;

/** "hrv_next_morning" → "hrv next morning" */
const human = (k: string) => k.replace(/_/g, " ").trim();

/**
 * What to say about a trial, in plain English, from the structured fields.
 *
 * An n-of-1 trial is mostly waiting, so the useful sentence is almost always
 * "how much longer" rather than "what did we find".
 */
function trialRead(
  e: { min_per_arm: number; result: { verdict: string; effect: number | null } | null },
  a: number,
  b: number,
  pct: number,
): string {
  const r = e.result;
  const need = e.min_per_arm;

  if (r && (r.verdict === "CONFIRMED" || r.verdict === "REFUTED") && r.effect != null) {
    const dir = r.effect > 0 ? "better" : "worse";
    return r.verdict === "CONFIRMED"
      ? `Across ${a} days on and ${b} days off it came out ${Math.abs(r.effect).toFixed(1)} ${dir} when you did it — enough to trust.`
      : `Across ${a} days on and ${b} days off it made no real difference to you, whatever it does on average for other people.`;
  }

  if (a === 0 && b === 0) {
    return `Nothing logged on either side yet. It needs ${need} days of each before the answer means anything.`;
  }

  const short = Math.max(need - a, need - b);
  return `${a} days on, ${b} days off — ${pct}% of the way there. About ${short} more ${short === 1 ? "day" : "days"} on the thinner side before this can be called.`;
}

export default function ResearchPage() {
  const experiments = useQuery({ queryKey: ["experiments"], queryFn: api.experiments, staleTime: 60_000 });
  const findings = useQuery({ queryKey: ["lab-findings"], queryFn: api.labFindings, staleTime: 60_000 });
  const learning = useQuery({ queryKey: ["self-learning"], queryFn: api.trainingSelfLearning, staleTime: 60_000 });
  const correlations = useQuery({ queryKey: ["correlations"], queryFn: api.insightsCorrelations, staleTime: 60_000 });

  const L = learning.data;
  const acc = L?.prescription_accuracy;
  const personalised = L?.volume_landmarks?.filter((v) => v.source !== "population").length ?? 0;
  const totalLandmarks = L?.volume_landmarks?.length ?? 0;

  const confirmed = (findings.data ?? []).filter((f) => f.verdict === "confirmed");
  const other = (findings.data ?? []).filter((f) => f.verdict !== "confirmed").slice(0, 4);

  const ranked = [...(correlations.data ?? [])]
    .filter((c) => c.hrv_delta != null)
    .sort((a, b) => Math.abs(b.hrv_delta ?? 0) - Math.abs(a.hrv_delta ?? 0))
    .slice(0, 6);

  return (
    <ConsoleShell>
      <div className="cx-grid">
        {/* ── how well the engine knows Rob ── */}
        <div className="cx-rule" style={{ marginTop: 0 }}>
          How well this system knows you
        </div>

        <section className="cx-card">
          <header className="cx-head">
            <h3 className="cx-label">Prescription accuracy</h3>
            <span className="cx-status" style={{ color: "var(--c-dim)" }}>
              {acc?.n_scored ?? 0} scored
            </span>
          </header>
          <div className="cx-value">
            {acc?.overall != null ? `${Math.round(acc.overall * 100)}` : "—"}
            <span className="cx-unit">%</span>
          </div>
          <p className="cx-read">
            {acc?.overall != null
              ? `When the engine prescribes a weight, it lands where it intended about ${Math.round(acc.overall * 100)}% of the time, measured across ${acc.n_scored} scored sessions.`
              : "No scored sessions yet, so the engine cannot say how well its prescriptions land."}
          </p>
        </section>

        <section className="cx-card">
          <header className="cx-head">
            <h3 className="cx-label">Volume targets</h3>
            <span className="cx-status" style={{ color: "var(--c-dim)" }}>
              {personalised}/{totalLandmarks}
            </span>
          </header>
          <div className="cx-value">
            {personalised}
            <span className="cx-unit">of {totalLandmarks}</span>
          </div>
          <p className="cx-read">
            {personalised} of your {totalLandmarks} muscles now have set targets fitted from your own
            response rather than borrowed from population averages. The rest still use the textbook
            numbers until you give them enough history.
          </p>
        </section>

        <section className="cx-card">
          <header className="cx-head">
            <h3 className="cx-label">Load bands</h3>
            <span
              className="cx-status"
              style={{ color: L?.acwr_bands.source === "personal" ? "var(--ok)" : "var(--warn)" }}
            >
              {L?.acwr_bands.source ?? "—"}
            </span>
          </header>
          <div className="cx-value">
            {L?.acwr_bands.sample_weeks ?? "—"}
            <span className="cx-unit">weeks</span>
          </div>
          <p className="cx-read">
            {L?.acwr_bands.source === "personal"
              ? `The safe-load range is fitted to ${L.acwr_bands.sample_weeks} weeks of your own training rather than a published average.`
              : "The safe-load range is still the published population default — it has not seen enough of your history to fit your own."}
          </p>
        </section>

        <section className="cx-card">
          <header className="cx-head">
            <h3 className="cx-label">Deload trigger</h3>
            <span
              className="cx-status"
              style={{
                color: L?.deload_calibration.status === "fitted" ? "var(--ok)" : "var(--warn)",
              }}
            >
              {L?.deload_calibration.status === "fitted" ? "yours" : "default"}
            </span>
          </header>
          <div className="cx-value">
            {L?.deload_calibration.threshold != null
              ? L.deload_calibration.threshold.toFixed(2)
              : (L?.deload_calibration.population_threshold?.toFixed(2) ?? "—")}
          </div>
          <p className="cx-read">
            {L?.deload_calibration.status === "fitted"
              ? `Fitted from ${L.deload_calibration.n_events} of your own deload events.`
              : "Still the population default — not yet enough of your own deload events to personalise it. Treat it as a rule of thumb, not a finding about you."}
          </p>
        </section>

        {/* ── n-of-1 trials ── */}
        <div className="cx-rule">Trials running on you</div>
        {(experiments.data ?? []).length === 0 && (
          <section className="cx-card" style={{ gridColumn: "span 2" }}>
            <h3 className="cx-label">No trials registered</h3>
            <p className="cx-read">
              Register one behaviour change and the system will measure whether it actually moves
              anything for you, rather than whether it works on average for other people.
            </p>
          </section>
        )}
        {(experiments.data ?? []).slice(0, 4).map((e) => {
          const a = e.arms.A?.adhered ?? 0;
          const b = e.arms.B?.adhered ?? 0;
          const pct = Math.min(100, Math.round((Math.min(a, b) / Math.max(1, e.min_per_arm)) * 100));
          const v = e.result?.verdict ? VERDICT_COPY[e.result.verdict] : undefined;
          return (
            <section className="cx-card" key={e.id} style={{ gridColumn: "span 2" }}>
              <header className="cx-head">
                <h3 className="cx-label">{human(e.manipulated)}</h3>
                <span className="cx-status" style={{ color: TONE_VAR[v?.tone ?? "dim"] }}>
                  {v?.label ?? "Running"}
                </span>
              </header>
              {/* Deliberately NOT e.result.summary. That field is engine-voice
                  ("Only 0/0 adhered 1 pickleball session in 3 days/2 pickleball
                  sessions in 3 days days with an outcome"), and rendering it
                  here would repeat the rationale mistake on a board whose whole
                  premise is plain English. Everything needed to say it properly
                  is already in the structured fields. */}
              <p className="cx-read" style={{ marginTop: 2 }}>
                Testing whether <strong style={{ color: "var(--c-ink)" }}>{human(e.manipulated)}</strong>{" "}
                changes <strong style={{ color: "var(--c-ink)" }}>{human(e.outcome_metric)}</strong>.{" "}
                {trialRead(e, a, b, pct)}
              </p>
              <div className="cx-band-wrap">
                <div className="cx-band" style={{ background: "var(--c-surface-2)" }}>
                  <div
                    style={{
                      position: "absolute",
                      inset: 0,
                      width: `${pct}%`,
                      background: pct >= 100 ? "var(--ok)" : "var(--c-accent)",
                      borderRadius: 2,
                    }}
                  />
                </div>
                <div className="cx-band-labels">
                  <span>started {e.started_on}</span>
                  <span>{pct}% of sample</span>
                </div>
              </div>
            </section>
          );
        })}

        {/* ── findings ── */}
        <div className="cx-rule">What has actually been shown</div>
        {confirmed.length === 0 && other.length === 0 && (
          <section className="cx-card" style={{ gridColumn: "1 / -1" }}>
            <h3 className="cx-label">Nothing decisive yet</h3>
            <p className="cx-read">
              Hypotheses are being tracked against your data, but none has enough evidence behind it
              to call either way.
            </p>
          </section>
        )}
        {[...confirmed, ...other].map((f) => {
          const v = f.verdict ? VERDICT_COPY[f.verdict] : undefined;
          return (
            <section className="cx-card" key={f.id} style={{ gridColumn: "span 2" }}>
              <header className="cx-head">
                <h3 className="cx-label">{f.title}</h3>
                <span className="cx-status" style={{ color: TONE_VAR[v?.tone ?? "dim"] }}>
                  {v?.label ?? "Open"}
                </span>
              </header>
              <p className="cx-read" style={{ marginTop: 2 }}>
                {f.summary ?? f.hypothesis}
              </p>
              <p className="cx-read" style={{ color: "var(--c-faint)", fontSize: 12.5 }}>
                {f.n != null ? `${f.n} observations` : "sample size unknown"}
                {f.effect_size != null
                  ? ` · effect ${f.effect_size > 0 ? "+" : ""}${f.effect_size.toFixed(1)}${f.effect_unit ?? ""}`
                  : ""}
              </p>
            </section>
          );
        })}

        {/* ── correlations ── */}
        <div className="cx-rule">What moves your HRV</div>
        {ranked.length === 0 ? (
          <section className="cx-card" style={{ gridColumn: "1 / -1" }}>
            <h3 className="cx-label">Not enough journal data</h3>
            <p className="cx-read">
              These come from WHOOP journal answers paired against next-morning HRV. There are not
              enough logged days yet to rank anything.
            </p>
          </section>
        ) : (
          <section className="cx-card" style={{ gridColumn: "1 / -1" }}>
            <header className="cx-head">
              <h3 className="cx-label">Ranked by how much they move it</h3>
              <span className="cx-status" style={{ color: "var(--c-dim)" }}>
                {ranked.length} behaviours
              </span>
            </header>
            <p className="cx-read" style={{ marginTop: 2, marginBottom: 12 }}>
              Each row is the difference in your next-morning heart rate variability on days you did
              the thing versus days you did not. Bigger swing, bigger lever.
            </p>
            <div className="cx-bars">
              {ranked.map((c) => {
                const d = c.hrv_delta ?? 0;
                const max = Math.max(...ranked.map((r) => Math.abs(r.hrv_delta ?? 0)), 1);
                return (
                  <div className="cx-bar" key={c.question}>
                    <span className="cx-bar-name" style={{ width: 210 }}>
                      {c.question}
                    </span>
                    <span className="cx-bar-track">
                      <i
                        style={{
                          width: `${(Math.abs(d) / max) * 100}%`,
                          background: d >= 0 ? "var(--ok)" : "var(--bad)",
                        }}
                      />
                    </span>
                    <span className="cx-bar-n" style={{ color: d >= 0 ? "var(--ok)" : "var(--bad)" }}>
                      {d > 0 ? "+" : ""}
                      {d.toFixed(1)}ms
                    </span>
                  </div>
                );
              })}
            </div>
          </section>
        )}
      </div>
    </ConsoleShell>
  );
}
