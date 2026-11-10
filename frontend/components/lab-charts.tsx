"use client";

import { useQuery } from "@tanstack/react-query";
import { api, type Experiment } from "@/lib/api";

/**
 * Lab at a glance: the n-of-1 program drawn instead of written. Every figure
 * renders the route's values as served; the only client-side step is picking
 * which rows to show.
 */

const nice = (slug: string) => slug.replace(/^suggest-/, "").replace(/-/g, " ");
const fmtDate = (iso: string | null) => {
  if (!iso) return "never";
  // A bare date is a calendar day, not UTC midnight: parse it as local.
  const d = new Date(/^\d{4}-\d{2}-\d{2}$/.test(iso) ? `${iso}T00:00:00` : iso);
  const year = d.getFullYear() === new Date().getFullYear() ? undefined : "numeric";
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year });
};

/** Content only: the kit Panel around it supplies the card, title and guide. */
function Frame({ error, ready, height, children }: { error: unknown; ready: boolean; height: number; children: React.ReactNode }) {
  if (error) return <p className="ts-error">Couldn&apos;t load: {String(error)}</p>;
  if (!ready) return <div className="ts-skeleton" style={{ height }} />;
  return <div className="ts-card">{children}</div>;
}

/** Sign of B − A the study predicted, from its pre-registered direction. */
const predictedPositive = (e: Experiment) => e.outcome_direction !== "lower_better";

/** A clear effect (CI excludes zero) whose sign contradicts the hypothesis. It can never confirm. */
function againstHypothesis(e: Experiment) {
  const r = e.result;
  if (r?.effect == null || r.effect_ci_low == null || r.effect_ci_high == null) return false;
  const clear = r.effect_ci_low > 0 || r.effect_ci_high < 0;
  return clear && r.effect > 0 !== predictedPositive(e);
}

const useExperiments = () => useQuery({ queryKey: ["experiments"], queryFn: api.experiments, staleTime: 5 * 60 * 1000 });

// ── Trial progress ──────────────────────────────────────────────────────────

export function TrialProgress() {
  const q = useExperiments();
  const active = (q.data ?? []).filter((e) => e.status === "active");
  return (
    <Frame error={q.error} ready={!!q.data} height={280}>
      <div className="tp-list">
        {active.map((e) => (
          <div key={e.id} className="tp-row">
            <div className="tp-name">
              <span>{nice(e.slug)}</span>
              <em className={e.design === "observational" ? "tp-obs" : "tp-rand"}>{e.design === "observational" ? "observational" : "randomized"}</em>
              <small className="tp-meta">
                since {fmtDate(e.started_on)} · {e.outcome_metric.replace(/_/g, " ")}
              </small>
            </div>
            {(["A", "B"] as const).map((k) => {
              const n = e.arms?.[k]?.measured ?? 0;
              const full = n >= e.min_per_arm;
              return (
                <div key={k} className="tp-arm" title={`${k}: ${k === "A" ? e.condition_a : e.condition_b}`}>
                  <small>{k}</small>
                  <span className="tp-track">
                    <i style={{ width: `${Math.min(n / e.min_per_arm, 1) * 100}%`, background: full ? "var(--series-1)" : "var(--series-2)" }} />
                  </span>
                  <b>
                    {n}/{e.min_per_arm}
                  </b>
                </div>
              );
            })}
            <span className={`nf-chip${e.result?.verdict === "CONFIRMED" ? " moved" : ""}`}>{e.result ? e.result.verdict.toLowerCase().replace("_", " ") : "not scored"}</span>
          </div>
        ))}
      </div>
      <p className="ts-foot">A trial can be scored once both conditions reach their pre-registered minimum days. Copper bars still need days.</p>
    </Frame>
  );
}

// ── Effect sizes ────────────────────────────────────────────────────────────

const OUTCOME_UNIT: Record<string, string> = { hrv_next_morning: "ms", recovery_score_next_day: "pts" };

