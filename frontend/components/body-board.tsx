"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { FillBars, FillLines, fmtX } from "@/components/kit";

/**
 * Body, rebuilt on the kit: the slow movers drawn as charts, each read
 * against its own history. Values render as served by their routes.
 */

const Err = ({ e }: { e: unknown }) => <p className="ts-error">Couldn&apos;t load: {String(e)}</p>;
const Skel = ({ h }: { h: number }) => <div className="ts-skeleton" style={{ height: h }} />;
const STALE = 10 * 60 * 1000;

/** Whole days between an ISO date and today; a source quiet for a fortnight says so. */
const daysSince = (iso: string) => Math.round((Date.now() - new Date(`${iso}T00:00:00`).getTime()) / 86_400_000);
const quiet = (iso: string) => (daysSince(iso) > 14 ? <span className="bd-stale"> No reading since {fmtX(iso)}.</span> : null);

/** Monthly means of a sparse multi-year series, labelled "YYYY-MM" so the axis carries the year. */
function monthly<T extends { date: string }>(rows: T[], v: (r: T) => number) {
  const m = new Map<string, number[]>();
  rows.forEach((r) => m.set(r.date.slice(0, 7), [...(m.get(r.date.slice(0, 7)) ?? []), v(r)]));
  return { labels: [...m.keys()], y: [...m.values()].map((a) => a.reduce((s, x) => s + x, 0) / a.length) };
}

// ── Weight ──────────────────────────────────────────────────────────────────

export function WeightTrend() {
  const q = useQuery({ queryKey: ["body-trend"], queryFn: api.bodyTrend, staleTime: STALE });
  if (q.isError) return <Err e={q.error} />;
  const p = q.data ?? [];
  if (p.length < 2) return <Skel h={260} />;
  const last = p[p.length - 1];
  const m = monthly(p, (x) => x.lbs);
  const yearAgo = [...p].reverse().find((x) => daysSince(x.date) - daysSince(last.date) >= 365);
  return (
    <div className="ts-card">
      <p className="ts-lede">
        Latest <b>{last.lbs.toFixed(1)} lb</b> on {fmtX(last.date)}
        {yearAgo ? (
          <>
            , {last.lbs >= yearAgo.lbs ? "up" : "down"} <b>{Math.abs(last.lbs - yearAgo.lbs).toFixed(1)} lb</b> from a year before.
          </>
        ) : (
          "."
        )}
        {quiet(last.date)}
      </p>
      <FillLines labels={m.labels} series={[{ name: "Weight lb", color: "var(--series-1)", y: m.y }]} fmt={(v) => v.toFixed(0)} min={220} />
      <p className="ts-foot">Monthly average of each month with a weigh-in, so quiet stretches close up. Under strict recomposition a flat line with rising lifts is the goal, so read it next to the lift scoreboard.</p>
    </div>
  );
}

// ── Aerobic fitness ─────────────────────────────────────────────────────────

export function Vo2Trend() {
  const q = useQuery({ queryKey: ["body-vo2"], queryFn: api.bodyVO2Max, staleTime: STALE });
  if (q.isError) return <Err e={q.error} />;
  const p = q.data ?? [];
  if (p.length < 2) return <Skel h={260} />;
  const last = p[p.length - 1];
  const best = Math.max(...p.map((x) => x.vo2max));
  const m = monthly(p, (x) => x.vo2max);
  return (
    <div className="ts-card">
      <p className="ts-lede">
        Latest <b>{last.vo2max.toFixed(1)}</b> ml/kg/min on {fmtX(last.date)}; best on record <b>{best.toFixed(1)}</b>.{quiet(last.date)}
      </p>
      <FillLines labels={m.labels} series={[{ name: "VO₂ max", color: "var(--series-1)", y: m.y }]} fmt={(v) => v.toFixed(0)} min={220} />
      <p className="ts-foot">Monthly average of the watch&apos;s estimates from outdoor walks and runs. Not a lab test: trust the direction over the number.</p>
    </div>
  );
}

// ── Daily movement ──────────────────────────────────────────────────────────

