"use client";

import { useEffect } from "react";

/**
 * App-wide button feedback. Mounted once in the root layout, this attaches a
 * single capture-phase pointer listener and gives every <button> a satisfying,
 * futuristic response — a synthesized "tick", a haptic pulse (mobile), and an
 * accent ripple at the pointer. The visual press/hover/focus states live in
 * globals.css. Opt a button out with the class "no-tactile".
 *
 * Sound can be muted by setting localStorage["sl-tactile-mute"] = "1".
 */
export function TactileFeedback() {
  useEffect(() => {
    let audioCtx: AudioContext | null = null;
    const reduceMotion = window.matchMedia(
      "(prefers-reduced-motion: reduce)",
    ).matches;

    function tick() {
      if (localStorage.getItem("sl-tactile-mute") === "1") return;
      try {
        audioCtx ??= new (window.AudioContext ||
          (window as unknown as { webkitAudioContext: typeof AudioContext })
            .webkitAudioContext)();
        if (audioCtx.state === "suspended") void audioCtx.resume();

        const now = audioCtx.currentTime;
        const out = audioCtx.createGain();
        out.gain.setValueAtTime(0.0001, now);
        out.gain.exponentialRampToValueAtTime(0.07, now + 0.004);
        out.gain.exponentialRampToValueAtTime(0.0001, now + 0.09);
        out.connect(audioCtx.destination);

        // Bright chirp — a quick upward sweep reads as "futuristic".
        const lead = audioCtx.createOscillator();
        lead.type = "triangle";
        lead.frequency.setValueAtTime(820, now);
        lead.frequency.exponentialRampToValueAtTime(1480, now + 0.07);
        lead.connect(out);

        // Sub layer for body.
        const sub = audioCtx.createOscillator();
        sub.type = "sine";
        sub.frequency.setValueAtTime(220, now);
        sub.connect(out);

        lead.start(now);
        sub.start(now);
        lead.stop(now + 0.1);
        sub.stop(now + 0.1);
      } catch {
        /* audio unavailable — ignore */
      }
    }

    function ripple(x: number, y: number) {
      if (reduceMotion) return;
      const el = document.createElement("span");
      el.className = "sl-tactile-ripple";
      el.style.left = `${x}px`;
      el.style.top = `${y}px`;
      document.body.appendChild(el);
      const remove = () => el.remove();
      el.addEventListener("animationend", remove);
      window.setTimeout(remove, 700);
    }

    function onPointerDown(e: PointerEvent) {
      const target = e.target as Element | null;
      const btn = target?.closest?.(
        'button:not(:disabled):not(.no-tactile), [role="button"]:not(.no-tactile)',
      );
      if (!btn) return;
      if ((btn as HTMLButtonElement).disabled) return;
      tick();
      navigator.vibrate?.(8);
      ripple(e.clientX, e.clientY);
    }

    document.addEventListener("pointerdown", onPointerDown, true);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown, true);
      void audioCtx?.close();
    };
  }, []);

  return null;
}
