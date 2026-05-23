"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { Eyebrow } from "@/components/ui/metric";
import { CheckIcon, XIcon, RefreshIcon, SparkleIcon } from "@/components/ui/icons";

type SyncState =
  | { kind: "idle" }
  | { kind: "syncing" }
  | { kind: "ok" }
  | { kind: "err"; msg: string };

const RETROSPECTIVE_PROMPT = `Write Rob's post-workout retrospective for the session he just logged in Hevy.

STEP 1 — Read context (do NOT regenerate the morning health story — recovery metrics don't change post-workout; this is execution feedback only).
If the API is down (ECONNREFUSED), run: zsh /Users/robsavage/Projects/savage-health-center/dev-restart.sh — then wait 8s before fetching.
- GET http://127.0.0.1:8000/api/workout/retrospective/latest — gives the workout_id, session date, and whether a retrospective already exists. Use this workout_id in the POST.
- GET http://127.0.0.1:8000/api/training/after-action — per-exercise actual reps/load/RPE vs plan target, the next-session weight suggestion and verdict (drop/progress/repeat) for each lift, AND a "## VAULT RESEARCH" section: research notes selected server-side from this session's execution signals (rep misses, RPE overshoot, progression, missing RPE). Read that section and ground every adjustment in it.
- GET http://127.0.0.1:8000/api/workout/context — only if you need additional vault research beyond what after-action already returned.

STEP 2 — Write the retrospective summary.
Tone: a coach debriefing at the gym door — direct, plain language, second person ("you"). No academic phrasing, no filename citations. 2–3 short paragraphs:
¶1 — HOW IT WENT vs the plan. Did you hit the prescribed sets/reps/load? Where did RPE land relative to target? Call out the standout lift (best progression) and the one that lagged.
¶2 — WHAT TO ADJUST next session. Translate the after-action verdicts into plain guidance — which lifts to add load to, which to hold or drop, and why (cite the RPE/rep reason, not the percentage). Ground each adjustment in the mechanism from the VAULT RESEARCH section — e.g. why a rep miss means dropping load (effective reps near failure), not adding it.
¶3 — ANY FLAGS worth carrying forward (a lift that felt off, a rep miss pattern, a joint niggle if noted). Skip if nothing notable.

STEP 3 — POST to http://127.0.0.1:8000/api/workout/retrospective with body:
{
  "workout_id": "<from /workout/retrospective/latest>",
  "summary": "<the 2–3 paragraph text>",
  "progressive_overload_achieved": <true|false — did at least half the lifts hit progress/repeat-at-target?>,
  "rpe_vs_target": "<one phrase, e.g. 'on target', 'ran 1–2 above plan', 'easier than prescribed'>",
  "flags": ["<short flag strings, or empty>"],
  "vault_insights": ["<≥2 notes, each citing a vault filename from the VAULT RESEARCH section + the specific mechanism it justifies, e.g. 'effective-reps-hypertrophy.md: rep miss = too few effective reps near failure → drop load to finish the range'>"]
}

Confirm the POST succeeded.`;

