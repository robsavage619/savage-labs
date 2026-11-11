"use client";

import { useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import Link from "next/link";
import { api, type MenuPick, type TrainingBrief, type WorkoutPlan } from "@/lib/api";
import { ease, niceTicks, useWidth } from "@/components/kit";
import { ProgressionDrawer } from "@/components/progression-drawer";
import { useDailyState } from "@/components/today-brief";

/**
 * Training as a brief: the session to do and what the rotation changed in it,
 * every muscle's sets this week against the engine's target (biceps and glutes
 * first), what court weeks cost the glutes, and each lift's working e1RM.
 * Values render as served; the only arithmetic here is chart scaling and the
 * light-vs-heavy court-week averages, which are read straight off the series.
 */

const STALE = 10 * 60 * 1000;
const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const short = (iso: string) => `${MON[+iso.slice(5, 7) - 1]} ${+iso.slice(8, 10)}`;
const pretty = (s: string) => s.replace(/_/g, " ");
const n1 = (v: number) => (v % 1 ? v.toFixed(1) : String(v));
const addDays = (iso: string, d: number) => new Date(Date.parse(iso + "T00:00:00Z") + d * 86_400_000).toISOString().slice(0, 10);

const usePlan = () => useQuery({ queryKey: ["workout-next"], queryFn: () => api.workoutNext(false), staleTime: 60 * 60 * 1000, retry: 1 });
const useRx = () => useQuery({ queryKey: ["prescription"], queryFn: api.prescription, staleTime: STALE });
const useBrief = () => useQuery({ queryKey: ["training-brief", 26], queryFn: () => api.trainingBrief(26), staleTime: STALE });
const useTier = () => useQuery({ queryKey: ["training-tier"], queryFn: api.trainingTier, staleTime: 60 * 60 * 1000 });

const Skel = ({ h }: { h: number }) => <div className="ts-skeleton tr-skel" style={{ height: h }} />;
const Err = ({ what, e }: { what: string; e: unknown }) => (
  <p className="tr-err">
    Couldn&apos;t load {what}: {String(e)}
  </p>
);

export function Block({ n, title, sub, children, id }: { n: string; title: string; sub: ReactNode; children: ReactNode; id?: string }) {
  return (
    <section className="tr-block scroll-mt-24" id={id}>
      <header className="tr-bhead">
        <span className="tr-n">{n}</span>
        <div>
          <h2>{title}</h2>
          <p>{sub}</p>
        </div>
      </header>
      {children}
    </section>
  );
}

// ── Rotation status, parsed from the menu's own status line ────────────────

type Rot = { kind: "in" | "out" | "held" | "due" | "trial" | "kept" | "other"; replaces?: string; why: string };

function parseStatus(s: string): Rot {
  let m = s.match(/^swapped in: replaces (.+) \((.+)\)$/);
  if (m) return { kind: "in", replaces: m[1], why: m[2] };
  if ((m = s.match(/^swap candidate: (.+)$/))) return { kind: "out", why: m[1] };
  if ((m = s.match(/^held: (.+?)(, no in-band alternative)?$/))) return { kind: "held", why: m[2] ? `${m[1]}, nothing in-band to swap to` : m[1] };
  if ((m = s.match(/^past the rotation window \((.+?)\)/))) return { kind: "due", why: m[1] };
  if (s.startsWith("TRIAL")) return { kind: "trial", why: "no verified option for this head" };
  if (s.startsWith("kept")) return { kind: "kept", why: s.replace(/^kept: /, "") };
  return { kind: "other", why: s };
}

const ROT_RANK: Record<Rot["kind"], number> = { in: 0, out: 1, due: 2, held: 3, trial: 4, kept: 5, other: 6 };
const ROT_TAG: Partial<Record<Rot["kind"], string>> = { in: "rotated in", out: "due out", due: "past window", held: "held", trial: "trial" };

/** Exercise → its strongest rotation status across every muscle menu it appears in. */
function rotationIndex(science: Record<string, MenuPick[]>) {
  const out = new Map<string, Rot & { muscle: string }>();
  for (const [muscle, picks] of Object.entries(science))
    for (const p of picks) {
      const r = parseStatus(p.status);
      const prev = out.get(p.exercise);
      if (!prev || ROT_RANK[r.kind] < ROT_RANK[prev.kind]) out.set(p.exercise, { ...r, muscle });
    }
  return out;
}

// ── 01 The session ──────────────────────────────────────────────────────────

export function SessionBrief() {
  const plan = usePlan();
  const rx = useRx();
  const brief = useBrief();
  const st = useDailyState();
  if (plan.isError) return <Err what="today's session" e={plan.error} />;
  const p: WorkoutPlan | undefined = plan.data;
  if (!p || !st.data) return <Skel h={620} />;
  const rot = rx.data ? rotationIndex(rx.data.exercise_science ?? {}) : new Map<string, Rot & { muscle: string }>();
  const lifts = new Map((brief.data?.lifts ?? []).map((l) => [l.exercise, l]));
  const exs = p.blocks.flatMap((b) => b.exercises);
  const sets = exs.reduce((a, e) => a + e.sets, 0);
  const executed = p.execution?.executed === true;
  const [head, ...rest] = p.recommendation.focus.split(/: | — /);
  const day = new Date(st.data.as_of + "T12:00:00").toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" });
  const locks = [...st.data.gates.forbid_muscle_groups, ...st.data.gates.forbid_muscles];
  let i = 0;
  return (
    <div className="tr-mast">
      <div className="tr-card tr-sess scroll-mt-24" id="plan">
        <div className="tr-sess-head">
          <span className="tr-eyebrow">
            {day} · {executed ? "trained" : "the session to do"}
          </span>
          <motion.h1 initial={{ opacity: 0.001, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.7, ease }}>
            {head}
          </motion.h1>
          {rest.length > 0 && <p className="tr-sess-focus">{rest.join(": ")}</p>}
          <p className="tr-sess-why">{p.recommendation.summary}</p>
        </div>
        <div className="tr-sess-stats">
          <div>
            <b>{exs.length}</b>
            <span>lifts</span>
          </div>
          <div>
            <b>{sets}</b>
            <span>working sets</span>
          </div>
          <div>
            <b>{p.recommendation.estimated_duration_min != null ? `~${p.recommendation.estimated_duration_min}` : "–"}</b>
            <span>minutes</span>
          </div>
          <div>
            <b>{p.recommendation.target_rpe ?? "–"}</b>
            <span>target RPE</span>
          </div>
          <div className="tr-sess-locks">
            <span className="tr-label">Locked now</span>
            <span>
              {locks.length === 0 ? (
                <i className="tr-chip clear">nothing</i>
              ) : (
                locks.map((l) => (
                  <i key={l} className="tr-chip soft" title={st.data!.gates.reasons.find((r) => r.startsWith(l))}>
                    {pretty(l)}
                  </i>
                ))
              )}
            </span>
          </div>
        </div>
        <ol className="tr-sess-list">
          {p.blocks.map((b) =>
            b.exercises.map((e, k) => {
              const r = rot.get(e.name);
              const l = lifts.get(e.name);
              const timed = String(e.reps).includes("min");
              const perHand = l?.unit === "each hand" || /dumbbell/i.test(e.name);
              // A swap credited to another muscle's slot is not this lift's rotation (Leg Press filling the adductor slot).
              const own = r && !(r.kind === "in" && l?.muscle && r.muscle !== l.muscle) ? r : undefined;
              const tag = own && ROT_TAG[own.kind];
              return (
                <li key={e.name} className={`tr-sess-row${k === 0 ? " first" : ""}`}>
                  <span className="tr-sess-i">{String(++i).padStart(2, "0")}</span>
                  <span className="tr-sess-name">
                    <b>{e.name}</b>
                    <small>
                      {k === 0 ? `${b.label.replace(/ - /g, " · ")} · ` : ""}
                      {l?.muscle ? pretty(l.muscle) : r ? pretty(r.muscle) : timed ? "conditioning" : "no history"}
                    </small>
                  </span>
                  <span className="tr-sess-tag">{tag && <i className={`tr-rot tr-rot-${own!.kind}`} title={own!.replaces ? `Replaces ${own!.replaces}: ${own!.why}` : own!.why}>{tag}</i>}</span>
                  <span className="tr-sess-dose">
                    {e.sets} × {e.reps}
                  </span>
                  <span className="tr-sess-load">
                    {e.weight_lbs ? (
                      <>
                        <b>{e.weight_lbs}</b> {perHand ? "lb / hand" : "lb"}
                      </>
                    ) : (
                      <em>{timed ? "by effort" : `to RPE ${e.rpe_target}`}</em>
                    )}
                  </span>
                </li>
              );
            }),
          )}
        </ol>
        <Link className="tr-sess-go" href="/#session">
          Working sheet with load history, cues and Send to Hevy, on Today →
        </Link>
      </div>
      <Rotation plan={p} />
    </div>
  );
}

function Rotation({ plan }: { plan: WorkoutPlan }) {
  const rx = useRx();
  if (rx.isError) return <Err what="the rotation" e={rx.error} />;
  if (!rx.data) return <Skel h={620} />;
  const science = rx.data.exercise_science ?? {};
  const emph = new Set(rx.data.muscles.filter((m) => m.emphasis).map((m) => m.muscle));
  const inPlan = new Set(plan.blocks.flatMap((b) => b.exercises.map((e) => e.name)));
  const order = Object.keys(science).sort((a, b) => Number(emph.has(b)) - Number(emph.has(a)) || a.localeCompare(b));
  const swaps: { muscle: string; inn: string; out: string; why: string }[] = [];
  const held: { muscle: string; name: string; why: string; kind: Rot["kind"] }[] = [];
  const seen = new Set<string>();
  for (const m of order)
    for (const p of science[m]) {
      const r = parseStatus(p.status);
      if (r.kind === "in" && !seen.has(`${p.exercise}>${r.replaces}`)) {
        seen.add(`${p.exercise}>${r.replaces}`);
        swaps.push({ muscle: m, inn: p.exercise, out: r.replaces!, why: r.why });
      } else if ((r.kind === "held" || r.kind === "due") && !seen.has(p.exercise)) {
        seen.add(p.exercise);
        held.push({ muscle: m, name: p.exercise, why: r.why, kind: r.kind });
      }
    }
  const programmed = swaps.filter((s) => inPlan.has(s.inn)).length;
  return (
    <div className="tr-card tr-rotation scroll-mt-24" id="rotation">
      <div className="tr-rot-head">
        <span className="tr-label">The rotation the menu proposes</span>
        <b>
          {swaps.length} swap{swaps.length === 1 ? "" : "s"} this week{swaps.length ? `, ${programmed} in today's session` : ""}
        </b>
        <p>A lift that plateaus, or leads its slot past six weeks, is swapped for an in-band alternative. A swapped-in lift has no load anchor yet, so it starts at a target effort.</p>
      </div>
      <ul className="tr-swaps">
        {swaps.map((s) => (
          <li key={`${s.inn}>${s.out}`} className={inPlan.has(s.inn) ? "on" : ""}>
            <span className="tr-swap-m">
              {pretty(s.muscle)}
              {emph.has(s.muscle) && <em>emphasis</em>}
            </span>
            <span className="tr-swap-x">
              <s>{s.out}</s>
              <b>{s.inn}</b>
            </span>
            <span className="tr-swap-why">{s.why === "plateaued" ? "plateaued" : s.why.replace("held this head ", "held ")}</span>
            <span className="tr-swap-today">{inPlan.has(s.inn) ? "today" : ""}</span>
          </li>
        ))}
      </ul>
      {held.length > 0 && (
        <div className="tr-held">
          <span className="tr-label">Held with nothing in-band to swap to</span>
          <ul>
            {held.map((h) => (
              <li key={h.name}>
                <b>{h.name}</b>
                <span>
                  {pretty(h.muscle)} · {h.why.replace(", nothing in-band to swap to", "")}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

// ── 02 Muscle first ─────────────────────────────────────────────────────────

type Land = { mev: number; mav: number; mrv: number; tier: string };

function zone(v: number, l?: Land) {
  if (!l) return "range";
  return v < l.mev ? "under" : v > l.mrv ? "over" : "range";
}

function EmphasisCard({ muscle, brief, land, row }: { muscle: string; brief: TrainingBrief; land?: Land; row: { current_sets: number; target_sets: number; direct_owed: number } }) {
  const [ref, W] = useWidth(560);
  const [hov, setHov] = useState<number | null>(null);
  const weeks = brief.weeks;
  const ys = weeks.map((w) => w.sets[muscle] ?? 0);
  const H = 150;
  const P = { l: 4, r: 52, t: 10, b: 22 };
  const max = Math.max(land?.mrv ?? 0, row.target_sets, ...ys) * 1.08 || 1;
  const step = (W - P.l - P.r) / weeks.length;
  const y = (v: number) => P.t + (1 - v / max) * (H - P.t - P.b);
  const bw = Math.max(3, Math.min(16, step * 0.64));
  const done = ys.slice(-9, -1);
  const avg = done.reduce((a, b) => a + b, 0) / Math.max(1, done.length);
  const left = Math.max(0, row.target_sets - row.current_sets);
  const hi = hov ?? weeks.length - 1;
  return (
    <div className="tr-card tr-emph">
      <div className="tr-emph-head">
        <div>
          <span className="tr-eyebrow">Emphasis · {land?.tier ?? "grow"}</span>
          <h3>{pretty(muscle)}</h3>
        </div>
        <div className="tr-emph-num">
          <b>{n1(row.current_sets)}</b>
          <span>/ {row.target_sets} sets</span>
        </div>
      </div>
      <p className="tr-emph-read">
        {left > 0 ? (
          <>
            <em>{n1(left)}</em> sets still to land this week
          </>
        ) : (
          <>Target met this week</>
        )}
        {row.direct_owed > 0 ? `, ${row.direct_owed} of them direct` : ""}. Averaging <em>{avg.toFixed(1)}</em> a week over the last 8 complete weeks{land ? `, against a growth range of ${land.mev}–${land.mrv}` : ""}.
      </p>
      <div className="tr-emph-chart" ref={ref} onMouseLeave={() => setHov(null)}>
        <svg width={W} height={H} role="img" aria-label={`${pretty(muscle)} sets per week, 26 weeks`}>
          {land && <rect x={P.l} width={W - P.l - P.r} y={y(land.mrv)} height={y(land.mev) - y(land.mrv)} className="tr-band" />}
          {land && (
            <>
              <text x={W - P.r + 6} y={y(land.mrv) + 4} className="tr-tick">
                MRV {land.mrv}
              </text>
              <text x={W - P.r + 6} y={y(land.mev) + 4} className="tr-tick">
                MEV {land.mev}
              </text>
            </>
          )}
          <line x1={P.l} x2={W - P.r} y1={y(row.target_sets)} y2={y(row.target_sets)} className="tr-ref" />
          <line x1={P.l} x2={W - P.r} y1={y(0)} y2={y(0)} className="tr-grid" />
          {ys.map((v, i) => {
            const cx = P.l + step * (i + 0.5);
            const last = i === ys.length - 1;
            const h = Math.max(v > 0 ? 2 : 0, y(0) - y(v));
            return (
              <g key={weeks[i].week_start}>
                {i === hi && <rect x={cx - step / 2} width={step} y={P.t} height={H - P.t - P.b} className="tr-hovcol" />}
                {v === 0 ? (
                  <circle cx={cx} cy={y(0) - 3} r={2} className="tr-zero" />
                ) : (
                  <rect x={cx - bw / 2} width={bw} y={y(0) - h} height={h} rx={Math.min(3, bw / 3)} className={`tr-bar z-${zone(v, land)}${last ? " part" : ""}`} />
                )}
                {(i % 6 === (ys.length - 1) % 6) && (
                  <text x={cx} y={H - 6} textAnchor="middle" className={`tr-tick${last ? " now" : ""}`}>
                    {last ? "now" : short(weeks[i].week_start)}
                  </text>
                )}
              </g>
            );
          })}
          <rect
            x={P.l}
            y={P.t}
            width={Math.max(0, W - P.l - P.r)}
            height={H - P.t - P.b}
            fill="transparent"
            onMouseMove={(e) => {
              const r = (e.currentTarget as SVGRectElement).getBoundingClientRect();
              const k = Math.floor(((e.clientX - r.left) / r.width) * weeks.length);
              setHov(k >= 0 && k < weeks.length ? k : null);
            }}
          />
        </svg>
        <span className="tr-emph-hov">
          {hi === weeks.length - 1 ? "this week so far" : `week of ${short(weeks[hi].week_start)}`} · <b>{n1(ys[hi])}</b> sets
          {weeks[hi].court_days ? ` · ${weeks[hi].court_days} court day${weeks[hi].court_days === 1 ? "" : "s"}` : ""}
        </span>
      </div>
    </div>
  );
}

function MuscleRow({ m, land, hist }: { m: { muscle: string; current_sets: number; target_sets: number; reason: string; tier?: string }; land?: Land; hist: number[] }) {
  const max = Math.max(land?.mrv ?? 0, m.target_sets, m.current_sets, 1);
  const pct = (v: number) => `${(Math.min(v, max) / max) * 100}%`;
  const done = m.current_sets >= m.target_sets;
  return (
    <div className="tr-mrow" title={m.reason}>
      <span className="tr-mrow-name">
        {pretty(m.muscle)}
        <em>{land?.tier === "grow" ? "grow" : "hold"}</em>
      </span>
      <span className="tr-mrow-track">
        {land && <span className="tr-mrow-band" style={{ left: pct(land.mev), width: `calc(${pct(land.mrv)} - ${pct(land.mev)})` }} />}
        <motion.span className={`tr-mrow-bar${done ? " done" : ""}`} initial={{ width: 0 }} animate={{ width: pct(m.current_sets) }} transition={{ duration: 0.7, ease }} />
        <span className="tr-mrow-tgt" style={{ left: pct(m.target_sets) }} />
      </span>
      <b className="tr-mrow-val">
        {n1(m.current_sets)}
        <small>/{m.target_sets}</small>
      </b>
      <span className="tr-mrow-hist" aria-label="Last 12 complete weeks against the minimum">
        {hist.map((v, i) => (
          <i key={i} className={`z-${zone(v, land)}${v === 0 ? " zero" : ""}`} style={{ opacity: v === 0 ? 1 : 0.35 + 0.65 * Math.min(1, v / max) }} />
        ))}
      </span>
    </div>
  );
}

export function MuscleVolume() {
  const rx = useRx();
  const brief = useBrief();
  const tier = useTier();
  const err = [rx, brief, tier].find((q) => q.isError);
  if (err) return <Err what="weekly volume" e={err.error} />;
  if (!rx.data || !brief.data || !tier.data) return <Skel h={760} />;
  const lands = new Map<string, Land>(tier.data.muscles.map((t) => [t.muscle, { mev: t.mev, mav: t.mav, mrv: t.mrv, tier: t.tier }]));
  const emph = rx.data.muscles.filter((m) => m.emphasis);
  const rest = rx.data.muscles.filter((m) => !m.emphasis).sort((a, b) => Number(lands.get(b.muscle)?.tier === "grow") - Number(lands.get(a.muscle)?.tier === "grow") || a.muscle.localeCompare(b.muscle));
  const complete = brief.data.weeks.slice(-13, -1);
  const onTarget = rx.data.muscles.filter((m) => m.current_sets >= m.target_sets).length;
  return (
    <div className="tr-vol">
      <div className="tr-emph-pair">
        {emph.map((m) => (
          <EmphasisCard key={m.muscle} muscle={m.muscle} brief={brief.data!} land={lands.get(m.muscle)} row={m} />
        ))}
      </div>
      <div className="tr-card tr-mtable">
        <div className="tr-mtable-head">
          <span className="tr-label">Every other muscle, week of {short(rx.data.week_start)}</span>
          <b>
            {onTarget} of {rx.data.muscles.length} at target so far
          </b>
          <span className="tr-mtable-key">
            <span>
              <i className="k-band" />
              growth range
            </span>
            <span>
              <i className="k-tgt" />
              this week&apos;s target
            </span>
            <span>
              <i className="k-hist" />
              last 12 weeks, amber under the minimum
            </span>
          </span>
        </div>
        <div className="tr-mgrid">
          {rest.map((m) => (
            <MuscleRow key={m.muscle} m={m} land={lands.get(m.muscle)} hist={complete.map((w) => w.sets[m.muscle] ?? 0)} />
          ))}
        </div>
      </div>
    </div>
  );
}

// ── 03 What the court costs ─────────────────────────────────────────────────

export function CourtCost() {
  const brief = useBrief();
  const tier = useTier();
  const [ref, W] = useWidth(1200);
  const [hov, setHov] = useState<number | null>(null);
  if (brief.isError) return <Err what="court weeks" e={brief.error} />;
  if (!brief.data) return (
    <div className="tr-card tr-court" ref={ref}>
      <Skel h={360} />
    </div>
  );
  // The running week is partial, so the comparison reads complete weeks only.
  const weeks = brief.data.weeks.slice(0, -1);
  const g = weeks.map((w) => w.sets.glutes ?? 0);
  const c = weeks.map((w) => w.court_days);
  const land = tier.data?.muscles.find((m) => m.muscle === "glutes");
  const bucket = (f: (d: number) => boolean) => {
    const v = g.filter((_, i) => f(c[i]));
    return { n: v.length, avg: v.length ? v.reduce((a, b) => a + b, 0) / v.length : null };
  };
  const light = bucket((d) => d <= 1);
  const heavy = bucket((d) => d >= 4);
  let run: { s: number; e: number } | null = null;
  for (let i = 0, s = -1; i <= g.length; i++) {
    if (i < g.length && g[i] === 0) {
      if (s < 0) s = i;
    } else if (s >= 0) {
      if (!run || i - s > run.e - run.s + 1) run = { s, e: i - 1 };
      s = -1;
    }
  }
  const runCourt = run ? c.slice(run.s, run.e + 1).reduce((a, b) => a + b, 0) : 0;

  const P = { l: 132, r: 56, t: 14, b: 26 };
  const GH = 150;
  const CH = 54;
  const GAP = 22;
  const H = P.t + GH + GAP + CH + P.b;
  const step = (W - P.l - P.r) / weeks.length;
  const cx = (i: number) => P.l + step * (i + 0.5);
  const gmax = Math.max(land?.mrv ?? 0, ...g) * 1.08 || 1;
  const cmax = Math.max(5, ...c);
  const gy = (v: number) => P.t + (1 - v / gmax) * GH;
  const ctop = P.t + GH + GAP;
  const cy = (v: number) => ctop + (1 - v / cmax) * CH;
  const bw = Math.max(4, Math.min(20, step * 0.6));
  const hi = hov ?? weeks.length - 1;
  return (
    <div className="tr-card tr-court">
      <div className="tr-court-stats">
        <div>
          <span className="tr-label">Light court weeks · 0–1 days</span>
          <b>{light.avg == null ? "–" : light.avg.toFixed(1)}</b>
          <span>glute sets a week, {light.n} weeks</span>
        </div>
        <div className="hot">
          <span className="tr-label">Heavy court weeks · 4+ days</span>
          <b>{heavy.avg == null ? "–" : heavy.avg.toFixed(1)}</b>
          <span>glute sets a week, {heavy.n} weeks</span>
        </div>
        <div className="zero">
          <span className="tr-label">Longest run with no glute work</span>
          <b>{run ? `${run.e - run.s + 1} wk` : "none"}</b>
          <span>{run ? `${short(weeks[run.s].week_start)} – ${short(addDays(weeks[run.e].week_start, 6))}, ${runCourt} court days in it` : "every week had glute sets"}</span>
        </div>
      </div>
      <div className="tr-court-chart" ref={ref} onMouseLeave={() => setHov(null)}>
        <svg width={W} height={H} role="img" aria-label="Glute sets and court days per week, last 25 complete weeks">
          {run && <rect x={cx(run.s) - step / 2} width={step * (run.e - run.s + 1)} y={P.t} height={H - P.t - P.b} className="tr-drought" />}
          <rect x={cx(hi) - step / 2} width={step} y={P.t} height={H - P.t - P.b} className="tr-hovcol" />
          {land && <rect x={P.l} width={W - P.l - P.r} y={gy(land.mrv)} height={gy(land.mev) - gy(land.mrv)} className="tr-band" />}
          <line x1={P.l} x2={W - P.r} y1={gy(0)} y2={gy(0)} className="tr-grid" />
          <line x1={P.l} x2={W - P.r} y1={cy(0)} y2={cy(0)} className="tr-grid" />
          {niceTicks(0, cmax, 2).filter((t) => t > 0).map((t) => (
            <line key={t} x1={P.l} x2={W - P.r} y1={cy(t)} y2={cy(t)} className="tr-week" />
          ))}
          <text x={0} y={P.t + 12} className="tr-lane-name">Glute sets</text>
          <text x={0} y={P.t + 40} className="tr-lane-val">{n1(g[hi])}</text>
          <text x={0} y={ctop + 12} className="tr-lane-name">Court days</text>
          <text x={0} y={ctop + 40} className="tr-lane-val copper">{c[hi]}</text>
          {land && (
            <>
              <text x={W - P.r + 6} y={gy(land.mrv) + 4} className="tr-tick">MRV {land.mrv}</text>
              <text x={W - P.r + 6} y={gy(land.mev) + 4} className="tr-tick">MEV {land.mev}</text>
            </>
          )}
          {g.map((v, i) =>
            v === 0 ? (
              <circle key={i} cx={cx(i)} cy={gy(0) - 3} r={2.5} className="tr-zero" />
            ) : (
              <rect key={i} x={cx(i) - bw / 2} width={bw} y={gy(v)} height={gy(0) - gy(v)} rx={Math.min(3, bw / 3)} className={`tr-bar z-${zone(v, land)}`} opacity={hov == null || hov === i ? 1 : 0.45} />
            ),
          )}
          {c.map((v, i) => (v > 0 ? <rect key={i} x={cx(i) - bw / 2} width={bw} y={cy(v)} height={cy(0) - cy(v)} rx={Math.min(3, bw / 3)} className="tr-cbar" opacity={hov == null || hov === i ? 1 : 0.45} /> : null))}
          {run && (
            <text x={cx(run.s) - step / 2 + 8} y={P.t + 14} className="tr-drought-lbl">
              {run.e - run.s + 1} weeks, no glute sets
            </text>
          )}
          {weeks.map((w, i) =>
            i % 4 === (weeks.length - 1) % 4 ? (
              <text key={w.week_start} x={cx(i)} y={H - 8} textAnchor="middle" className="tr-tick">
                {short(w.week_start)}
              </text>
            ) : null,
          )}
          <rect
            x={P.l}
            y={P.t}
            width={Math.max(0, W - P.l - P.r)}
            height={H - P.t - P.b}
            fill="transparent"
            onMouseMove={(e) => {
              const r = (e.currentTarget as SVGRectElement).getBoundingClientRect();
              const k = Math.floor(((e.clientX - r.left) / r.width) * weeks.length);
              setHov(k >= 0 && k < weeks.length ? k : null);
            }}
          />
        </svg>
        <span className="tr-court-day">week of {short(weeks[hi].week_start)}{weeks[hi].court_min ? ` · ${weeks[hi].court_min} min on court` : ""}</span>
      </div>
      <p className="tr-foot">
        Pickleball counts here as training load, not a goal. When you have played, the same-day leg gate moves a planned leg day to upper body, so the glutes lose the day rather than the court. Glute sets are credited the engine&apos;s way, with compounds counting for every muscle they train.
      </p>
    </div>
  );
}

// ── 04 Strength ─────────────────────────────────────────────────────────────

type Lift = TrainingBrief["lifts"][number];
const TREND: Record<string, { c: string; l: string; r: number }> = {
  regressing: { c: "var(--negative)", l: "sliding", r: 0 },
  stalled: { c: "var(--neutral)", l: "stalled", r: 1 },
  progressing: { c: "var(--positive)", l: "going up", r: 3 },
};
const tr = (t: string | null) => TREND[t ?? ""] ?? { c: "var(--text-faint)", l: "too new", r: 2 };

/** Position on the shared 26-week axis, 0..1, by date rather than by index: untrained weeks leave a gap. */
const span = (from: string, to: string) => (iso: string) => (Date.parse(iso) - Date.parse(from)) / Math.max(1, Date.parse(to) - Date.parse(from));

function Spark({ s, color, at }: { s: Lift["series"]; color: string; at: (iso: string) => number }) {
  const W = 92;
  const H = 26;
  if (s.length < 2) return <svg width={W} height={H} aria-hidden="true" />;
  const v = s.map((p) => p.e1rm_lbs);
  const lo = Math.min(...v);
  const hi = Math.max(...v);
  const x = (i: number) => 2 + at(s[i].week_start) * (W - 4);
  const y = (n: number) => 3 + (hi === lo ? 0.5 : (hi - n) / (hi - lo)) * (H - 6);
  return (
    <svg width={W} height={H} aria-hidden="true">
      <path d={v.map((n, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(n).toFixed(1)}`).join("")} fill="none" stroke={color} strokeWidth={1.5} strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={x(v.length - 1)} cy={y(v[v.length - 1])} r={2.5} fill={color} />
    </svg>
  );
}

function LiftChart({ lift, weeks }: { lift: Lift; weeks: string[] }) {
  const [ref, W] = useWidth(640);
  const H = 250;
  const P = { l: 44, r: 16, t: 14, b: 26 };
  const s = lift.series;
  const v = s.map((p) => p.e1rm_lbs);
  const lo0 = Math.min(...v, lift.e1rm_lbs);
  const hi0 = Math.max(...v, lift.e1rm_lbs);
  const pad = (hi0 - lo0) * 0.15 || hi0 * 0.05 || 1;
  const ticks = niceTicks(lo0 - pad, hi0 + pad, 4);
  const lo = Math.min(ticks[0], lo0 - pad);
  const hi = Math.max(ticks[ticks.length - 1], hi0 + pad);
  const at = span(weeks[0], weeks[weeks.length - 1]);
  const xd = (iso: string) => P.l + at(iso) * (W - P.l - P.r);
  const x = (i: number) => xd(s[i].week_start);
  const y = (n: number) => P.t + (1 - (n - lo) / (hi - lo)) * (H - P.t - P.b);
  const c = tr(lift.trend).c;
  const path = v.map((n, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(n).toFixed(1)}`).join("");
  return (
    <div className="tr-lchart" ref={ref}>
      <svg width={W} height={H} role="img" aria-label={`${lift.exercise} weekly e1RM`}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={P.l} x2={W - P.r} y1={y(t)} y2={y(t)} className="tr-week" />
            <text x={P.l - 8} y={y(t) + 4} textAnchor="end" className="tr-tick">
              {t}
            </text>
          </g>
        ))}
        <line x1={P.l} x2={W - P.r} y1={y(lift.e1rm_lbs)} y2={y(lift.e1rm_lbs)} className="tr-ref" />
        <text x={W - P.r} y={y(lift.e1rm_lbs) - 6} textAnchor="end" className="tr-tick">
          90-day best {lift.e1rm_lbs}
        </text>
        {s.length > 1 && <path d={`${path}L${x(s.length - 1).toFixed(1)},${y(lo).toFixed(1)}L${x(0).toFixed(1)},${y(lo).toFixed(1)}Z`} fill={c} opacity={0.08} />}
        <motion.path key={lift.exercise} d={path} fill="none" stroke={c} strokeWidth={2.25} strokeLinejoin="round" strokeLinecap="round" initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ duration: 0.8, ease }} />
        {s.map((p, i) => (
          <circle key={p.week_start} cx={x(i)} cy={y(p.e1rm_lbs)} r={i === s.length - 1 ? 4.5 : 2.5} fill={c} className={i === s.length - 1 ? "tr-enddot" : undefined}>
            <title>
              week of {short(p.week_start)}: {p.e1rm_lbs} lb
            </title>
          </circle>
        ))}
        {weeks.map((w, i) =>
          i % 5 === (weeks.length - 1) % 5 ? (
            <text key={w} x={xd(w)} y={H - 8} textAnchor="middle" className="tr-tick">
              {short(w)}
            </text>
          ) : null,
        )}
      </svg>
    </div>
  );
}

export function Strength() {
  const brief = useBrief();
  const rx = useRx();
  const [picked, setPicked] = useState<string | null>(null);
  const [drawer, setDrawer] = useState<string | null>(null);
  if (brief.isError) return <Err what="lift progression" e={brief.error} />;
  if (!brief.data) return <Skel h={560} />;
  const emph = new Set((rx.data?.muscles ?? []).filter((m) => m.emphasis).map((m) => m.muscle));
  const lifts = [...brief.data.lifts].sort(
    (a, b) => Number(emph.has(b.muscle ?? "")) - Number(emph.has(a.muscle ?? "")) || tr(a.trend).r - tr(b.trend).r || a.exercise.localeCompare(b.exercise),
  );
  const sel = lifts.find((l) => l.exercise === picked) ?? lifts.find((l) => emph.has(l.muscle ?? "") && l.trend !== "progressing") ?? lifts[0];
  const count = (t: string) => lifts.filter((l) => l.trend === t).length;
  const sliding = lifts.filter((l) => emph.has(l.muscle ?? "") && (l.trend === "stalled" || l.trend === "regressing"));
  if (!sel) return <p className="tr-foot">No loaded lifts in the last 90 days.</p>;
  const t = tr(sel.trend);
  const weeks = brief.data.weeks.map((w) => w.week_start);
  const at = span(weeks[0], weeks[weeks.length - 1]);
  const perHand = sel.unit === "each hand";
  return (
    <div className="tr-str">
      <div className="tr-card tr-str-l">
        <div className="tr-str-counts">
          {(["progressing", "stalled", "regressing"] as const).map((k) => (
            <div key={k}>
              <b style={{ color: TREND[k].c }}>{count(k)}</b>
              <span>{TREND[k].l}</span>
            </div>
          ))}
          <div>
            <b>{lifts.length}</b>
            <span>lifts in 90 days</span>
          </div>
        </div>
        <p className="tr-str-sum">
          {sliding.length === 0 ? (
            <>Nothing in the emphasis muscles is stalled or sliding.</>
          ) : (
            <>
              Stalled or sliding in the emphasis muscles:{" "}
              {sliding.map((l, i) => (
                <span key={l.exercise}>
                  {i ? ", " : ""}
                  <button className="tr-inline no-tactile" onClick={() => setPicked(l.exercise)}>
                    {l.exercise}
                  </button>
                </span>
              ))}
              .
            </>
          )}
        </p>
        <div className="tr-str-sel">
          <div>
            <span className="tr-label">{sel.muscle ? pretty(sel.muscle) : "unmapped"} · {sel.sessions_90d} sessions in 90 days</span>
            <h3>{sel.exercise}</h3>
          </div>
          <div className="tr-str-e1">
            <b>{sel.e1rm_lbs}</b>
            <span>lb e1RM{perHand ? " per hand" : ""}</span>
            <i className="tr-chip" style={{ color: t.c, borderColor: `color-mix(in oklch, ${t.c} 40%, transparent)` }}>
              {t.l} · {sel.recommendation}
            </i>
          </div>
        </div>
        {sel.series.length > 0 ? <LiftChart lift={sel} weeks={weeks} /> : <p className="tr-foot">No stored weekly e1RM in the last six months.</p>}
        <div className="tr-str-foot">
          <p className="tr-foot">The headline is the working-weights e1RM the planner loads and validates from, the best set of the last 90 days. The line is each trained week&apos;s best over six months.</p>
          <button className="btn btn-ghost" onClick={() => setDrawer(sel.exercise)}>
            Every session →
          </button>
        </div>
      </div>
      <div className="tr-card tr-str-r">
        <div className="tr-str-scroll" role="listbox" aria-label="Lifts">
          {lifts.map((l, i) => {
            const lt = tr(l.trend);
            const firstOther = i > 0 && emph.has(lifts[i - 1].muscle ?? "") && !emph.has(l.muscle ?? "");
            return (
              <div key={l.exercise}>
                {i === 0 && emph.has(l.muscle ?? "") && <span className="tr-str-grp">Emphasis muscles</span>}
                {firstOther && <span className="tr-str-grp">Everything else</span>}
                <button role="option" aria-selected={l === sel} className={`tr-lrow no-tactile${l === sel ? " on" : ""}`} onClick={() => setPicked(l.exercise)}>
                  <i style={{ background: lt.c }} />
                  <span className="tr-lrow-name">
                    <b>{l.exercise}</b>
                    <small>
                      {l.muscle ? pretty(l.muscle) : "unmapped"} · {lt.l}
                    </small>
                  </span>
                  <Spark s={l.series} color={lt.c} at={at} />
                  <span className="tr-lrow-val">
                    {Math.round(l.e1rm_lbs)}
                    <small>{l.unit === "each hand" ? "/hand" : "lb"}</small>
                  </span>
                </button>
              </div>
            );
          })}
        </div>
      </div>
      <ProgressionDrawer exercise={drawer} onClose={() => setDrawer(null)} />
    </div>
  );
}
