"use client";

import { cn } from "@/lib/utils";
import type { ReactNode } from "react";

export function Eyebrow({ children, className }: { children: ReactNode; className?: string }) {
  return <p className={cn("eyebrow", className)}>{children}</p>;
}

export function Metric({
  value,
  unit,
  size = "md",
  tone = "default",
  className,
}: {
  value: string | number;
  unit?: string;
  size?: "xl" | "lg" | "md";
  tone?: "default" | "positive" | "neutral" | "negative";
  className?: string;
}) {
  const toneClass =
    tone === "positive"
      ? "text-[var(--positive)]"
      : tone === "neutral"
      ? "text-[var(--neutral)]"
      : tone === "negative"
      ? "text-[var(--negative)]"
      : "text-[var(--text-primary)]";
  return (
    <span className={cn(`metric-${size} tabular-nums`, toneClass, className)}>
      {value}
      {unit && (
        <span className="ml-1 text-[11px] font-normal tracking-normal text-[var(--text-dim)] align-baseline">
          {unit}
        </span>
      )}
    </span>
  );
}

export function DeltaPill({
  value,
  unit,
  polarity,
  className,
}: {
  value: number;
  unit?: string;
  polarity?: "positive" | "neutral" | "negative";
  className?: string;
}) {
  const auto = value > 0 ? "positive" : value < 0 ? "negative" : "neutral";
  const p = polarity ?? auto;
  const color =
    p === "positive"
      ? "var(--positive)"
      : p === "negative"
      ? "var(--negative)"
      : "var(--neutral)";
  const bg =
    p === "positive"
      ? "var(--positive-soft)"
      : p === "negative"
      ? "var(--negative-soft)"
      : "var(--neutral-soft)";
  const arrow = value > 0 ? "↑" : value < 0 ? "↓" : "·";
  return (
    <span
      className={cn(
        "inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 text-[10.5px] font-medium tabular-nums",
        className,
      )}
      style={{ background: bg, color }}
    >
      {arrow} {Math.abs(value).toFixed(Math.abs(value) < 10 ? 1 : 0)}
      {unit}
    </span>
  );
}

export function Dot({ tone = "neutral" }: { tone?: "positive" | "neutral" | "negative" }) {
  const color = tone === "positive" ? "var(--positive)" : tone === "negative" ? "var(--negative)" : "var(--neutral)";
  return <span className="inline-block h-1.5 w-1.5 rounded-full" style={{ background: color }} />;
}

export function SectionTitle({ children, hint }: { children: ReactNode; hint?: ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <h2 className="shc-section-title">{children}</h2>
      {hint && <span className="text-[10px] text-[var(--text-faint)] tabular-nums">{hint}</span>}
    </div>
  );
}

export function HowToRead({ children }: { children: ReactNode }) {
  return (
    <p className="shc-helptext mt-1.5 mb-3">
      <span className="text-[var(--text-muted)] mr-1">How to read this.</span>
      {children}
    </p>
  );
}
