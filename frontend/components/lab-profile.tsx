"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { ModelDomain, ModelParameter } from "@/lib/api";
import { useWidth } from "@/components/kit";

const DOMAIN_TITLE: Record<string, string> = {
  training: "Training",
  recovery: "Recovery",
  sleep: "Sleep",
  health: "Health",
};

const HOW_SURE: Record<string, string> = {
  "prior only": "Nothing of yours yet: the lab is repeating the literature",
  learning: "Learning: your data is moving it, not enough to act on",
  established: "Established: enough of your data that the engine acts on it",
};

const fmt = (v: number | null, unit: string | null) => {
  if (v == null) return "—";
  const s = Math.abs(v) >= 100 ? v.toFixed(0) : Math.abs(v) >= 10 ? v.toFixed(1) : v.toFixed(2);
  return unit ? `${s} ${unit}` : s;
};

const range = (m: { mean: number | null; sd: number | null }, unit: string | null) =>
  m.mean == null ? "no published prior" : `${fmt(m.mean, unit)}${m.sd != null ? ` ± ${fmt(m.sd, null)}` : ""}`;

/** Literature and Rob as two mean ± 1 sd intervals on one shared axis, drawn at the measured pixel width. */
function Strip({ p }: { p: ModelParameter }) {
  const [ref, W] = useWidth(320);
  const rows = [
    { name: "Literature", m: p.literature, color: "var(--sl-accent)" },
    { name: "You", m: p.rob, color: "var(--copper, #ce7951)" },
  ].filter((r) => r.m.mean != null);
  const H = 22 * rows.length + 4;
  const pts = rows.flatMap((r) => [r.m.mean! - (r.m.sd ?? 0), r.m.mean! + (r.m.sd ?? 0)]);
  const lo = Math.min(...pts);
  const hi = Math.max(...pts);
  const pad = 6;
  const x = (v: number) => (hi === lo ? W / 2 : pad + ((v - lo) / (hi - lo)) * (W - 2 * pad));
  return (
    <div ref={ref} className="lp-strip">
      {rows.length > 0 && (
        <svg width={W} height={H} role="img" aria-label={`${p.label}: literature against you`}>
          {rows.map((r, i) => {
            const y = 12 + i * 22;
            const sd = r.m.sd ?? 0;
            return (
              <g key={r.name}>
                {sd > 0 && <line x1={x(r.m.mean! - sd)} x2={x(r.m.mean! + sd)} y1={y} y2={y} stroke={r.color} strokeWidth={2} strokeOpacity={0.55} />}
                <circle cx={x(r.m.mean!)} cy={y} r={4.5} fill={r.color} />
              </g>
            );
          })}
        </svg>
      )}
    </div>
  );
}

function Row({ p }: { p: ModelParameter }) {
  const same = p.rob.mean === p.literature.mean && p.rob.sd === p.literature.sd;
  return (
    <li className="lp-row">
      <div className="lp-main">
        <h3>{p.label}</h3>
        <p className="lp-sure">{HOW_SURE[p.how_sure] ?? p.how_sure}</p>
        {p.changes ? <p className="lp-changes">Changes: {p.changes}</p> : <p className="lp-changes dim">Changes nothing yet</p>}
      </div>
      <dl className="lp-nums">
        <div>
          <dt>Literature</dt>
          <dd>{range(p.literature, p.unit)}</dd>
          <dd className="src">{p.literature.source}</dd>
        </div>
        <div>
          <dt>You</dt>
          <dd>{same && p.evidence.n === 0 ? "no data of yours yet" : range(p.rob, p.unit)}</dd>
          <dd className="src">
            {p.evidence.n} {p.evidence.kind} {p.evidence.n === 1 ? "observation" : "observations"}
          </dd>
        </div>
      </dl>
      <Strip p={p} />
    </li>
  );
}

export function LabProfile() {
  const q = useQuery({ queryKey: ["rob-model"], queryFn: api.robModel, staleTime: 5 * 60 * 1000 });
  if (q.isError) {
    return (
      <p className="lp-state hot" role="alert">
        Couldn&apos;t load the model ({q.error instanceof Error ? q.error.message : "error"}). The server is returning an error; this is not a slow load.
      </p>
    );
  }
  if (q.isLoading || !q.data) return <p className="lp-state">Reading the model…</p>;
  const entries = Object.entries(q.data.domains) as [string, ModelDomain][];
  if (q.data.count === 0) {
    return (
      <p className="lp-state">
        The lab has not written down anything about you yet. The registry fills the first time the engine&apos;s fits are read into it; until then there is nothing honest to show here.
      </p>
    );
  }
  return (
    <div className="lp">
      <p className="lp-lede">
        {q.data.count} beliefs about you. Each starts from published work and moves only when your own evidence is strong enough; with little data you will see the literature repeated back.
      </p>
      {entries.map(([d, params]) => (
        <section key={d} className="lp-domain">
          <h2>{DOMAIN_TITLE[d] ?? d}</h2>
          <ul>
            {params.map((p) => (
              <Row key={p.key} p={p} />
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}
