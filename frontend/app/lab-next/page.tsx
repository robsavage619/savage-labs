"use client";

import Link from "next/link";
import { BeliefLenses, Coverage, ForecastDesk, Masthead, Misses, Pipeline, Threads } from "@/components/lab-floor";
import { SurfaceShell } from "@/components/surface-shell";

/** Prototype of the rebuilt Lab: the research team's workspace, on live data. */
export default function LabNextPage() {
  return (
    <SurfaceShell>
      <div className="lf-page">
        <nav className="lf-tabs" aria-label="Lab views">
          <span className="on">Research floor</span>
          <Link href="/lab#trial-progress">Trials &amp; instruments</Link>
        </nav>
        <Masthead />
        <Block n="01" kicker="Forecast desk" title="Can the team predict you?">
          <ForecastDesk />
        </Block>
        <Block n="02" kicker="Belief ledger" title="What the team believes about you">
          <BeliefLenses />
        </Block>
        <Block n="03" kicker="Pipeline" title="Questions in flight">
          <Pipeline />
        </Block>
        <Block n="04" kicker="Notebook" title="The team's conversation" lede="Proposals, blind reviews and results, as the agents wrote them.">
          <Threads />
        </Block>
        <Block n="05" kicker="Misses" title="Where the lab is still wrong" lede="The analyst's agenda: patterns in the forecast's errors that no belief explains yet.">
          <Misses />
        </Block>
        <Block n="06" kicker="Data" title="What the team can see">
          <Coverage />
        </Block>
      </div>
    </SurfaceShell>
  );
}

function Block({ n, kicker, title, lede, children }: { n: string; kicker: string; title: string; lede?: string; children: React.ReactNode }) {
  return (
    <section className="lf-block">
      <header className="lf-bhead">
        <span className="lf-n">{n}</span>
        <div>
          <span className="lf-kicker">{kicker}</span>
          <h2>{title}</h2>
          {lede && <p>{lede}</p>}
        </div>
      </header>
      {children}
    </section>
  );
}