export function PostWorkoutPanel() {
  const qc = useQueryClient();
  const [copied, setCopied] = useState(false);
  const [showPrompt, setShowPrompt] = useState(false);
  const [sync, setSync] = useState<SyncState>({ kind: "idle" });

  const { data, isLoading } = useQuery({
    queryKey: ["retrospective-latest"],
    queryFn: api.retrospectiveLatest,
    refetchInterval: 5 * 60_000,
  });

  function handleCopyPrompt() {
    if (navigator.clipboard?.writeText) {
      navigator.clipboard
        .writeText(RETROSPECTIVE_PROMPT)
        .then(() => {
          setCopied(true);
          setTimeout(() => setCopied(false), 2500);
        })
        .catch(() => fallbackCopy());
    } else {
      fallbackCopy();
    }
  }

  function fallbackCopy() {
    const el = document.createElement("textarea");
    el.value = RETROSPECTIVE_PROMPT;
    el.style.cssText = "position:fixed;top:-9999px;left:-9999px;opacity:0";
    document.body.appendChild(el);
    el.focus();
    el.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(el);
    if (ok) {
      setCopied(true);
      setTimeout(() => setCopied(false), 2500);
    } else {
      setShowPrompt(true);
    }
  }

  async function handleSync() {
    setSync({ kind: "syncing" });
    try {
      await api.syncAll();
      await qc.invalidateQueries();
      setSync({ kind: "ok" });
      setTimeout(() => setSync({ kind: "idle" }), 5000);
    } catch (e) {
      setSync({ kind: "err", msg: e instanceof Error ? e.message : "sync failed" });
      setTimeout(() => setSync({ kind: "idle" }), 4000);
    }
  }

  const retro = data?.retrospective ?? null;
  const sessionLabel =
    data?.days_ago === 0
      ? "today"
      : data?.days_ago === 1
      ? "yesterday"
      : data?.days_ago != null
      ? `${data.days_ago}d ago`
      : null;

  if (isLoading) {
    return (
      <div className="shc-card shc-enter p-5">
        <Eyebrow>Post-workout · debrief</Eyebrow>
        <div className="shc-skeleton h-[80px] mt-3" />
      </div>
    );
  }

  return (
    <div className="shc-card shc-enter overflow-hidden">
      <div className="px-5 py-4 flex items-center justify-between gap-3 border-b border-[var(--hairline)] flex-wrap">
        <div className="min-w-0">
          <Eyebrow>Post-workout · debrief</Eyebrow>
          <p className="mt-0.5 text-[13px] text-[var(--text-primary)]">
            {retro
              ? "Session retrospective — execution vs plan, synthesized"
              : "Run after you train — logs how the session went vs the plan"}
          </p>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          {(data?.session_date || sessionLabel) && (
            <span className="text-[10px] text-[var(--text-faint)] tabular-nums hidden sm:inline">
              {data?.session_date}
              {sessionLabel ? ` · ${sessionLabel}` : ""}
            </span>
          )}

          <button
            type="button"
            onClick={handleCopyPrompt}
            className={copied ? "btn btn-primary text-[11px]" : "btn btn-secondary text-[11px]"}
            title="Step 1 — copy prompt, paste into Claude Code after your workout to generate the retrospective"
          >
            <span className="text-[10px] mr-1 text-[var(--text-faint)]">1</span>
            {copied ? <><CheckIcon size={11} className="inline mr-1" />Prompt copied</> : <><SparkleIcon size={11} className="inline mr-1" />Copy CC prompt</>}
          </button>

          <button
            type="button"
            onClick={handleSync}
            disabled={sync.kind === "syncing"}
            className={sync.kind === "ok" ? "btn btn-primary text-[11px]" : "btn btn-secondary text-[11px]"}
            title="Step 2 — pull latest Hevy session + retrospective from the API"
          >
            <span className="text-[10px] mr-1 text-[var(--text-faint)]">2</span>
            <span
              className={sync.kind === "syncing" ? "animate-spin inline-block" : ""}
              style={sync.kind === "err" ? { color: "var(--negative)" } : undefined}
            >
              {sync.kind === "ok" ? <CheckIcon size={11} /> : sync.kind === "err" ? <XIcon size={11} /> : <RefreshIcon size={11} />}
            </span>{" "}
            {sync.kind === "syncing" ? "Syncing…" : sync.kind === "ok" ? "Synced" : sync.kind === "err" ? "Failed" : "Sync"}
          </button>
        </div>
      </div>

      <div className="px-5 py-5">
        {showPrompt && (
          <div className="mb-3 rounded-md border border-[var(--hairline-strong)] bg-[var(--surface-1)] p-3">
            <p className="text-[10.5px] text-[var(--text-dim)] uppercase tracking-wider mb-1.5">
              Copy this prompt manually
            </p>
            <pre className="whitespace-pre-wrap text-[11px] text-[var(--text-primary)] leading-relaxed">
              {RETROSPECTIVE_PROMPT}
            </pre>
          </div>
        )}

        {!data?.workout_id && (
          <p className="text-[12px] text-[var(--text-dim)] leading-relaxed">
            No logged session yet. After your workout syncs from Hevy, run the prompt to
            generate a retrospective and it will land here.
          </p>
        )}

        {data?.workout_id && !retro && (
          <div className="text-[12.5px] text-[var(--text-muted)] leading-relaxed space-y-2">
            <p>
              Your last session{sessionLabel ? ` (${sessionLabel})` : ""} hasn&apos;t been
              debriefed yet. Click{" "}
              <span className="text-[var(--text-primary)] font-medium">Copy CC prompt</span>,
              paste into Claude Code, then hit{" "}
              <span className="text-[var(--text-primary)] font-medium">Sync</span> to pull it back.
            </p>
            {data.exercises && (
              <p className="text-[var(--text-faint)]">{data.exercises}</p>
            )}
          </div>
        )}

        {retro && (
          <article>
            <div className="flex flex-wrap items-center gap-2 mb-4">
              {retro.progressive_overload_achieved != null && (
                <span
                  className="text-[10px] font-medium px-2 py-0.5 rounded-full"
                  style={{
                    background: retro.progressive_overload_achieved
                      ? "oklch(0.88 0.18 145 / 0.15)"
                      : "var(--surface-1)",
                    color: retro.progressive_overload_achieved
                      ? "oklch(0.88 0.18 145)"
                      : "var(--text-dim)",
                  }}
                >
                  {retro.progressive_overload_achieved ? "↑ overload achieved" : "overload not hit"}
                </span>
              )}
              {retro.rpe_vs_target && (
                <span className="text-[10px] text-[var(--text-dim)] px-2 py-0.5 rounded-full bg-[var(--surface-1)]">
                  RPE: {retro.rpe_vs_target}
                </span>
              )}
            </div>

            {retro.summary
              .split(/\n\n+/)
              .filter(Boolean)
              .map((para, i) => (
                <p
                  key={i}
                  className="text-[13px] leading-[1.75] text-[var(--text-muted)] mb-3"
                >
                  {para}
                </p>
              ))}

            {retro.flags.length > 0 && (
              <div className="mt-4 pt-3 border-t border-[var(--hairline)]">
                <p className="text-[9px] font-semibold uppercase tracking-widest text-[var(--text-dim)] mb-2">
                  Flags
                </p>
                <div className="flex flex-wrap gap-2">
                  {retro.flags.map((f, i) => (
                    <span
                      key={i}
                      className="text-[11px] px-2 py-0.5 rounded-full"
                      style={{ background: "var(--negative-soft, var(--surface-1))", color: "var(--text-muted)" }}
                    >
                      {f}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {retro.vault_insights.length > 0 && (
              <div className="mt-4 pt-3 border-t border-[var(--hairline)]">
                <p className="text-[9px] font-semibold uppercase tracking-widest text-[var(--text-dim)] mb-2">
                  Research
                </p>
                <ul className="space-y-1.5">
                  {retro.vault_insights.map((v, i) => (
                    <li key={i} className="text-[11.5px] text-[var(--text-dim)] leading-snug">
                      {v}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </article>
        )}
      </div>
    </div>
  );
}
