"use client";

import { useQuery } from "@tanstack/react-query";
import { api, type ResearchBelief, type ResearchHypothesis } from "@/lib/api";
import { Fill, FillLines } from "@/components/kit";

/**
 * The research team's workspace: what it believes about you, the questions it
 * is asking, and its notebook. Every number renders as the research routes
 * serve it.
 */

const STALE = 5 * 60 * 1000;
const Err = ({ e }: { e: unknown }) => <p className="ts-error">Couldn&apos;t load: {String(e)}</p>;
const Skel = ({ h }: { h: number }) => <div className="ts-skeleton" style={{ height: h }} />;
const pct = (v: number) => `${v > 0 ? "+" : ""}${v.toFixed(1)}%`;

// ── Belief ledger ───────────────────────────────────────────────────────────

function BeliefRow({ b, x }: { b: ResearchBelief; x: (v: number) => number }) {
  const pLo = b.prior_mean - 1.96 * b.prior_sd;
  const pHi = b.prior_mean + 1.96 * b.prior_sd;
  const qLo = b.post_mean - 1.96 * b.post_sd;
  const qHi = b.post_mean + 1.96 * b.post_sd;
  const clear = qLo > 0 || qHi < 0;
  const tone = !clear ? "var(--text-dim)" : b.post_mean < 0 ? "var(--series-2)" : "var(--series-1)";
  const learned = b.learned ?? 0;
  return (
    <div className="bel-row">
      <div className="bel-claim">
        <span>{b.claim}</span>
        <small title={b.prior_source}>Prior from {b.prior_source.split(";")[0].split("(")[0].trim()}</small>
      </div>
      <div className="bel-plot" aria-label={`prior ${pct(b.prior_mean)}, now ${pct(b.post_mean)} (95% ${pct(qLo)} to ${pct(qHi)})`}>
        <span className="bel-zero" style={{ left: `${x(0)}%` }} />
        <span className="bel-prior" style={{ left: `${x(pLo)}%`, width: `${x(pHi) - x(pLo)}%` }} />
        <span className="bel-post" style={{ left: `${x(qLo)}%`, width: `${x(qHi) - x(qLo)}%`, background: tone }} />
        <span className="bel-pt" style={{ left: `${x(b.post_mean)}%`, background: tone }} />
      </div>
      <div className="bel-val">
        <b>{pct(b.post_mean)}</b>
        <small>
          ±{(1.96 * b.post_sd).toFixed(1)} · {b.n_results ? `${Math.round(learned * 100)}% learned` : "prior only"}
        </small>
      </div>
    </div>
  );
}

export function BeliefLedger() {
  const q = useQuery({ queryKey: ["research-beliefs"], queryFn: api.researchBeliefs, staleTime: STALE });
  if (q.isError) return <Err e={q.error} />;
  if (!q.data) return <Skel h={300} />;
  const rows = [...q.data].sort((a, b) => (b.learned ?? 0) - (a.learned ?? 0));
  const ext = Math.max(5, ...rows.flatMap((b) => [Math.abs(b.prior_mean) + 1.96 * b.prior_sd, Math.abs(b.post_mean) + 1.96 * b.post_sd]));
  const x = (v: number) => 50 + (Math.max(-ext, Math.min(ext, v)) / ext) * 50;
  return (
    <div className="ts-card">
      {rows.length === 0 ? (
        <p className="ts-lede">No beliefs yet. The analyst adds one, with a literature prior, before asking a question about it.</p>
      ) : (
        <div className="bel-list">
          <div className="bel-axis">
            <span />
            <div className="bel-plot bel-scale">
              <i style={{ left: "0%" }}>{pct(-ext)}</i>
              <i style={{ left: "50%" }}>0</i>
              <i style={{ left: "100%" }}>{pct(ext)}</i>
            </div>
            <span />
          </div>
          {rows.map((b) => (
            <BeliefRow key={b.id} b={b} x={x} />
          ))}
        </div>
      )}
      <p className="ts-foot">
        Change in next-morning HRV against your 28-day baseline, on a log scale, so ±3% is the smallest change worth acting on. The faint bar is what the literature led the team to expect; the solid bar is
        what it believes now, after your data. Grey still includes zero.
      </p>
    </div>
  );
}

// ── Questions ───────────────────────────────────────────────────────────────

const VERDICT: Record<string, string> = {
  supported: "supported",
  against: "runs the other way",
  ruled_out: "ruled out",
  inconclusive: "not yet clear",
  insufficient: "too few days",
  error: "run failed",
};

function waitFor(days: number | null | undefined) {
  if (days == null) return "no answer at the current pace";
  if (days === 0) return "has enough data";
  if (days > 730) return "years at the current pace";
  if (days > 90) return `about ${Math.round(days / 30)} months`;
  return `about ${days} days`;
}

function QuestionRow({ h }: { h: ResearchHypothesis }) {
  const r = h.result;
  const unit = h.spec.unit === "week" ? "weeks" : "days";
  return (
    <div className="hq-row">
      <div className="hq-head">
        <span className="hq-q">{h.question}</span>
        <span className={`hq-v hq-${r?.verdict ?? "none"}`}>{r ? VERDICT[r.verdict] ?? r.verdict : "not run"}</span>
      </div>
      <p className="hq-meta">
        {r?.effect != null && r.ci_low != null && r.ci_high != null ? (
          <>
            <b>{pct(r.effect)}</b> (95% {pct(r.ci_low)} to {pct(r.ci_high)}) from {r.n_a} vs {r.n_b} {unit}
            {h.spec.adjust?.length ? `, adjusted for ${h.spec.adjust.join(", ").replace(/_/g, " ")}` : ""}.{" "}
          </>
        ) : r ? (
          <>{r.n_a} vs {r.n_b} {unit} so far. </>
        ) : null}
        {h.power ? `Sized to see ${h.spec.min_effect}%: needs ${h.power.needed_per_arm} ${unit} a side, ${waitFor(h.power.days_to_answer)}.` : "Too little data to size yet."}
      </p>
    </div>
  );
}

