"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { WarningIcon } from "@/components/ui/icons";

export function SyncStatus() {
  const { data } = useQuery({
    queryKey: ["oauth-status"],
    queryFn: api.oauthStatus,
    refetchInterval: 60_000,
  });

  const needsReauth = data?.find((s) => s.needs_reauth);
  if (!needsReauth) return null;

  return (
    <div className="rounded-lg border border-[oklch(0.75_0.18_75/0.3)] bg-[oklch(0.75_0.18_75/0.08)] px-4 py-2 text-sm text-[oklch(0.75_0.18_75)] flex items-center gap-2">
      <WarningIcon size={14} />
      <span>
        {needsReauth.source.toUpperCase()} sync needs re-authorization.{" "}
        <a href={`http://127.0.0.1:8000/auth/${needsReauth.source}/login`} className="underline">
          Reconnect →
        </a>
      </span>
    </div>
  );
}
