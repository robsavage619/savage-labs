"use client";

import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { teamApi, type Lead, type TeamMember } from "@/lib/team-api";

/**
 * The research team's room: one card per specialist with what they are
 * curious about, the leads they are chasing, and when they last wrote to the
 * notebook. A specialist without an agenda shows their standing curiosity and
 * a designed empty lead slot, so the grid never has holes.
 */

const ease = [0.22, 1, 0.36, 1] as const;
const when = (iso: string) => new Date(iso).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
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

function Card({ m, i }: { m: TeamMember; i: number }) {
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
          <div className="tm-empty">
            <i />
            <p>{m.agenda ? "Every lead is closed. New ones open as explorations turn something up." : "No agenda yet. The first leads land after this specialist's first research cycle."}</p>
          </div>
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
  if (q.isError) return <p className="tm-error">The research team could not be loaded ({String((q.error as Error).message)}).</p>;
  return (
    <div className="tm-room">
      {q.data
        ? q.data.map((m, i) => <Card key={m.researcher} m={m} i={i} />)
        : [0, 1, 2, 3].map((i) => <div key={i} className="ts-skeleton tm-skel" />)}
    </div>
  );
}
