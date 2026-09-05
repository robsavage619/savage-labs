"use client";

import { cn } from "@/lib/utils";
import { useEffect, useRef, useState, type ReactNode } from "react";

export function Eyebrow({ children, className }: { children: ReactNode; className?: string }) {
  return <p className={cn("eyebrow", className)}>{children}</p>;
}

/** Boot-up count animation for hero numeric metrics. Honors prefers-reduced-motion. */
function useCountUp(target: number | null, enabled: boolean, durationMs = 520) {
  const [val, setVal] = useState<number | null>(enabled ? 0 : target);
  const fromRef = useRef<number>(0);
  const targetRef = useRef<number | null>(target);

  useEffect(() => {
    if (!enabled || target == null) {
      setVal(target);
      return;
    }
    if (typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      setVal(target);
      return;
    }
    const from = fromRef.current ?? 0;
    targetRef.current = target;
    const start = performance.now();
    let raf = 0;
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / durationMs);
      const eased = 1 - Math.pow(1 - t, 3);
      const next = from + (target - from) * eased;
      setVal(next);
      if (t < 1) raf = requestAnimationFrame(tick);
      else fromRef.current = target;
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target, enabled, durationMs]);

  return val;
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
  const glowClass =
    size === "xl"
      ? tone === "positive"
        ? "shc-glow-positive"
        : tone === "neutral"
        ? "shc-glow-neutral"
        : tone === "negative"
        ? "shc-glow-negative"
        : ""
      : "";
  // Count-up only for hero size with a numeric target.
  const numericTarget = typeof value === "number" && Number.isFinite(value) ? value : null;
  const animated = useCountUp(numericTarget, size === "xl");
  let display: string | number;
  if (size === "xl" && numericTarget != null && animated != null) {
    const decimals = Math.abs(numericTarget) > 0 && Math.abs(numericTarget) < 10 && !Number.isInteger(numericTarget) ? 1 : 0;
    display = animated.toFixed(decimals);
  } else {
    display = value;
  }
  return (
    <span className={cn(`metric-${size} tabular-nums`, toneClass, glowClass, className)}>
      {display}
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
  const ref = useRef<HTMLDivElement>(null);
  const [inView, setInView] = useState(false);
  useEffect(() => {
    const node = ref.current;
    if (!node || inView) return;
    const obs = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          if (e.isIntersecting) {
            setInView(true);
            obs.disconnect();
          }
        }
      },
      { threshold: 0.4 },
    );
    obs.observe(node);
    return () => obs.disconnect();
  }, [inView]);
  return (
    <div
      ref={ref}
      className={cn("flex items-baseline justify-between gap-3 shc-section-scan", inView && "in-view")}
    >
      <h2 className="shc-section-title">{children}</h2>
      {hint && <span className="text-[10px] text-[var(--text-faint)] tabular-nums">{hint}</span>}
    </div>
  );
}
