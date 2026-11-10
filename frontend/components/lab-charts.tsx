"use client";

import { useQuery } from "@tanstack/react-query";
import { api, type Experiment } from "@/lib/api";
import { Eyebrow } from "@/components/ui/metric";
import { ExploreButton } from "@/components/metric-explorer";

/**
 * Lab at a glance: the n-of-1 program drawn instead of written. Every figure
 * renders the route's values as served; the only client-side step is picking
 * which rows to show.
 */

const nice = (slug: string) => slug.replace(/^suggest-/, "").replace(/-/g, " ");
const fmtDate = (iso: string | null) => {
  if (!iso) return "never";
  const d = new Date(iso);
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
};

function Head({ eyebrow, title, children }: { eyebrow: string; title: string; children?: React.ReactNode }) {
  return (
    <div className="ts-head">
      <div>
        <Eyebrow>{eyebrow}</Eyebrow>
        <h3 className="shc-section-title mt-1">{title}</h3>
      </div>
      {children}
    </div>
  );
}

function Frame({ error, ready, height, children }: { error: unknown; ready: boolean; height: number; children: React.ReactNode }) {
  if (error) return <div className="shc-card p-6 ts-card"><p className="ts-error">Couldn&apos;t load: {String(error)}</p></div>;
  if (!ready) return <div className="shc-card p-6 ts-card ts-skeleton" style={{ height }} />;
  return <div className="shc-card shc-enter p-6 ts-card">{children}</div>;
}

const useExperiments = () => useQuery({ queryKey: ["experiments"], queryFn: api.experiments, staleTime: 5 * 60 * 1000 });

// ── Trial progress ──────────────────────────────────────────────────────────

export function TrialProgress() {
  const q = useExperiments();
  const active = (q.data ?? []).filter((e) => e.status === "active");
  return (
    <Frame error={q.error} ready={!!q.data} height={280}>
      <Head eyebrow={`${active.length} running`} title="How close is each trial to an answer?" />
      <div className="tp-list">
        {active.map((e) => (
          <div key={e.id} className="tp-row">
            <div className="tp-name">
              <span>{nice(e.slug)}</span>
              <em className={e.design === "observational" ? "tp-obs" : "tp-rand"}>{e.design === "observational" ? "observational" : "randomized"}</em>
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
  const unit = OUTCOME_UNIT[e.outcome_metric] ?? "";
  return (
    <div className="fp-row">
      <div className="fp-label">
        <span>{nice(e.slug)}</span>
        <small>
          n {r.n_a}/{r.n_b} · scored {fmtDate(r.scored_at)}
        </small>
      </div>
      <div className="fp-plot" aria-label={`effect ${r.effect} ${unit}, 95% CI ${lo} to ${hi}`}>
        <span className="fp-zero" />
        <span className={`fp-ci${crosses ? " dim" : ""}`} style={{ left: `${x(lo)}%`, width: `${x(hi) - x(lo)}%` }} />
        <span className={`fp-pt${crosses ? " dim" : ""}`} style={{ left: `${x(r.effect!)}%` }} />
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
      <Head eyebrow="Scored results · 95% confidence" title="What the trials found so far" />
      {scored.length === 0 ? (
        <p className="ts-lede">No trial has enough data to be scored yet.</p>
      ) : (
        <div className="fp-list">
          {scored.map((e) => (
            <ForestRow key={e.id} e={e} />
          ))}
        </div>
      )}
      <p className="ts-foot">The diamond is the best estimate; the bar is where the true effect probably sits. A grey bar crosses zero, so it isn&apos;t a finding yet. Each row has its own scale and unit.</p>
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
      <Head eyebrow="WHOOP journal · yes days minus no days" title="What moves your HRV">
        <ExploreButton metric="hrv" />
      </Head>
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
      <Head eyebrow={`Last 90 days · first review ${q.data ? fmtDate(q.data.first_review) : ""}`} title="Is the engine any good?" />
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
  const closest = (ex.data ?? [])
    .filter((e) => e.status === "active" && e.result?.p_value != null)
    .sort((a, b) => a.result!.p_value! - b.result!.p_value!)[0];
  const short = closest ? (["A", "B"] as const).map((k) => Math.max(0, closest.min_per_arm - (closest.arms?.[k]?.measured ?? 0))) : null;
  return (
    <Frame error={p.error ?? ex.error} ready={!!p.data && !!ex.data} height={300}>
      <Head eyebrow="Confirmed and in use" title="What's been proven" />
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
              {short && short.some((s) => s > 0) ? `, still ${short[0]} days short in A and ${short[1]} in B.` : ". Both conditions have enough days; it needs rescoring."}
            </p>
          )}
        </div>
      )}
    </Frame>
  );
}
