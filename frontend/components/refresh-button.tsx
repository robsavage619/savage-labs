"use client";

import { useIsFetching, useQueryClient } from "@tanstack/react-query";

/**
 * Reload every query. A home-screen app has no browser reload and most panels
 * cache for minutes, so after a sync the screen could show old numbers with no way out.
 */
export function RefreshButton() {
  const qc = useQueryClient();
  const busy = useIsFetching() > 0;
  return (
    <button type="button" className={`sl-refresh${busy ? " spin" : ""}`} onClick={() => qc.invalidateQueries()} aria-label="Refresh data" title="Refresh">
      ↻
    </button>
  );
}