export function StepsBars() {
  const q = useQuery({ queryKey: ["body-steps", 90], queryFn: () => api.bodySteps(90), staleTime: STALE });
  if (q.isError) return <Err e={q.error} />;
  const p = q.data ?? [];
  if (p.length < 2) return <Skel h={240} />;
  const avg = p.reduce((s, x) => s + x.steps, 0) / p.length;
  return (
    <div className="ts-card">
      <p className="ts-lede">
        <b>{Math.round(avg).toLocaleString()}</b> a day on average across the <b>{p.length}</b> days that reported in the last 90.
      </p>
      <FillBars
        labels={p.map((x) => x.date)}
        values={p.map((x) => x.steps)}
        color={(v) => (v >= 10_000 ? "var(--series-1)" : "var(--series-2)")}
        refs={[{ y: 10_000, label: "10k" }]}
        fmt={(v) => (v >= 1000 ? `${Math.round(v / 1000)}k` : String(v))}
        tip={(i) => `${fmtX(p[i].date)}: ${p[i].steps.toLocaleString()} steps`}
        min={200}
      />
      <p className="ts-foot">Only days the phone or watch reported are drawn; a missing day is no data, not zero steps. Copper is under 10k.</p>
    </div>
  );
}

// ── Resting heart rate, both devices ────────────────────────────────────────

export function RhrDevices() {
  const q = useQuery({ queryKey: ["body-rhr", 90], queryFn: () => api.bodyRHRTrend(90), staleTime: STALE });
  if (q.isError) return <Err e={q.error} />;
  const p = q.data ?? [];
  if (p.length < 2) return <Skel h={240} />;
  const lastW = [...p].reverse().find((x) => x.whoop != null)?.whoop ?? null;
  return (
    <div className="ts-card">
      <p className="ts-lede">
        WHOOP reads <b>{lastW ?? "–"} bpm</b> this morning. The two devices measure differently, so compare each line to its own past.
      </p>
      <FillLines
        labels={p.map((x) => x.date)}
        series={[
          { name: "WHOOP", color: "var(--series-1)", y: p.map((x) => x.whoop) },
          { name: "Apple Watch", color: "var(--series-2)", y: p.map((x) => x.apple) },
        ]}
        min={200}
      />
    </div>
  );
}

// ── Airway ──────────────────────────────────────────────────────────────────

const useAirway = () => useQuery({ queryKey: ["sleep-airway", 180], queryFn: () => api.sleepAirway(180), staleTime: STALE });

export function Spo2Half() {
  const q = useAirway();
  if (q.isError) return <Err e={q.error} />;
  const d = q.data;
  if (!d) return <Skel h={260} />;
  const n = d.nights.filter((x) => x.spo2 != null);
  return (
    <div className="ts-card">
      <p className="ts-lede">
        <b>{d.spo2.below_95}</b> of {d.spo2.n} nights averaged under 95%, <b>{d.spo2.below_92}</b> under 92%.
      </p>
      <FillLines
        labels={n.map((x) => x.date)}
        series={[
          { name: "Nightly", color: "var(--series-2)", y: n.map((x) => x.spo2) },
          { name: "7-night mean", color: "var(--series-1)", y: n.map((x) => x.spo2_7d) },
        ]}
        refs={[
          { y: 95, label: "95%" },
          { y: 92, label: "92% gate" },
        ]}
        fmt={(v) => v.toFixed(0)}
        min={220}
      />
      <p className="ts-foot">Read the mean, not the dots. A nightly average is not an apnea count; only a sleep study gives one.</p>
    </div>
  );
}

export function RespHalf() {
  const q = useAirway();
  if (q.isError) return <Err e={q.error} />;
  const d = q.data;
  if (!d) return <Skel h={260} />;
  const n = d.nights.filter((x) => x.resp != null);
  const base = d.resp.baseline_28d;
  return (
    <div className="ts-card">
      <p className="ts-lede">
        Last 7 nights <b>{d.resp.last_7d_mean?.toFixed(1) ?? "–"}</b> breaths/min
        {base != null ? (
          <>
            {" "}
            against your 28-night baseline of <b>{base.toFixed(1)}</b>.
          </>
        ) : (
          "."
        )}
      </p>
      <FillLines
        labels={n.map((x) => x.date)}
        series={[
          { name: "Nightly", color: "var(--series-2)", y: n.map((x) => x.resp) },
          { name: "7-night mean", color: "var(--series-1)", y: n.map((x) => x.resp_7d) },
        ]}
        refs={base != null ? [{ y: base + d.resp.gate_delta, label: `+${d.resp.gate_delta} gate` }] : []}
        fmt={(v) => v.toFixed(0)}
        min={220}
      />
      <p className="ts-foot">Rises with infection and airway load alike. A dip in oxygen with flat breathing reads differently from both moving together.</p>
    </div>
  );
}
