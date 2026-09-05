import type { ReactNode } from "react";
import type { ChannelState } from "@/lib/reads";

/**
 * One sentence saying what the number above it means for today.
 *
 * The dot is the only colour this component spends, and only on watch/alert —
 * a "good" read needs no tint, and a board where every sentence is coloured
 * says nothing. Sizing comes from --fs-read so every read on the board is set
 * at the same optical weight, one notch under body copy.
 */
export function PlainRead({
  children,
  state = "unknown",
  className = "",
}: {
  children: ReactNode;
  state?: ChannelState;
  className?: string;
}) {
  const dot =
    state === "alert" ? "var(--bad)" : state === "watch" ? "var(--warn)" : null;

  return (
    <p
      className={`flex items-start gap-1.5 min-w-0 text-[var(--text-muted)] ${className}`}
      style={{
        fontSize: "var(--fs-read)",
        lineHeight: 1.55,
        textWrap: "pretty",
      }}
    >
      {dot && (
        <span
          aria-hidden
          className="mt-[6px] inline-block h-1.5 w-1.5 shrink-0 rounded-full"
          style={{ background: dot }}
        />
      )}
      <span className="min-w-0">{children}</span>
    </p>
  );
}

/** A read with its channel named — for stacks where the number sits in a
 *  separate compact tile and the sentence needs to say which tile it explains. */
export function LabelledRead({
  label,
  state = "unknown",
  children,
}: {
  label: string;
  state?: ChannelState;
  children: ReactNode;
}) {
  return (
    <div className="min-w-0">
      <p className="text-[10px] text-[var(--text-dim)] uppercase tracking-wider">{label}</p>
      <PlainRead state={state} className="mt-0.5">
        {children}
      </PlainRead>
    </div>
  );
}
