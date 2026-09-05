"use client";

import type { ChannelRead, ChannelState } from "@/lib/console-copy";

/**
 * One instrument channel: a name, a number, where that number sits in its
 * useful range, and a sentence saying what it means.
 *
 * Two deliberate departures from the rest of the app.
 *
 * Colour is spent ONLY on state, and only when state is not "good". A board
 * that tints every tile communicates nothing — the eye needs somewhere quiet
 * to rest so the one amber thing pulls. This is why there is no per-channel
 * accent cycle here.
 *
 * The read line is set at 13.5px, not the 10px the current panels use. It is
 * prose and has to be comfortable, otherwise it becomes decoration people stop
 * reading — which is exactly what happened to the existing captions.
 */

const STATE_COLOR: Record<ChannelState, string> = {
  good: "var(--ok)",
  watch: "var(--warn)",
  alert: "var(--bad)",
  unknown: "var(--c-faint)",
};

function Band({ pos, labels, state }: { pos: number; labels?: [string, string, string]; state: ChannelState }) {
  return (
    <div className="cx-band-wrap">
      <div className="cx-band">
        <div
          className="cx-marker"
          style={{ left: `${pos * 100}%`, background: STATE_COLOR[state] }}
        />
      </div>
      {labels && (
        <div className="cx-band-labels">
          <span>{labels[0]}</span>
          <span className="cx-band-mid">{labels[1]}</span>
          <span>{labels[2]}</span>
        </div>
      )}
    </div>
  );
}

export function Channel({ ch, span = 1 }: { ch: ChannelRead; span?: number }) {
  const color = STATE_COLOR[ch.state];
  return (
    <article
      className="cx-card"
      style={{ gridColumn: `span ${span}` }}
      data-state={ch.state}
    >
      <header className="cx-head">
        <h3 className="cx-label">
          {ch.label}
          {ch.tag && <span className="cx-tag">{ch.tag}</span>}
        </h3>
        <span className="cx-status" style={{ color: ch.state === "good" ? "var(--c-dim)" : color }}>
          {ch.state !== "good" && ch.state !== "unknown" && (
            <span className="cx-dot" style={{ background: color }} aria-hidden="true" />
          )}
          {ch.status}
        </span>
      </header>

      <div className="cx-value">
        {ch.value}
        {ch.unit && <span className="cx-unit">{ch.unit}</span>}
      </div>

      {ch.pos != null && <Band pos={ch.pos} labels={ch.bandLabels} state={ch.state} />}

      <p className="cx-read">{ch.read}</p>
    </article>
  );
}
