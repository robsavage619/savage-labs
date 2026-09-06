"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { WarningIcon } from "@/components/ui/icons";

/**
 * Sources that actually have a `/auth/<source>/login` redirect on the API.
 * Only WHOOP does. DUPR authenticates with a stored email/password, so it has
 * no login route to send Rob to — the banner used to link one anyway and the
 * "Reconnect →" click 404'd.
 */
const OAUTH_SOURCES = new Set(["whoop"]);

export function SyncStatus() {
  const { data } = useQuery({
    queryKey: ["oauth-status"],
    queryFn: api.oauthStatus,
    refetchInterval: 60_000,
  });

  const needsReauth = data?.find((s) => s.needs_reauth);
  if (!needsReauth) return null;

  const source = needsReauth.source;
  const canRedirect = OAUTH_SOURCES.has(source);

  return (
    <div className="rounded-lg border border-[oklch(0.75_0.18_75/0.3)] bg-[oklch(0.75_0.18_75/0.08)] px-4 py-2 text-sm text-[oklch(0.75_0.18_75)] flex items-center gap-2">
      <WarningIcon size={14} />
      <span>
        {source.toUpperCase()} sync needs re-authorization.{" "}
        {canRedirect ? (
          <a href={`http://127.0.0.1:8000/auth/${source}/login`} className="underline">
            Reconnect →
          </a>
        ) : (
          <span className="text-[var(--text-muted)]">
            Stored credentials were rejected — update them and re-run the sync.
          </span>
        )}
      </span>
    </div>
  );
}
