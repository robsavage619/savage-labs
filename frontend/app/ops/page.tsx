"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { reconciledVerdict } from "@/lib/readiness";
import { allChannels, boardLede } from "@/lib/console-copy";
import { Channel } from "@/components/console/channel";
import "@/components/console/console.css";

/**
 * OPS — the console board.
 *
 * A prototype of Direction B from the UI teardown, running on live data beside
 * the existing surfaces rather than replacing them, so the two can be compared
 * before anything is thrown away.
 *
 * Three rules it exists to test:
 *   1. Nothing collapses. Every channel is on screen; the width does the work
 *      that accordions were doing.
 *   2. Every number carries a sentence saying what it means for today.
 *   3. Colour appears only when a value is out of its useful band.
 */
export default function OpsPage() {
  const state = useQuery({ queryKey: ["daily-state"], queryFn: api.dailyState, staleTime: 5 * 60_000 });
  const plan = useQuery({ queryKey: ["workout-next"], queryFn: () => api.workoutNext(false), staleTime: 5 * 60_000 });

  const s = state.data;
  const verdict = s ? reconciledVerdict(s) : null;
  const channels = s ? allChannels(s) : [];

  const locks = [
    ...(s?.gates.forbid_muscle_groups ?? []).map((m) => ({ m, soft: false })),
    ...(s?.gates.forbid_muscles ?? []).map((m) => ({ m, soft: true })),
  ];

  const blocks = plan.data?.blocks ?? [];
  const sets = blocks.flatMap((b) => b.exercises ?? []).slice(0, 6);
  const rec = plan.data?.recommendation;
  const planFallbackSummary = rec?.focus
    ? `${rec.focus.split(" — ")[0]} today${
        rec.estimated_duration_min ? `, about ${rec.estimated_duration_min} minutes` : ""
      }${rec.target_rpe ? ` at RPE ${rec.target_rpe}` : ""}.`
    : "The lifts written for today.";

  return (
    <div className="cx">
      <div className="cx-wrap">
        <div className="cx-top">
          <span className="cx-word">
            Savage <em>Labs</em>
          </span>
          <nav style={{ display: "flex", gap: 14 }}>
            <Link href="/" className="cx-when no-tactile" style={{ textDecoration: "none" }}>
              Now
            </Link>
            <Link href="/review" className="cx-when no-tactile" style={{ textDecoration: "none" }}>
              Review
            </Link>
            <Link href="/lab" className="cx-when no-tactile" style={{ textDecoration: "none" }}>
              Lab
            </Link>
            <span className="cx-when" style={{ color: "var(--c-accent)" }}>
              Ops
            </span>
          </nav>
          <span className="cx-when">
            {new Date().toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" })}
          </span>
        </div>

        <div className="cx-grid">
          {/* ── the call ── */}
          {s && verdict ? (
            <section className="cx-call">
              <span className="cx-label" style={{ marginBottom: 0 }}>
                Today
              </span>
              <h1
                className="cx-call-verdict"
                style={{
                  color:
                    verdict.tone === "positive"
                      ? "var(--ok)"
                      : verdict.tone === "negative"
                        ? "var(--bad)"
                        : "var(--warn)",
                }}
              >
                {verdict.label}
              </h1>
              <p className="cx-lede">{boardLede(s, verdict.label)}</p>
              {locks.length > 0 && (
                <div className="cx-locks">
                  {locks.map(({ m, soft }) => (
                    <span key={`${soft}-${m}`} className="cx-lock" data-soft={soft}>
                      {m.replace(/_/g, " ")}
                    </span>
                  ))}
                </div>
              )}
            </section>
          ) : (
            <div className="cx-skel cx-call" style={{ minHeight: 210 }} />
          )}

          {/* ── today's session ── */}
          {sets.length > 0 ? (
            <section className="cx-card cx-sess">
              <header className="cx-head">
                <h3 className="cx-label">Today&apos;s session</h3>
                <span className="cx-status" style={{ color: "var(--c-dim)" }}>
                  {blocks.flatMap((b) => b.exercises ?? []).length} exercises
                </span>
              </header>
              {/* `summary` is the one plain sentence; `rationale` is the technical
                  record and lives behind the disclosure. Older plans predate the
                  summary field, so fall back to the focus line rather than
                  dumping the engine-voice paragraph into the reading path. */}
              <p className="cx-read" style={{ marginTop: 4 }}>
                {rec?.summary ?? planFallbackSummary}
              </p>
              <table className="cx-tbl">
                <tbody>
                  {sets.map((e, i) => (
                    <tr key={i}>
                      <td className="ex">{e.name}</td>
                      <td className="rx">
                        {e.sets}&#215;{e.reps}
                        {e.weight_lbs != null ? ` @ ${e.weight_lbs}` : ""}
                      </td>
                      <td className="prev">{e.rpe_target != null ? `RPE ${e.rpe_target}` : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {rec?.rationale && (
                <details className="cx-why">
                  <summary>Why this plan</summary>
                  <p className="cx-why-body">{rec.rationale}</p>
                </details>
              )}
            </section>
          ) : (
            <div className="cx-skel cx-sess" style={{ minHeight: 210 }} />
          )}

          <div className="cx-rule">Signals</div>

          {s
            ? channels.map((ch) => <Channel key={ch.label} ch={ch} />)
            : Array.from({ length: 8 }, (_, i) => <div key={i} className="cx-skel" />)}
        </div>
      </div>
    </div>
  );
}
