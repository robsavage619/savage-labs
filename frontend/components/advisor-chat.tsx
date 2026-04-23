"use client";

import { useEffect, useRef, useState } from "react";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { Eyebrow } from "@/components/ui/metric";
import { streamChat, type ChatMessage } from "@/lib/api";

const QUICK_ACTIONS = [
  { label: "Build programme", prompt: "Propose a weekly training programme aligned to my primary goal." },
  { label: "Swap exercise", prompt: "Suggest a substitution for an exercise I can't perform today." },
  { label: "Deload week", prompt: "Should I deload? Cite my ACWR and HRV data." },
  { label: "Plateau buster", prompt: "Identify my stalled lifts and prescribe a plateau break." },
  { label: "Session check-in", prompt: "I just finished training — give me a post-session summary and recovery protocol." },
];

interface Msg {
  role: "user" | "assistant";
  text: string;
  streaming?: boolean;
}

export function AdvisorChat() {
  const [open, setOpen] = useState(false);
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<Msg[]>([]);
  const [busy, setBusy] = useState(false);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen(true);
        setTimeout(() => inputRef.current?.focus(), 50);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  async function send(prompt: string) {
    if (!prompt.trim() || busy) return;
    setInput("");
    setBusy(true);

    const history: ChatMessage[] = [
      ...messages.map((m) => ({ role: m.role as "user" | "assistant", content: m.text })),
      { role: "user", content: prompt },
    ];

    setMessages((m) => [...m, { role: "user", text: prompt }, { role: "assistant", text: "", streaming: true }]);

    try {
      let full = "";
      for await (const chunk of streamChat(history)) {
        full += chunk;
        setMessages((m) => {
          const next = [...m];
          next[next.length - 1] = { role: "assistant", text: full, streaming: true };
          return next;
        });
      }
      setMessages((m) => {
        const next = [...m];
        next[next.length - 1] = { role: "assistant", text: full };
        return next;
      });
    } catch (err) {
      setMessages((m) => {
        const next = [...m];
        next[next.length - 1] = { role: "assistant", text: "Error connecting to advisor. Check that ANTHROPIC_API_KEY is set in shc.env." };
        return next;
      });
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className="fixed bottom-6 right-6 z-30 rounded-full border border-[var(--hairline-strong)] bg-[var(--card-hover)] px-4 py-2.5 text-[12px] text-[var(--text-primary)] shadow-[var(--shadow-pop)] hover:bg-[oklch(0.22_0_0)] transition-colors flex items-center gap-2"
      >
        <span className="inline-block h-1.5 w-1.5 rounded-full bg-[var(--positive)] animate-pulse" />
        Ask advisor
        <kbd className="rounded border border-[var(--hairline-strong)] px-1.5 text-[10px] text-[var(--text-dim)] tabular-nums">⌘K</kbd>
      </button>

      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent
          side="right"
          className="sm:max-w-none w-[420px] bg-[var(--bg-elevated)] border-l border-[var(--hairline)] p-0 flex flex-col"
        >
          <SheetTitle className="sr-only">Advisor</SheetTitle>
          <div className="p-4 border-b border-[var(--hairline)]">
            <div className="flex items-baseline justify-between">
              <Eyebrow>Advisor · Claude</Eyebrow>
              <span className="text-[10.5px] text-[var(--text-dim)]">health context cached</span>
            </div>
            <div className="mt-3 flex flex-wrap gap-1.5">
              {QUICK_ACTIONS.map((a) => (
                <button
                  key={a.label}
                  disabled={busy}
                  onClick={() => send(a.prompt)}
                  className="rounded-md border border-[var(--hairline)] px-2 py-1 text-[10.5px] text-[var(--text-muted)] hover:border-[var(--hairline-strong)] hover:text-[var(--text-primary)] transition-colors disabled:opacity-40"
                >
                  {a.label}
                </button>
              ))}
            </div>
          </div>

          <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 space-y-3">
            {messages.length === 0 ? (
              <div className="text-center py-16">
                <p className="text-[13px] text-[var(--text-muted)]">Ask your coach anything.</p>
                <p className="text-[11.5px] text-[var(--text-dim)] mt-1">Pick a quick action above, or type below.</p>
              </div>
            ) : (
              messages.map((m, i) => (
                <div
                  key={i}
                  className={`rounded-lg px-3 py-2 text-[12.5px] ${
                    m.role === "user"
                      ? "bg-[oklch(0.72_0.12_250/0.12)] border border-[oklch(0.72_0.12_250/0.2)]"
                      : "bg-[var(--card)] border border-[var(--hairline)]"
                  }`}
                >
                  {m.role === "assistant" && (
                    <p className="text-[9.5px] text-[var(--text-dim)] uppercase tracking-widest mb-0.5">
                      advisor{m.streaming ? " ·· " : ""}
                    </p>
                  )}
                  <p className="text-[var(--text-primary)] whitespace-pre-wrap leading-relaxed">
                    {m.text || (m.streaming ? <span className="animate-pulse">▋</span> : "")}
                  </p>
                </div>
              ))
            )}
          </div>

          <form
            onSubmit={(e) => {
              e.preventDefault();
              send(input);
            }}
            className="p-3 border-t border-[var(--hairline)]"
          >
            <input
              ref={inputRef}
              value={input}
              disabled={busy}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Ask about recovery, training, or programming…"
              className="w-full rounded-md bg-[var(--card)] border border-[var(--hairline)] px-3 py-2 text-[12.5px] text-[var(--text-primary)] placeholder:text-[var(--text-faint)] focus:border-[var(--hairline-strong)] focus:outline-none transition-colors disabled:opacity-50"
            />
            <p className="text-[9.5px] text-[var(--text-faint)] mt-1.5">Enter to send · health profile loaded as context</p>
          </form>
        </SheetContent>
      </Sheet>
    </>
  );
}
