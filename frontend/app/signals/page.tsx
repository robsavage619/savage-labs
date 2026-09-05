"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { recoveryRead, hrvRead, rhrRead, sleepRead, signalChannels } from "@/lib/console-copy";
import { Channel } from "@/components/console/channel";
import { ConsoleShell } from "@/components/console/shell";

/**
 * SIGNALS — what the body is doing, as opposed to Ops's what to do about it.
 *
 * This is the content that used to sit behind eight collapsed accordions on
 * /review plus a "Raw WHOOP vitals" section. Nothing here collapses.
 */
export default function SignalsPage() {
  const state = useQuery({ queryKey: ["daily-state"], queryFn: api.dailyState, staleTime: 5 * 60_000 });
  const volume = useQuery({ queryKey: ["muscle-volume"], queryFn: api.muscleVolume, staleTime: 5 * 60_000 });

  const s = state.data;
  const vitals = s ? [recoveryRead(s), hrvRead(s), rhrRead(s), sleepRead(s)] : [];
  const detail = s ? signalChannels(s) : [];

  // Volume against target — the thing the audit found buried three levels deep
  // on /lab, which is odd for the number that decides whether the training is
  // working at all.
  const muscles = (volume.data?.muscles ?? [])
    .filter((m) => m.mev != null)
    .map((m) => ({
      ...m,
      pct: m.mev ? Math.min(1.6, m.weekly_sets / m.mev) : 0,
    }))
    .sort((a, b) => a.pct - b.pct);

  const under = muscles.filter((m) => m.pct < 1);

  return (
    <ConsoleShell>
      <div className="cx-grid">
        <div className="cx-rule" style={{ marginTop: 0 }}>
          Today&apos;s vitals
        </div>
        {s
          ? vitals.map((ch) => <Channel key={ch.label} ch={ch} />)
          : Array.from({ length: 4 }, (_, i) => <div key={i} className="cx-skel" />)}

        <div className="cx-rule">Sleep &amp; systemic</div>
        {s
          ? detail.map((ch) => <Channel key={ch.label} ch={ch} />)
          : Array.from({ length: 6 }, (_, i) => <div key={i} className="cx-skel" />)}

        <div className="cx-rule">Weekly volume against target</div>
        {volume.data ? (
          <section className="cx-card" style={{ gridColumn: "1 / -1" }}>
            <header className="cx-head">
              <h3 className="cx-label">Sets this week</h3>
              <span className="cx-status" style={{ color: under.length ? "var(--warn)" : "var(--c-dim)" }}>
                {under.length ? `${under.length} below minimum` : "all at minimum"}
              </span>
            </header>
            <p className="cx-read" style={{ marginTop: 2, marginBottom: 14 }}>
              {under.length
                ? `${under
                    .slice(0, 3)
                    .map((m) => m.muscle.replace(/_/g, " "))
                    .join(", ")} ${under.length === 1 ? "is" : "are"} short of the weekly minimum that maintains size. Everything at or past the line is doing its job.`
                : "Every muscle is at or above the weekly minimum that maintains size."}
            </p>
            <div className="cx-bars">
              {muscles.map((m) => (
                <div className="cx-bar" key={m.muscle}>
                  <span className="cx-bar-name">{m.muscle.replace(/_/g, " ")}</span>
                  <span className="cx-bar-track">
                    <i
                      style={{
                        width: `${Math.min(100, (m.pct / 1.6) * 100)}%`,
                        background: m.pct < 1 ? "var(--warn)" : "var(--ok)",
                      }}
                    />
                    <em style={{ left: `${(1 / 1.6) * 100}%` }} aria-hidden="true" />
                  </span>
                  <span className="cx-bar-n">
                    {m.weekly_sets}
                    <span style={{ color: "var(--c-faint)" }}>/{m.mev}</span>
                  </span>
                </div>
              ))}
            </div>
          </section>
        ) : (
          <div className="cx-skel" style={{ gridColumn: "1 / -1", minHeight: 220 }} />
        )}
      </div>
    </ConsoleShell>
  );
}