function ForestRow({ e }: { e: Experiment }) {
  const r = e.result!;
  const lo = r.effect_ci_low!;
  const hi = r.effect_ci_high!;
  const ext = Math.max(Math.abs(lo), Math.abs(hi), Math.abs(r.effect!)) * 1.2;
  const x = (v: number) => 50 + (v / ext) * 50;
  const crosses = lo <= 0 && hi >= 0;
  const against = againstHypothesis(e);
  const tone = crosses ? " dim" : against ? " against" : "";
  const unit = OUTCOME_UNIT[e.outcome_metric] ?? "";
  return (
    <div className="fp-row">
      <div className="fp-label">
        <span>{nice(e.slug)}</span>
        <small>
          n {r.n_a}/{r.n_b} · scored {fmtDate(r.scored_at)}
        </small>
        {against && <em className="fp-against-t">clear effect, opposite to the hypothesis</em>}
      </div>
      <div className="fp-plot" aria-label={`effect ${r.effect} ${unit}, 95% CI ${lo} to ${hi}`}>
        <span className="fp-zero" />
        <span className={`fp-ci${tone}`} style={{ left: `${x(lo)}%`, width: `${x(hi) - x(lo)}%` }} />
        <span className={`fp-pt${tone}`} style={{ left: `${x(r.effect!)}%` }} />
        <span className="fp-tick" style={{ left: "0%" }}>−{ext.toFixed(0)}</span>
        <span className="fp-tick mid" style={{ left: "50%" }}>0</span>
        <span className="fp-tick end" style={{ left: "100%" }}>+{ext.toFixed(0)}</span>
      </div>
      <b className="fp-val">
        {r.effect! > 0 ? "+" : ""}
        {r.effect!.toFixed(1)} {unit}
        <small>p {r.p_value?.toFixed(2) ?? "–"}</small>
      </b>
    </div>
  );
}

export function EffectForest() {
  const q = useExperiments();
  const scored = (q.data ?? []).filter((e) => e.result?.effect != null && e.result.effect_ci_low != null && e.result.effect_ci_high != null);
  return (
    <Frame error={q.error} ready={!!q.data} height={280}>
      {scored.length === 0 ? (
        <p className="ts-lede">No trial has enough data to be scored yet.</p>
      ) : (
        <div className="fp-list">
          {scored.map((e) => (
            <ForestRow key={e.id} e={e} />
          ))}
        </div>
      )}
      <p className="ts-foot">The diamond is the best estimate; the bar is where the true effect probably sits. Grey crosses zero, so it isn&apos;t a finding yet. Copper is a clear effect in the opposite direction to the hypothesis: a finding against it, which can never confirm. Each row has its own scale and unit.</p>
    </Frame>
  );
}

// ── HRV drivers ─────────────────────────────────────────────────────────────

export function HrvDrivers() {
  const q = useQuery({ queryKey: ["insights-correlations"], queryFn: api.insightsCorrelations, staleTime: 10 * 60 * 1000 });
  const rows = (q.data ?? [])
    .filter((c) => c.hrv_delta != null)
    .sort((a, b) => Math.abs(b.hrv_delta!) - Math.abs(a.hrv_delta!))
    .slice(0, 8);
  const max = Math.max(1, ...rows.map((r) => Math.abs(r.hrv_delta!)));
  return (
    <Frame error={q.error} ready={!!q.data} height={300}>
      <div className="dv-list">
        {rows.map((c) => {
          const d = c.hrv_delta!;
          return (
            <div key={c.question} className="dv-row" title={`${c.sample_days} days answered`}>
              <span className="dv-q">{c.question.replace(/\?$/, "")}</span>
              <span className="dv-track">
                <span className="dv-mid" />
                <i style={d >= 0 ? { left: "50%", width: `${(d / max) * 50}%`, background: "var(--series-1)" } : { right: "50%", width: `${(-d / max) * 50}%`, background: "var(--series-2)" }} />
              </span>
              <b className="dv-val">
                {d > 0 ? "+" : ""}
                {d.toFixed(0)} ms<small>n {c.sample_days}</small>
              </b>
            </div>
          );
        })}
      </div>
      <p className="ts-foot">These are links, not proven causes; a calm evening can drive both the habit and the HRV. Test the interesting ones as a trial.</p>
    </Frame>
  );
}

// ── Engine scorecard ────────────────────────────────────────────────────────

