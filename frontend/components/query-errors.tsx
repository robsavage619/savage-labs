"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useSyncExternalStore } from "react";

/**
 * Names every query that failed, with one retry. Most panels guard on
 * `isLoading || !data`, so a failed request renders as a shimmer that never
 * resolves, which on a phone (no console) looks like "still loading". This is
 * the one place that says what actually failed.
 */
export function QueryErrors() {
  const qc = useQueryClient();
  const cache = qc.getQueryCache();
  const count = useSyncExternalStore(
    (notify) => cache.subscribe(notify),
    () => cache.findAll({ predicate: (q) => q.state.status === "error" }).length,
    () => 0,
  );
  if (!count) return null;
  const failed = cache.findAll({ predicate: (q) => q.state.status === "error" });
  const names = [...new Set(failed.map((q) => String(q.queryKey[0])))];
  return (
    <>
      <button type="button" className="sync-chip hot" popoverTarget="qerr-pop" title="Some panels failed to load">
        <i aria-hidden="true" />
        {count} failed
      </button>
      <div id="qerr-pop" popover="auto" className="sync-pop">
        <span className="sync-pop-k">Couldn&apos;t load</span>
        <b>{names.slice(0, 5).join(", ")}{names.length > 5 ? ` and ${names.length - 5} more` : ""}</b>
        <p>These panels may be stuck on a loading shimmer. Retry, and if they fail again the server is returning an error.</p>
        <button type="button" className="btn btn-primary" onClick={() => qc.refetchQueries({ predicate: (q) => q.state.status === "error" })}>
          Retry
        </button>
      </div>
    </>
  );
}
