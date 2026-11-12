"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, apiUrl } from "@/lib/api";

/**
 * Sources that actually have a `/auth/<source>/login` redirect on the API.
 * Only WHOOP does. DUPR authenticates with a stored email/password, so it has
 * no login route to send Rob to — the banner used to link one anyway and the
 * "Reconnect →" click 404'd.
 */
const OAUTH_SOURCES = new Set(["whoop"]);

/**
 * DUPR's sign-in has a second step: a 6-digit code it emails. Ask for one, type it
 * here, and the app keeps the session DUPR returns. After that the sync renews
 * itself, so this should be needed rarely.
 */
function DuprCodeForm() {
  const qc = useQueryClient();
  const [code, setCode] = useState("");
  const ask = useMutation({ mutationFn: () => api.duprRequestCode() });
  const verify = useMutation({
    mutationFn: () => api.duprVerify(code.trim()),
    onSuccess: () => {
      setCode("");
      qc.invalidateQueries({ queryKey: ["oauth-status"] });
      qc.invalidateQueries({ queryKey: ["freshness"] });
    },
  });
  const sent = ask.isSuccess && ask.data.status === "code_sent";
  return (
    <form
      className="dupr-link"
      onSubmit={(e) => {
        e.preventDefault();
        if (/^\d{4,12}$/.test(code.trim())) verify.mutate();
      }}
    >
      <button type="button" onClick={() => ask.mutate()} disabled={ask.isPending}>
        {ask.isPending ? "Asking DUPR…" : sent ? "Email me another code" : "Email me a code"}
      </button>
      {ask.isError && <p className="dupr-link-msg bad">{ask.error.message}</p>}
      {sent && <p className="dupr-link-msg">Code sent. Check your email and type it below.</p>}
      <input inputMode="numeric" autoComplete="one-time-code" value={code} placeholder="6-digit code" aria-label="DUPR code" onChange={(e) => setCode(e.target.value)} />
      <button type="submit" disabled={!/^\d{4,12}$/.test(code.trim()) || verify.isPending}>
        {verify.isPending ? "Checking…" : "Verify"}
      </button>
      {verify.isError && <p className="dupr-link-msg bad">{verify.error.message}</p>}
      {verify.isSuccess && <p className="dupr-link-msg">Linked. The next sync renews itself.</p>}
    </form>
  );
}

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
              : issue.source === "dupr"
                ? "DUPR signs in with a 6-digit code it emails. Ask for one, type it below, and the app keeps the session. The sync renews itself after that."
                : "The login was refused or wants an emailed code. Sort it out at the source, then run a manual sync."
            : `New data may be missing. ${issue.last_error ?? ""}`}
        </p>
        {reauth && issue.source === "dupr" && <DuprCodeForm />}
        {canRedirect && (
          <a className="btn btn-primary" href={apiUrl(`/auth/${issue.source}/login`)}>
            Reconnect {src}
          </a>
        )}
      </div>
    </>
  );
}

const ago = (h: number) => (h < 48 ? `${Math.round(h)}h` : `${Math.round(h / 24)}d`);

/**
 * Sources that have gone quiet, each against its own cadence. LiveBadge takes the
 * newest sync of any source, so one fresh feed hid every stale one; this names them.
 * Hidden when everything is on time.
 */
export function Freshness() {
  const { data } = useQuery({ queryKey: ["freshness"], queryFn: api.freshness, refetchInterval: 5 * 60_000 });
  const late = (data ?? []).filter((s) => s.state === "stale");
  if (!late.length) return null;
  return (
    <>
      <button type="button" className="sync-chip warm" popoverTarget="fresh-pop" title="Some data is overdue">
        <i aria-hidden="true" />
        {late.length === 1 ? late[0].label : `${late.length} sources`}
        <em>{late.length === 1 && late[0].age_h != null ? ago(late[0].age_h) : "late"}</em>
      </button>
      <div id="fresh-pop" popover="auto" className="sync-pop">
        <span className="sync-pop-k">Overdue data</span>
        <b>{late.map((s) => s.label).join(", ")}</b>
        <p>
          {late.map((s) => `${s.label}: nothing for ${s.age_h != null ? ago(s.age_h) : "a long while"} (expected every ${ago(s.stale_after_h)})`).join(". ")}.
        </p>
      </div>
    </>
  );
}