export function QuestionBoard() {
  const q = useQuery({ queryKey: ["research-hypotheses"], queryFn: api.researchHypotheses, staleTime: STALE });
  if (q.isError) return <Err e={q.error} />;
  if (!q.data) return <Skel h={300} />;
  return (
    <div className="ts-card">
      <div className="hq-list">
        {q.data.map((h) => (
          <QuestionRow key={h.slug} h={h} />
        ))}
      </div>
      <p className="ts-foot">Each question is pre-registered as a spec and frozen; the team re-runs every one nightly and folds the result into its belief.</p>
    </div>
  );
}

// ── Notebook ────────────────────────────────────────────────────────────────

const when = (iso: string) => new Date(iso).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });

export function Notebook() {
  const q = useQuery({ queryKey: ["research-notebook"], queryFn: () => api.researchNotebook(40), staleTime: STALE });
  if (q.isError) return <Err e={q.error} />;
  if (!q.data) return <Skel h={300} />;
  return (
    <div className="ts-card">
      <Fill min={260}>
        {(h) => (
          <ol className="nb-list" style={{ height: h }}>
            {q.data.map((n) => (
              <li key={n.id} className={`nb-${n.kind}`}>
                <div className="nb-top">
                  <span className="nb-kind">{n.kind}</span>
                  <span className="nb-who">
                    {n.author} · {when(n.written_at)}
                  </span>
                </div>
                <b>{n.title}</b>
                {n.body && <p>{n.body}</p>}
              </li>
            ))}
          </ol>
        )}
      </Fill>
    </div>
  );
}

// ── Forecast skill ──────────────────────────────────────────────────────────

const skillPct = (v: number) => `${v >= 0 ? "+" : ""}${(v * 100).toFixed(1)}%`;

export function ForecastSkill() {
  const f = useQuery({ queryKey: ["research-forecast"], queryFn: api.researchForecast, staleTime: STALE });
  const b = useQuery({ queryKey: ["research-beliefs"], queryFn: api.researchBeliefs, staleTime: STALE });
  if (f.isError) return <Err e={f.error} />;
  if (!f.data || !b.data) return <Skel h={360} />;
  const bt = f.data.backtest;
  if (!bt || bt.skill == null) return <p className="ts-lede">No backtest yet. It runs nightly at 04:50.</p>;
  const claim = Object.fromEntries(b.data.map((x) => [x.id, x.claim]));
  const gains = Object.entries(bt.gains)
    .filter(([, g]) => g != null)
    .map(([id, g]) => ({ id, claim: claim[id] ?? id, g: g as number }))
    .sort((x, y) => y.g - x.g);
  const gmax = Math.max(0.001, ...gains.map((x) => Math.abs(x.g)));
  const next = f.data.live.find((x) => x.actual == null);
  return (
    <div className="ts-card fs-card">
      <div className="fs-top">
        <div className="fs-score">
          <small>Forecast skill</small>
          <b className={bt.skill > 0 ? "up" : "down"}>{skillPct(bt.skill)}</b>
          <span>
            better than guessing &quot;same as your baseline&quot; across {bt.n} mornings it never saw. Typical miss {bt.rmse_lab?.toFixed(1)}% vs {bt.rmse_base?.toFixed(1)}%.
          </span>
        </div>
        <div className="fs-gains">
          <small>What each belief adds</small>
          {gains.map((x) => (
            <div key={x.id} className="fs-g">
              <span>{x.claim}</span>
              <span className="fs-track">
                <span className="fs-mid" />
                <i style={x.g >= 0 ? { left: "50%", width: `${(x.g / gmax) * 50}%`, background: "var(--series-1)" } : { right: "50%", width: `${(-x.g / gmax) * 50}%`, background: "var(--series-2)" }} />
              </span>
              <b>{x.g > 0 ? "helps" : x.g < 0 ? "hurts" : "no effect"}</b>
            </div>
          ))}
        </div>
      </div>
      <FillLines
        labels={bt.series.map((x) => x.date)}
        series={[
          { name: "What happened", color: "var(--series-2)", y: bt.series.map((x) => x.actual) },
          { name: "Lab forecast", color: "var(--series-1)", y: bt.series.map((x) => x.predicted) },
        ]}
        refs={[{ y: 0, label: "baseline" }]}
        fmt={(v) => `${Math.round(v)}%`}
        min={200}
      />
      <p className="ts-foot">
        Morning HRV against your 28-day baseline, log scale. Each month the lab refits its beliefs on data up to that point and forecasts the next 30 mornings, so every point scored is one it hadn&apos;t seen.
        {next ? ` Today's live forecast: ${next.predicted > 0 ? "+" : ""}${next.predicted.toFixed(1)}%.` : " Live forecasts start at 04:50 each morning, before the reading exists."}
        {f.data.live_n > 0 && f.data.live_skill != null ? ` Live skill so far ${skillPct(f.data.live_skill)} over ${f.data.live_n} mornings.` : ""}
      </p>
    </div>
  );
}
