"use client";

import { useIsFetching, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";

/**
 * Pull WHOOP and Hevy now, then reload every query. A home-screen app has no browser
 * reload and most panels cache for minutes. A source that failed is named beside the
 * button; the panels still reload with whatever did arrive.
 */
export function RefreshButton() {
  const qc = useQueryClient();
  const sync = useMutation({ mutationFn: api.syncAll, onSettled: () => qc.invalidateQueries() });
  const fetching = useIsFetching() > 0;
  const busy = sync.isPending || fetching;
  const failed = Object.entries(sync.data?.results ?? {}).filter(([, r]) => !r.ok);
  const problem = sync.isError
    ? { label: "SYNC", detail: sync.error.message }
    : failed.length
      ? { label: failed.map(([s]) => s.toUpperCase()).join(" + "), detail: failed.map(([s, r]) => `${s}: ${r.error}`).join("; ") }
      : null;
  return (
    <>
      <button
        type="button"
        className={`sl-refresh${busy ? " spin" : ""}`}
        onClick={() => sync.mutate()}
        disabled={sync.isPending}
        aria-label="Sync devices and refresh"
        title="Sync WHOOP and Hevy now"
      >
        ↻
      </button>
      {problem && (
        <span className="sync-chip hot" role="status" title={problem.detail}>
          <i aria-hidden="true" />
          {problem.label}
          <em>sync failed</em>
        </span>
      )}
    </>
  );
}
