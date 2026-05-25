"use client";

import { useEffect, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { DailyState } from "@/lib/api";

// ── Waveform canvas ────────────────────────────────────────────────────────────

function Waveform({ recoveryScore }: { recoveryScore: number | null }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const rafRef = useRef<number>(0);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    // Color walks with recovery: red → amber → green → brand-blue (resting)
    let hue = 210;
    let chroma = 0.18;
    if (recoveryScore != null) {
      if (recoveryScore < 34) { hue = 25; chroma = 0.22; }
      else if (recoveryScore < 67) { hue = 25 + (75 - 25) * ((recoveryScore - 34) / 33); chroma = 0.20; }
      else { hue = 75 + (145 - 75) * ((recoveryScore - 67) / 33); chroma = 0.18; }
    }

    // Convert oklch to a usable CSS color string for canvas
    const waveColor = recoveryScore == null
      ? "oklch(0.55 0.18 210)"
      : recoveryScore >= 67
        ? "oklch(0.60 0.18 145)"
        : recoveryScore >= 34
          ? "oklch(0.60 0.18 75)"
          : "oklch(0.55 0.22 25)";

    let t = 0;

    function resize() {
      if (!canvas) return;
      canvas.width = canvas.offsetWidth * window.devicePixelRatio;
      canvas.height = canvas.offsetHeight * window.devicePixelRatio;
    }

    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(canvas);

    function draw() {
      if (!canvas || !ctx) return;
      const { width, height } = canvas;
      ctx.clearRect(0, 0, width, height);

      const midY = height / 2;
      // Amplitude scales with recovery — poor recovery = more erratic
      const amplitude = recoveryScore == null
        ? height * 0.28
        : height * (0.18 + (1 - recoveryScore / 100) * 0.22);

      ctx.beginPath();
      ctx.strokeStyle = waveColor;
      ctx.lineWidth = 1.2 * window.devicePixelRatio;
      ctx.globalAlpha = 0.22;
      ctx.shadowBlur = 6 * window.devicePixelRatio;
      ctx.shadowColor = waveColor;

      for (let x = 0; x <= width; x += 1) {
        const xn = x / width;
        // Composite of three sines at different frequencies + subtle noise
        const y = midY
          + Math.sin(xn * Math.PI * 6 + t * 0.6) * amplitude * 0.55
          + Math.sin(xn * Math.PI * 14 + t * 1.1) * amplitude * 0.28
          + Math.sin(xn * Math.PI * 3  + t * 0.3) * amplitude * 0.17;
        if (x === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }

      // Fade edges with a clipping gradient mask
      const grad = ctx.createLinearGradient(0, 0, width, 0);
      grad.addColorStop(0, "transparent");
      grad.addColorStop(0.12, waveColor);
      grad.addColorStop(0.88, waveColor);
      grad.addColorStop(1, "transparent");

      ctx.strokeStyle = grad as unknown as string;
      ctx.stroke();

      t += 0.012;
      rafRef.current = requestAnimationFrame(draw);
    }

    draw();
    return () => {
      cancelAnimationFrame(rafRef.current);
      ro.disconnect();
    };
  }, [recoveryScore]);

  return (
    <canvas
      ref={canvasRef}
      className="absolute inset-0 w-full h-full pointer-events-none"
      aria-hidden
    />
  );
}

// ── HUD stat strip ─────────────────────────────────────────────────────────────

function HudStat({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div className="flex flex-col items-center gap-[3px]">
      <span style={{
        fontFamily: "var(--font-orbitron)",
        fontSize: 7.5,
        fontWeight: 500,
        letterSpacing: "0.18em",
        color: "var(--text-dim)",
        textTransform: "uppercase",
      }}>
        {label}
      </span>
      <span style={{
        fontFamily: "var(--font-orbitron)",
        fontSize: 13,
        fontWeight: 700,
        letterSpacing: "0.06em",
        lineHeight: 1,
        color: color ?? "var(--text-primary)",
        fontVariantNumeric: "tabular-nums",
      }}>
        {value}
      </span>
    </div>
  );
}

function Divider() {
  return (
    <div style={{
      width: 1,
      height: 28,
      background: "var(--hairline)",
      flexShrink: 0,
    }} />
  );
}

function recoveryColor(score: number | null): string {
  if (score == null) return "var(--text-primary)";
  if (score >= 67) return "var(--positive)";
  if (score >= 34) return "var(--neutral)";
  return "var(--negative)";
}

// ── Composed header HUD ────────────────────────────────────────────────────────

export function HeaderHUD() {
  const { data } = useQuery<DailyState>({
    queryKey: ["daily-state"],
    queryFn: api.dailyState,
    staleTime: 5 * 60_000,
  });

  const recovery = data?.recovery;
  const sleep = data?.sleep;
  const readiness = data?.readiness;

  const recoveryScore = readiness?.score ?? null;
  const hrv = recovery?.hrv_ms;
  const rhr = recovery?.rhr;
  const sleepH = sleep?.last_hours;
  const skinTemp = recovery?.skin_temp_delta;

  return (
    <div className="relative flex-1 flex items-end justify-center pb-[6px] min-w-0 overflow-hidden" style={{ height: "100%" }}>
      {/* Stat strip */}
      <div className="relative z-10 flex items-center gap-4 px-6"
        style={{
          background: "oklch(0 0 0 / 0)",
        }}
      >
        {recoveryScore != null && (
          <HudStat
            label="Readiness"
            value={String(Math.round(recoveryScore))}
            color={recoveryColor(recoveryScore)}
          />
        )}
        {hrv != null && (
          <HudStat label="HRV" value={`${Math.round(hrv)}ms`} />
        )}
        {rhr != null && (
          <HudStat label="RHR" value={`${Math.round(rhr)}bpm`} />
        )}
        {sleepH != null && (
          <HudStat label="Sleep" value={`${sleepH.toFixed(1)}h`} />
        )}
        {skinTemp != null && (
          <HudStat
            label="Skin Δ"
            value={`${skinTemp >= 0 ? "+" : ""}${skinTemp.toFixed(1)}°F`}
            color={Math.abs(skinTemp) >= 0.9 ? "var(--negative)" : "var(--text-primary)"}
          />
        )}
      </div>
    </div>
  );
}
