"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Eyebrow } from "@/components/ui/metric";

const STORY_PROMPT = `Read the live health context from GET http://127.0.0.1:8000/api/briefing/context, then read the relevant research notes from Rob's vault at ~/Vault/savage_vault/wiki/.

Write a narrative health briefing — not bullets, not a dashboard. 4–6 paragraphs of clear prose addressed to Rob in second person. Lead with the most important signal of the moment, not chronology. Cite specific numbers from the live data (recovery score, HRV deviation σ, ACWR, sleep totals) but always anchor them to meaning, not just the number. Weave in vault research naturally by source name when relevant. End with one paragraph on near-term trajectory: what the next 1–2 weeks should look like.

Constraints: no "as your AI advisor I think" framing. No motivational filler. Never imply chronic propranolol use — it is PRN/occasional, reference it only if today's check-in shows it was taken. Never invent metrics not in the live context.

POST the result to http://127.0.0.1:8000/api/health-story with body { "narrative": "<your text>", "sources": [<list of vault note filenames cited>], "model": "claude-sonnet-4-6" }. Confirm success.`;

type SyncState = { kind: "idle" } | { kind: "syncing" } | { kind: "ok" } | { kind: "err"; msg: string };

interface StoryData {
  story_date?: string;
  generated_at?: string;
  model?: string;
  narrative?: string;
  sources?: string[];
}

export function HealthStory() {
  const qc = useQueryClient();
  const [copied, setCopied] = useState(false);
  const [showPrompt, setShowPrompt] = useState(false);
  const [sync, setSync] = useState<SyncState>({ kind: "idle" });

  const storyQ = useQuery<StoryData>({
    queryKey: ["health-story"],
    queryFn: async () => {
      const res = await fetch(`${process.env.NEXT_PUBLIC_SHC_API ?? "http://127.0.0.1:8000"}/api/health-story`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return (await res.json()) as StoryData;
    },
  });

  const story = storyQ.data;
  const hasContent = !!story?.narrative;

  function handleCopyPrompt() {
    if (navigator.clipboard?.writeText) {
      navigator.clipboard
        .writeText(STORY_PROMPT)
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
    el.value = STORY_PROMPT;
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
      setTimeout(() => setSync({ kind: "idle" }), 3000);
    } catch (e) {
      setSync({ kind: "err", msg: e instanceof Error ? e.message : "sync failed" });
      setTimeout(() => setSync({ kind: "idle" }), 4000);
    }
  }

  const ageLabel = story?.generated_at
    ? new Date(story.generated_at).toLocaleString([], {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      })
    : null;

  return (
    <div className="shc-card shc-enter overflow-hidden">
      <div className="px-5 py-4 flex items-center justify-between gap-3 border-b border-[var(--hairline)] flex-wrap">
        <div className="flex items-center gap-3 min-w-0">
          <span
            className="inline-flex items-center justify-center h-6 w-6 rounded-full text-[10px] font-bold uppercase tracking-wider"
            style={{
              background: "oklch(0.88 0.18 145 / 0.18)",
              color: "oklch(0.88 0.18 145)",
            }}
          >
            AI
          </span>
          <div className="min-w-0">
            <Eyebrow>Your story</Eyebrow>
            <p className="mt-0.5 text-[13px] text-[var(--text-primary)]">
              Narrative briefing — metrics + research synthesized into one read
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          {ageLabel && (
            <span className="text-[10px] text-[var(--text-faint)] tabular-nums hidden sm:inline">
              {ageLabel}
            </span>
          )}

          <button
            type="button"
            onClick={handleCopyPrompt}
            className={copied ? "btn btn-primary text-[11px]" : "btn btn-secondary text-[11px]"}
            title="Step 1 — copy prompt, paste into Claude Code to generate today's story"
          >
            <span className="text-[10px] mr-1 text-[var(--text-faint)]">1</span>
            {copied ? "✓ Prompt copied" : "✦ Copy CC prompt"}
          </button>

          <button
            type="button"
            onClick={handleSync}
            disabled={sync.kind === "syncing"}
            className={sync.kind === "ok" ? "btn btn-primary text-[11px]" : "btn btn-secondary text-[11px]"}
            title="Step 2 — pull latest WHOOP + Hevy + AI story from the API"
          >
            <span className="text-[10px] mr-1 text-[var(--text-faint)]">2</span>
            <span
              className={sync.kind === "syncing" ? "animate-spin inline-block" : ""}
              style={sync.kind === "err" ? { color: "var(--negative)" } : undefined}
            >
              {sync.kind === "ok" ? "✓" : sync.kind === "err" ? "✗" : "↻"}
            </span>{" "}
            {sync.kind === "syncing"
              ? "Syncing…"
              : sync.kind === "ok"
              ? "Synced"
              : sync.kind === "err"
              ? "Failed"
              : "Sync"}
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
              {STORY_PROMPT}
            </pre>
          </div>
        )}

        {storyQ.isLoading && (
          <div className="space-y-2">
            {Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="shc-skeleton h-[14px]" />
            ))}
          </div>
        )}

        {!storyQ.isLoading && !hasContent && (
          <div className="text-[12.5px] text-[var(--text-muted)] leading-relaxed space-y-2">
            <p>
              No story yet for today. Click{" "}
              <span className="text-[var(--text-primary)] font-medium">Copy CC prompt</span>,
              paste into Claude Code, then hit{" "}
              <span className="text-[var(--text-primary)] font-medium">Sync</span> to pull
              it back.
            </p>
            <p className="text-[var(--text-faint)]">
              Claude reads your live biometrics + vault research, writes a
              narrative analysis, and POSTs it to /api/health-story. Sync pulls it
              alongside WHOOP and Hevy data.
            </p>
          </div>
        )}

        {hasContent && (
          <article className="prose-narrative text-[14px] leading-[1.7] text-[var(--text-primary)] space-y-4">
            {story.narrative!.split(/\n\n+/).map((para, i) => (
              <p key={i}>{para}</p>
            ))}
            {story.sources && story.sources.length > 0 && (
              <div className="pt-2 mt-3 border-t border-[var(--hairline)]">
                <span className="text-[10px] uppercase tracking-wider text-[var(--text-dim)] mr-2">
                  Sources
                </span>
                {story.sources.map((s, i) => (
                  <span
                    key={i}
                    className="inline-block mr-1.5 mt-1 px-2 py-0.5 rounded-full border border-[var(--hairline)] text-[10.5px] text-[var(--text-muted)]"
                  >
                    {s}
                  </span>
                ))}
              </div>
            )}
          </article>
        )}
      </div>
    </div>
  );
}
