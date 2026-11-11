"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

/**
 * Sources that actually have a `/auth/<source>/login` redirect on the API.
 * Only WHOOP does. DUPR authenticates with a stored email/password, so it has
 * no login route to send Rob to — the banner used to link one anyway and the
 * "Reconnect →" click 404'd.
 */
const OAUTH_SOURCES = new Set(["whoop"]);

/**
 * A sync problem as a small chip beside LIVE, not a page-wide banner. The
 * detail opens in a native popover (light-dismiss and Escape come free).
 * WHOOP gets the louder tone: it feeds every gate, DUPR only the rating.
 */
export function SyncStatus() {
  const { data } = useQuery({ queryKey: ["oauth-status"], queryFn: api.oauthStatus, refetchInterval: 60_000 });
  const issue = data?.find((s) => s.needs_reauth) ?? data?.find((s) => s.last_error);
  if (!issue) return null;

  const src = issue.source.toUpperCase();
  const reauth = issue.needs_reauth;
  const canRedirect = reauth && OAUTH_SOURCES.has(issue.source);
  const tone = issue.source === "whoop" ? "hot" : "warm";

  return (
    <>
      <button type="button" className={`sync-chip ${tone}`} popoverTarget="sync-pop" title="Sync needs attention">
        <i aria-hidden="true" />
        {src}
        <em>{reauth ? "sign-in" : "failing"}</em>
      </button>
      <div id="sync-pop" popover="auto" className="sync-pop">
        <span className="sync-pop-k">{src} sync</span>
        <b>{reauth ? "Automatic logins are paused" : "Recent syncs are failing"}</b>
        <p>
          {reauth
            ? canRedirect
              ? "The connection expired. Reconnect and the next sync picks up where it left off."
              : "The login was refused or wants an emailed code. Sort it out at the source, then run a manual sync."
            : `New data may be missing. ${issue.last_error ?? ""}`}
        </p>
        {canRedirect && (
          <a className="btn btn-primary" href={`http://127.0.0.1:8000/auth/${issue.source}/login`}>
            Reconnect {src}
          </a>
        )}
      </div>
    </>
  );
}
