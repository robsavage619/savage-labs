"use client";

import type { ReactNode } from "react";

/**
 * The one explanation affordance every card uses.
 *
 * Two problems this fixes. Explanations were on 10 of 21 cards and absent from
 * the densest one in the app — `prescription`, 561 words of per-muscle targets
 * with nothing telling you what a target is. And where they existed they were
 * bespoke: different wording, different placement, different disclosure widget.
 *
 * The DATA is never hidden — that was the whole point of retiring the
 * accordions. But an explanation is read once and then never again, so it
 * belongs behind a control in the header rather than as a paragraph stacked
 * above the numbers. Putting four of them in the sleep card pushed the actual
 * sleep bars below the fold, which is the same failure in a new costume.
 *
 * `summary` is the one-line answer to "what am I looking at" and shows inline,
 * always. `children` is the longer read — thresholds, caveats, how to act —
 * and opens on demand.
 */
export function CardHelp({
  summary,
  children,
}: {
  /** One sentence, plain English, no jargon. What this card tells you. */
  summary: string;
  /** Optional detail: thresholds, what to do about it, caveats. */
  children?: ReactNode;
}) {
  if (!children) {
    return <p className="card-help-summary">{summary}</p>;
  }
  return (
    <details className="card-help">
      <summary>
        <span className="card-help-summary">{summary}</span>
        <span className="card-help-more" aria-hidden="true">
          more
        </span>
      </summary>
      <div className="card-help-body">{children}</div>
    </details>
  );
}