export function ScorecardBullets() {
  const q = useQuery({ queryKey: ["engine-scorecard"], queryFn: api.engineScorecard, staleTime: 10 * 60 * 1000 });
  return (
    <Frame error={q.error} ready={!!q.data} height={300}>
      <p className="ts-lede">Last 90 days. First formal review {q.data ? fmtDate(q.data.first_review) : ""}.</p>
      <div className="sb-list">
        {q.data?.metrics.map((m) => {
          const pct = m.unit.trim() === "%" && m.value != null ? Math.max(0, Math.min(100, m.value)) : null;
          const tone = m.status === "on track" ? "var(--positive)" : m.status === "review" ? "var(--neutral)" : "var(--text-dim)";
          return (
            <div key={m.key} className="sb-row">
              <span className="sb-label">{m.label}</span>
              <span className="sb-track">{pct != null && <i style={{ width: `${pct}%`, background: tone }} />}</span>
              <b className="sb-val">
                {m.value ?? "–"}
                {m.unit}
              </b>
              <span className="sb-status" style={{ color: tone }}>
                {m.status}
              </span>
            </div>
          );
        })}
      </div>
    </Frame>
  );
}

// ── Priors shelf ────────────────────────────────────────────────────────────

export function PriorsShelf() {
  const p = useQuery({ queryKey: ["experiment-priors"], queryFn: api.experimentPriors, staleTime: 10 * 60 * 1000 });
  const ex = useExperiments();
  // Only a study whose estimate points the predicted way can still confirm.
  const closest = (ex.data ?? [])
    .filter((e) => e.status === "active" && e.result?.p_value != null && e.result.effect != null)
    .filter((e) => e.result!.effect! > 0 === predictedPositive(e))
    .sort((a, b) => a.result!.p_value! - b.result!.p_value!)[0];
  const ladder = (ex.data ?? [])
    .filter((e) => e.status === "active" && e.result?.p_value != null && e.result.effect != null)
    .sort((a, b) => a.result!.p_value! - b.result!.p_value!);
  const short = closest ? (["A", "B"] as const).map((k) => Math.max(0, closest.min_per_arm - (closest.arms?.[k]?.measured ?? 0))) : null;
  return (
    <Frame error={p.error ?? ex.error} ready={!!p.data && !!ex.data} height={300}>
      {p.data && p.data.length > 0 ? (
        <ul className="ps-list">
          {p.data.map((x) => (
            <li key={x.experiment_id}>
              <b>{x.prior_key.replace(/[._]/g, " ")}</b>
              <span>
                {x.effect > 0 ? "+" : ""}
                {x.effect.toFixed(1)} on {x.outcome_metric.replace(/_/g, " ")}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <div className="ps-empty">
          <p className="ts-lede">Nothing yet. No trial has confirmed, so the engine still runs on textbook rules here.</p>
          {closest && (
            <p className="ps-next">
              Closest: <b>{nice(closest.slug)}</b>, p {closest.result!.p_value!.toFixed(2)}
              {short && short.some((s) => s > 0)
                ? `, still ${short[0]} days short in A and ${short[1]} in B.`
                : ". Both conditions have enough days but the effect isn't clear yet; it rescores every night."}
            </p>
          )}
        </div>
      )}
      <PValueLadder trials={ladder} />
    </Frame>
  );
}

/** p on a log axis from 1 down to 0.001, so the 0.05 bar sits in view and small p's spread out. */
const pPos = (p: number) => Math.min(1, Math.max(0, Math.log10(1 / Math.max(p, 0.001)) / 3));

function PValueLadder({ trials }: { trials: Experiment[] }) {
  if (trials.length === 0) return null;
  return (
    <div className="pl-wrap">
      <div className="pl-head">
        <span>Distance to confirming</span>
        <small>p value, log scale · the line is 0.05</small>
      </div>
      <div className="pl-list">
        {trials.map((e) => {
          const p = e.result!.p_value!;
          const against = e.result!.effect! > 0 !== predictedPositive(e);
          return (
            <div key={e.id} className="pl-row" title={against ? "Points opposite to the hypothesis, so it can never confirm" : undefined}>
              <span className="pl-name">{nice(e.slug)}</span>
              <span className="pl-track">
                <span className="pl-line" style={{ left: `${pPos(0.05) * 100}%` }} />
                <i style={{ width: `${pPos(p) * 100}%`, background: against ? "var(--series-2)" : "var(--series-1)" }} />
              </span>
              <b className="pl-val">
                p {p.toFixed(2)}
                <small>{against ? "wrong way" : p < 0.05 ? "past the line" : "not yet"}</small>
              </b>
            </div>
          );
        })}
      </div>
      <p className="ts-foot">Longer bars are stronger evidence; a cyan bar past the line, in a randomized trial, becomes a prior. Copper bars point the other way and can never confirm.</p>
    </div>
  );
}
