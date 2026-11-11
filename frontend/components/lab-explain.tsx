"use client";

import { useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { api } from "@/lib/api";
import { teamApi } from "@/lib/team-api";
import { useGuides } from "@/components/kit";
import { useDefaultTarget } from "@/components/lab-floor";

/**
 * Explainers for the research floor: each block can open a three-layer read.
 * The plain read says what the chart is; "your numbers" walks through the
 * subject's own data behind it, filled from the same routes the chart uses;
 * "the science" names the method and where it comes from.
 */

const STALE = 5 * 60 * 1000;
const sg = (v: number, d = 1) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(d)}`;
const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const short = (iso: string) => `${MON[+iso.slice(5, 7) - 1]} ${+iso.slice(8, 10)}`;
const DAY: Record<string, string> = { Mon: "Mondays", Tue: "Tuesdays", Wed: "Wednesdays", Thu: "Thursdays", Fri: "Fridays", Sat: "Saturdays", Sun: "Sundays" };
const Loading = () => <p className="lf-x-wait">Reading your data…</p>;

/** Open state for one explainer: closed by default, and follows the global guides switch once it's flipped. */
export function useExplain(): [boolean, () => void] {
  const { on, version } = useGuides();
  const [local, setLocal] = useState<{ v: number; open: boolean } | null>(null);
  const open = local && local.v === version ? local.open : version > 0 ? on : false;
  return [open, () => setLocal({ v: version, open: !open })];
}

export function ExplainButton({ open, onClick }: { open: boolean; onClick: () => void }) {
  return (
    <button className={`lf-x-btn${open ? " on" : ""}`} onClick={onClick} aria-expanded={open}>
      {open ? "Close explainer" : "Explain this"}
      <i aria-hidden>{open ? "−" : "+"}</i>
    </button>
  );
}

export function ExplainBody({ plain, numbers, science }: { plain: ReactNode; numbers: ReactNode; science: ReactNode }) {
  return (
    <motion.div className="lf-x" initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.3 }}>
      <section>
        <span className="lf-x-k">In plain words</span>
        <div>{plain}</div>
      </section>
      <section className="lf-x-you">
        <span className="lf-x-k">Your numbers</span>
        <div>{numbers}</div>
      </section>
      <section>
        <span className="lf-x-k">The science</span>
        <div>{science}</div>
      </section>
    </motion.div>
  );
}

// ── The researchers ─────────────────────────────────────────────────────────

export function TeamExplain() {
  const t = useQuery({ queryKey: ["research-team"], queryFn: teamApi.team, staleTime: STALE });
  const n = useQuery({ queryKey: ["research-notebook", 120], queryFn: () => api.researchNotebook(120), staleTime: STALE });
  const kinds = (k: string) => (n.data ?? []).filter((e) => e.kind === k).length;
  const leads = (t.data ?? []).reduce((s, m) => s + (m.agenda?.open_leads.filter((l) => l.status !== "closed").length ?? 0), 0);
  return (
    <ExplainBody
      plain={
        <p>
          Four AI researchers each own a field of your health. Every week each one reads what the others found, explores your data freely, keeps a running list of leads ranked 1 to 5 by how promising
          they look, and can turn its best lead into a formal question. Exploring can never change your training; only a formal question that survives a blind review can change what the lab believes.
        </p>
      }
      numbers={
        !t.data || !n.data ? (
          <Loading />
        ) : (
          <p>
            {t.data.filter((m) => m.agenda).length} of 4 researchers have written an agenda so far, holding <b>{leads}</b> open lead{leads === 1 ? "" : "s"}. In the latest 120 notebook entries:{" "}
            <b>{kinds("exploration")}</b> explorations, <b>{kinds("proposal")}</b> formal proposals, <b>{kinds("rejection")}</b> blind rejections and <b>{kinds("measurement")}</b> new measurements.
            {t.data.every((m) => !m.agenda) && " The first specialist runs on Monday at 1 PM; the cards fill in as each one completes its cycle."}
          </p>
        )
      }
      science={
        <p>
          The split mirrors how careful labs separate <em>exploratory</em> from <em>confirmatory</em> work. Free exploration finds leads, but it also offers endless ways to find a pattern by chance (the
          &quot;garden of forking paths&quot;, Gelman &amp; Loken, 2013). So a claim only counts once its design is fixed in advance and reviewed by someone who can&apos;t see the reasoning behind it, as in
          a registered report (Chambers, 2013).
        </p>
      }
    />
  );
}

// ── Forecast desk ───────────────────────────────────────────────────────────

export function ForecastExplain() {
  // The explainer walks through the HRV target, the one with a scored history.
  const f = useQuery({ queryKey: ["research-forecast", "lnhrv_dev_pct"], queryFn: () => api.researchForecast(), staleTime: STALE });
  const p = useQuery({ queryKey: ["research-preview", "lnhrv_dev_pct"], queryFn: () => api.researchPreview(), staleTime: STALE });
  const bt = f.data?.backtest;
  const t = p.data?.terms.find((x) => x.contribution !== 0);
  const armWord = (r?: { min?: number; max?: number }) => (!r ? "" : r.min != null && r.max != null ? `${r.min}–${r.max}` : r.min != null ? `${r.min} or more` : `under ${r.max}`);
  return (
    <ExplainBody
      plain={
        <p>
          Each morning the lab makes a bet: how far your HRV will sit above or below your own recent normal, using only what it currently believes. The chart replays that bet over the past six months on
          mornings it hadn&apos;t seen yet, and compares it with the laziest possible guess, &quot;same as normal&quot;. <b>Skill</b> is how much better the lab does than that guess. Above zero means it has
          learned something real about you; around zero means it hasn&apos;t yet.
        </p>
      }
      numbers={
        !bt || !p.data ? (
          <Loading />
        ) : (
          <p>
            Over <b>{bt.n}</b> unseen mornings the lab&apos;s typical miss was <b>{bt.rmse_lab?.toFixed(1)}%</b>, against <b>{bt.rmse_base?.toFixed(1)}%</b> for &quot;same as normal&quot;: a skill of{" "}
            <b>{sg((bt.skill ?? 0) * 100)}%</b>. Your morning HRV naturally swings about ±{bt.rmse_base?.toFixed(0)}% from day to day, so no single belief can call it closely yet.
            {t && t.exposure != null ? (
              <>
                {" "}
                Tomorrow&apos;s bet of <b>{sg(p.data.predicted)}%</b> comes from &quot;{t.claim.toLowerCase()}&quot;: {t.feature?.replace(/_/g, " ")} was <b>{Math.round(t.exposure)}</b>, which falls in
                the {t.exposure >= (t.arm_b?.min ?? Infinity) ? `"${armWord(t.arm_b)}"` : `"${armWord(t.arm_a)}"`} group, and the lab currently believes that group runs{" "}
                {sg(t.contribution)}% from an average morning.
              </>
            ) : (
              " No belief applies to today's data, so tomorrow's bet is simply your normal."
            )}
          </p>
        )
      }
      science={
        <p>
          This is a rolling-origin backtest: refit at each past cut-off using only the data available then, then score the next month (Tashman, 2000). Skill is the mean-squared-error skill score against a
          reference forecast (Murphy, 1988). Each belief is also scored by removing it and re-running; one that makes the forecast worse is flagged for demotion, however strong its p-value looked.
        </p>
      }
    />
  );
}

// ── Belief ledger ───────────────────────────────────────────────────────────

export function BeliefsExplain() {
  const b = useQuery({ queryKey: ["research-beliefs"], queryFn: api.researchBeliefs, staleTime: STALE });
  const h = useQuery({ queryKey: ["research-hypotheses"], queryFn: api.researchHypotheses, staleTime: STALE });
  const top = [...(b.data ?? [])].filter((x) => x.n_results > 0).sort((x, y) => (y.learned ?? 0) - (x.learned ?? 0))[0];
  const q = top && (h.data ?? []).find((x) => x.belief_id === top.id && x.result?.mean_a != null);
  const u = top?.unit === "%" ? "%" : top?.unit ? ` ${top.unit}` : "";
  return (
    <ExplainBody
      plain={
        <p>
          Each card is one thing the lab believes about you, drawn as a curve of how big the effect probably is. The dashed curve is where the team started, from published research. The filled curve is
          where your own data has moved it. A narrow curve sitting clearly to one side of the centre line means the team is confident; a wide one straddling the line means it still doesn&apos;t know.
        </p>
      }
      numbers={
        !b.data || !h.data ? (
          <Loading />
        ) : top ? (
          <p>
            Take &quot;{top.claim}&quot;. The literature led the team to expect about <b>{sg(top.prior_mean)}{u}</b>, give or take {(1.96 * top.prior_sd).toFixed(0)}{u}.
            {q?.result && q.result.mean_a != null && q.result.mean_b != null && (
              <>
                {" "}
                Your data compared <b>{q.result.n_b}</b> days of one kind with <b>{q.result.n_a}</b> of the other: they averaged <b>{sg(q.result.mean_b)}{u}</b> and <b>{sg(q.result.mean_a)}{u}</b>.
              </>
            )}{" "}
            Combining the two, the team now believes <b>{sg(top.post_mean)}{u}</b>, give or take {(1.96 * top.post_sd).toFixed(1)}{u}. That&apos;s {Math.round((top.learned ?? 0) * 100)}% less uncertainty
            than it started with.
          </p>
        ) : (
          <p>No belief has a result yet, so every curve is still where the literature put it.</p>
        )
      }
      science={
        <p>
          Each belief is a normal prior updated by a normal likelihood: the posterior mean is a precision-weighted average of the literature&apos;s estimate and yours, so strong data pulls hard and thin data
          barely moves it (Bayesian shrinkage; Gelman et al., <em>Bayesian Data Analysis</em>). &quot;Learned&quot; is 1 − (posterior SD ÷ prior SD)², the share of the starting uncertainty your data has removed.
        </p>
      }
    />
  );
}

// ── Pipeline ────────────────────────────────────────────────────────────────

export function PipelineExplain() {
  const h = useQuery({ queryKey: ["research-hypotheses"], queryFn: api.researchHypotheses, staleTime: STALE });
  const top = [...(h.data ?? [])].filter((x) => x.value_parts).sort((a, b) => (b.value_score ?? 0) - (a.value_score ?? 0))[0];
  const live = (h.data ?? []).filter((x) => x.status === "active");
  const longest = [...live].sort((a, b) => (b.power?.needed_per_arm ?? 0) - (a.power?.needed_per_arm ?? 0))[0];
  return (
    <ExplainBody
      plain={
        <p>
          Every formal question moves along the line: proposed by a researcher, reviewed blind, then run every night until it has an answer. The ring on each card fills toward the number of days that
          question needs before it can see the effect it&apos;s looking for. <b>Value</b> is the server&apos;s score for how worth asking a question is; no researcher can raise its own.
        </p>
      }
      numbers={
        !h.data ? (
          <Loading />
        ) : (
          <p>
            {live.length} questions are running.
            {longest?.power && (
              <>
                {" "}
                The slowest, &quot;{longest.question}&quot;, needs <b>{longest.power.needed_per_arm.toLocaleString()}</b>{" "}days on each side to see its effect, because a single morning&apos;s HRV is noisy.
              </>
            )}
            {top?.value_parts && (
              <>
                {" "}
                The highest-value proposal so far scored <b>{top.value_parts.value.toFixed(2)}</b> = uncertainty {top.value_parts.uncertainty.toFixed(2)} × decision {top.value_parts.decision} × feasibility{" "}
                {top.value_parts.feasibility.toFixed(2)} × novelty {top.value_parts.novelty}
                {top.value_parts.goal_weight != null && ` × goal ${top.value_parts.goal_weight}`}.
              </>
            )}
          </p>
        )
      }
      science={
        <p>
          Days needed come from an a-priori power analysis: 80% power at the lab&apos;s significance level (Cohen, 1988), inflated by the design effect because today&apos;s reading resembles yesterday&apos;s
          (Kish, 1965). The value score is a simple value-of-information rule: questions whose answer is uncertain, decision-relevant, answerable soon, new, and close to your goals come first.
        </p>
      }
    />
  );
}

// ── Notebook ────────────────────────────────────────────────────────────────

export function NotebookExplain() {
  const n = useQuery({ queryKey: ["research-notebook", 120], queryFn: () => api.researchNotebook(120), staleTime: STALE });
  const by = (n.data ?? []).reduce<Record<string, number>>((m, e) => ({ ...m, [e.kind]: (m[e.kind] ?? 0) + 1 }), {});
  return (
    <ExplainBody
      plain={
        <p>
          The team&apos;s working record, written by the researchers themselves and never edited afterwards. Each thread follows one question: the researcher&apos;s proposal, the methodologist&apos;s blind
          verdict, and the nightly results. Colours mark who wrote what: the four specialists, the methodologist (amber), the forecaster and the nightly runner.
        </p>
      }
      numbers={
        !n.data ? (
          <Loading />
        ) : (
          <p>
            The latest {n.data.length} entries:{" "}
            {Object.entries(by)
              .sort((a, b) => b[1] - a[1])
              .map(([k, v]) => `${v} ${k}`)
              .join(", ")}
            .
          </p>
        )
      }
      science={
        <p>
          An append-only lab notebook is the oldest reproducibility tool there is: the record of what was tried, including what failed, is what stops a lab from quietly re-running a dead question until it
          comes up significant. The blind review step borrows from registered reports, where the method is judged before the result is known (Chambers, 2013).
        </p>
      }
    />
  );
}

// ── Misses ──────────────────────────────────────────────────────────────────

export function MissesExplain() {
  const metric = useDefaultTarget();
  const hrv = metric === "lnhrv_dev_pct";
  const what = hrv ? "your HRV" : "your strength change";
  const q = useQuery({ queryKey: ["research-misses", metric], queryFn: () => api.researchMisses(hrv ? undefined : metric), staleTime: STALE });
  const wd = [...(q.data?.by_weekday ?? [])].sort((a, b) => Math.abs(b.mean_residual) - Math.abs(a.mean_residual))[0];
  const worst = q.data?.worst_mornings?.[0];
  return (
    <ExplainBody
      plain={
        <p>
          A miss is what actually happened minus what the lab predicted. One big miss is just noise. A miss that keeps landing on the same weekday, or the same kind of night, is a clue: something the lab
          doesn&apos;t yet know about is driving the result. That&apos;s where the researchers look first.
        </p>
      }
      numbers={
        !q.data ? (
          <Loading />
        ) : (
          <p>
            {wd && (
              <>
                The biggest pattern: on {DAY[wd.day] ?? wd.day} {what} came in <b>{Math.abs(wd.mean_residual).toFixed(1)}%</b> {wd.mean_residual < 0 ? "below" : "above"} what the lab expected, averaged over {wd.n} mornings.{" "}
              </>
            )}
            {q.data.last_30_days_bias != null && (
              <>
                Over the last 30 days the forecast has run <b>{Math.abs(q.data.last_30_days_bias).toFixed(1)}%</b> too {q.data.last_30_days_bias < 0 ? "high" : "low"}.{" "}
              </>
            )}
            {worst && (
              <>
                The single worst miss was {short(worst.date)}, at <b>{sg(worst.residual, 0)}%</b>.
              </>
            )}
          </p>
        )
      }
      science={
        <p>
          This is residual analysis: if a model has captured what matters, its errors should look like random noise. Errors that line up with the calendar, or with a variable the model doesn&apos;t use,
          point to a missing predictor. It&apos;s the cheapest way to decide what to study next.
        </p>
      }
    />
  );
}

// ── Coverage ────────────────────────────────────────────────────────────────

export function CoverageExplain() {
  const q = useQuery({ queryKey: ["research-features"], queryFn: api.researchFeatures, staleTime: STALE });
  const rows = (q.data ?? []).filter((f) => f.first && !f.name.startsWith("journal:") && !f.name.includes(":") && f.name !== "weekend");
  const longest = [...rows].sort((a, b) => b.days - a.days)[0];
  const stale = rows.filter((f) => f.stale);
  return (
    <ExplainBody
      plain={
        <p>
          Every stream of data the researchers can measure, drawn from its first reading to its latest. Long bars are long histories; copper bars have stopped arriving, so any question that depends on them
          is stuck until they resume.
        </p>
      }
      numbers={
        !q.data ? (
          <Loading />
        ) : (
          <p>
            {rows.length} core streams{longest && <>, the longest being {longest.label.toLowerCase()} with <b>{longest.days.toLocaleString()}</b> days</>}. Per-muscle strength and set counts add more on top.
            {stale.length > 0 ? (
              <>
                {" "}
                Gone quiet: <b>{stale.map((f) => f.label.toLowerCase()).join("; ")}</b>.
              </>
            ) : (
              " Nothing has gone quiet."
            )}
          </p>
        )
      }
      science={
        <p>
          Missing data is rarely random. A scale that stops syncing during a bad stretch removes exactly the days that matter (data &quot;missing not at random&quot;; Rubin, 1976), which biases anything
          estimated from the days that remain. Showing what&apos;s quiet keeps that visible.
        </p>
      }
    />
  );
}
