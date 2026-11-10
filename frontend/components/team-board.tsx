"use client";

import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { api, type FeatureInfo } from "@/lib/api";
import { teamApi, type Lead, type TeamMember } from "@/lib/team-api";

/**
 * The research team's room: one card per specialist with what they are
 * curious about, the leads they are chasing, and when they last wrote to the
 * notebook. A specialist without an agenda shows their standing curiosity and
 * a designed empty lead slot, so the grid never has holes.
 */

const ease = [0.22, 1, 0.36, 1] as const;
const when = (iso: string) => new Date(iso).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
// The streams each specialist starts from, shown until its first leads exist.
const STARTING_DATA: Record<string, string[]> = {
  hypertrophy: ["strength_emphasis_pct14", "e1rm_pct14:biceps", "e1rm_pct14:glutes", "sets:biceps"],
  recovery: ["lnhrv_dev_pct", "sleep_hours", "deep_sleep_min", "resp_rate"],
  conditioning: ["strain", "rhr_bpm", "vo2_max", "pickleball_min"],
  metabolic: ["body_mass_lb", "steps", "daylight_min", "session_quality"],
};

function StartingData({ who, feats }: { who: string; feats: FeatureInfo[] | undefined }) {
  const rows = (STARTING_DATA[who] ?? []).map((n) => feats?.find((f) => f.name === n)).filter((f): f is FeatureInfo => !!f);
  const max = Math.max(1, ...rows.map((f) => f.days));
  return (
    <div className="tm-start">
      <p>No leads yet. Its first cycle starts from:</p>
      <ul>
        {rows.map((f) => (
          <li key={f.name} className={f.stale ? "stale" : ""}>
            <span>{f.label.replace(/,.*$/, "")}{f.name.includes(":") ? ` (${f.name.split(":")[1].replace(/_/g, " ")})` : ""}</span>
            <i>
              <b style={{ width: `${(f.days / max) * 100}%` }} />
            </i>
            <em>{f.stale ? "quiet" : `${f.days.toLocaleString()} d`}</em>
          </li>
        ))}
      </ul>
    </div>
  );
}

const ORDER: Record<Lead["status"], number> = { chasing: 0, open: 1, parked: 2, closed: 3 };

const topLeads = (leads: Lead[]) =>
  leads
    .filter((l) => l.status !== "closed")
    .sort((a, b) => ORDER[a.status] - ORDER[b.status] || b.priority - a.priority)
    .slice(0, 3);

function Pips({ n }: { n: number }) {
  return (
    <span className="tm-pips" aria-label={`priority ${n} of 5`}>
      {[1, 2, 3, 4, 5].map((i) => (
        <i key={i} className={i <= n ? "on" : ""} />
      ))}
    </span>
  );
}

function Card({ m, i, feats }: { m: TeamMember; i: number; feats: FeatureInfo[] | undefined }) {
  const leads = topLeads(m.agenda?.open_leads ?? []);
  const more = (m.agenda?.open_leads ?? []).filter((l) => l.status !== "closed").length - leads.length;
  const act = m.last_activity;
  return (
    <motion.article
      className={`tm-card tm-${m.researcher}`}
      initial={{ opacity: 0.001, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.07 * i, duration: 0.5, ease }}
    >
      <header className="tm-head">
        <span className={`tm-av tm-av-${m.researcher}`}>{m.name[0]}</span>
        <div>
          <b>{m.name}</b>
          <span>{m.field}</span>
        </div>
      </header>

      <section className="tm-interest">
        <span className="tm-label">{m.agenda?.interests ? "Curious about" : "Standing curiosity"}</span>
        <p>{m.agenda?.interests || m.curiosity}</p>
      </section>

      <section className="tm-leads">
        <span className="tm-label">Open leads</span>
        {leads.length > 0 ? (
          <ol>
            {leads.map((l) => (
              <li key={l.lead} className={`tm-lead tm-s-${l.status}`}>
                <div className="tm-lead-top">
                  <Pips n={l.priority} />
                  <span className="tm-status">{l.status}</span>
                </div>
                <b>{l.lead}</b>
                <p>{l.why}</p>
              </li>
            ))}
            {more > 0 && <li className="tm-more">+{more} more on the agenda</li>}
          </ol>
        ) : (
          m.agenda ? (
            <div className="tm-empty">
              <i />
              <p>Every lead is closed. New ones open as explorations turn something up.</p>
            </div>
          ) : (
            <StartingData who={m.researcher} feats={feats} />
          )
        )}
      </section>

      <footer className="tm-foot">
        <i className={act ? "on" : ""} />
        <span className="tm-act">
          {act ? (
            <>
              <em>{act.kind}</em>
              <span title={act.title}>{act.title}</span>
            </>
          ) : (
            <span>Not yet run</span>
          )}
        </span>
        {act && <time>{when(act.at)}</time>}
      </footer>
    </motion.article>
  );
}

export function TeamRoom() {
  const q = useQuery({ queryKey: ["research-team"], queryFn: teamApi.team, staleTime: 5 * 60 * 1000 });
  const f = useQuery({ queryKey: ["research-features"], queryFn: api.researchFeatures, staleTime: 5 * 60 * 1000 });
  if (q.isError) return <p className="tm-error">The research team could not be loaded ({String((q.error as Error).message)}).</p>;
  return (
    <div className="tm-room">
      {q.data
        ? q.data.map((m, i) => <Card key={m.researcher} m={m} i={i} feats={f.data} />)
        : [0, 1, 2, 3].map((i) => <div key={i} className="ts-skeleton tm-skel" />)}
    </div>
  );
}
