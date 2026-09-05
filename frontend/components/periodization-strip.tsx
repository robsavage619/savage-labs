"use client";

import { useQuery } from "@tanstack/react-query";
import { LineChart, Line, ReferenceLine, ResponsiveContainer, Tooltip, YAxis } from "recharts";

import { api } from "@/lib/api";
import { Eyebrow } from "@/components/ui/metric";

function formTone(tsb: number): "positive" | "neutral" | "negative" {
  if (tsb > 5) return "positive";
  if (tsb < -10) return "negative";
  return "neutral";
}

function formLabel(tsb: number): string {
  if (tsb > 15) return "Detraining risk";
  if (tsb > 5) return "Fresh";
  if (tsb >= -10) return "Optimal";
  if (tsb >= -20) return "Fatigued";
  return "Overreaching";
}

export function PeriodizationStrip() {
  const meso = useQuery({
    queryKey: ["mesocycle"],
    queryFn: api.mesocycle,
    refetchInterval: 5 * 60 * 1000,
  });
  const curve = useQuery({
    queryKey: ["load-curve", 90],
    queryFn: () => api.loadCurve(90),
    refetchInterval: 5 * 60 * 1000,
  });

  const m = meso.data;
  const c = curve.data;
  const today = c?.today ?? null;
  const tone = today ? formTone(today.tsb) : "neutral";
  const toneColor =
    tone === "positive" ? "var(--positive)" : tone === "negative" ? "var(--negative)" : "var(--text-primary)";

  const planned = m?.planned_weeks ?? 5;
  const week = m?.week_number ?? 1;
  const weeksLeft = m?.weeks_remaining ?? 0;
  const deloadWeek = planned;

  const cells = Array.from({ length: planned }, (_, i) => {
    const wk = i + 1;
    const isDeload = wk === deloadWeek;
    const isCurrent = wk === week;
    const isPast = wk < week;
    return { wk, isDeload, isCurrent, isPast };
  });

  return (
    <div className="@container shc-card shc-enter p-5">
      <div className="grid grid-cols-1 @2xl:grid-cols-2 items-start gap-x-6 gap-y-5">
        {/* LEFT: mesocycle progress */}
        <div className="min-w-0">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 min-w-0">
            <Eyebrow className="min-w-0">Mesocycle · {m?.status ?? "loading"}</Eyebrow>
            {m && (
              <span className="text-[10.5px] text-[var(--text-dim)] tabular-nums min-w-0">
                started {m.started_on}
              </span>
            )}
          </div>

          <div className="mt-2 flex flex-wrap items-baseline gap-x-2 gap-y-1 tabular-nums min-w-0">
            <span className="text-[28px] font-medium leading-none text-[var(--text-primary)]">
              W{week}
            </span>
            <span className="text-[13px] text-[var(--text-muted)]">
              / {planned}
            </span>
            <span className="text-[11.5px] text-[var(--text-dim)] @xs:ml-2 min-w-0">
              {m?.is_deload_week ? "deload now" : weeksLeft <= 1 ? "deload next" : `${weeksLeft - 1}w to deload`}
            </span>
          </div>

          {/* Phase strip */}
          <div className="mt-3 flex gap-1 min-w-0">
            {cells.map((cell) => {
              const bg = cell.isCurrent
                ? cell.isDeload
                  ? "var(--neutral, #d4a373)"
                  : "var(--accent, #6cf)"
                : cell.isPast
                ? "oklch(0.55 0 0)"
                : cell.isDeload
                ? "oklch(0.45 0.10 60 / 0.6)"
                : "oklch(0.30 0 0)";
              return (
                <div
                  key={cell.wk}
                  className="flex-1 h-[6px] rounded-sm transition-all"
                  style={{ background: bg, boxShadow: cell.isCurrent ? "0 0 8px var(--accent, #6cf)" : undefined }}
                  title={`Week ${cell.wk}${cell.isDeload ? " · deload" : ""}${cell.isCurrent ? " (now)" : ""}`}
                />
              );
            })}
          </div>
          <div className="mt-1 flex justify-between gap-2 text-[9.5px] text-[var(--text-faint)] uppercase tracking-wider min-w-0">
            <span>accumulation</span>
            <span>deload</span>
          </div>

          {m?.deload_trigger && (
            <p className="mt-2 text-[10.5px] text-[var(--neutral)] uppercase tracking-wider">
              deload trigger · {m.deload_trigger}
            </p>
          )}
        </div>

        {/* RIGHT: TSB / form */}
        <div className="min-w-0">
          <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 min-w-0">
            <Eyebrow className="min-w-0">Form · banister TSB</Eyebrow>
            <span className="text-[10.5px] text-[var(--text-dim)] tabular-nums min-w-0">
              {c?.tau ? `CTL ${c.tau.ctl_days}d · ATL ${c.tau.atl_days}d` : "loading"}
            </span>
          </div>

          <div className="mt-2 grid grid-cols-3 gap-2 @xs:gap-3 tabular-nums min-w-0">
            <div className="min-w-0">
              <p className="text-[10px] text-[var(--text-dim)] uppercase tracking-wider">CTL · fitness</p>
              <p className="text-[18px] font-medium text-[var(--text-primary)]">{today ? today.ctl.toFixed(1) : "—"}</p>
            </div>
            <div className="min-w-0">
              <p className="text-[10px] text-[var(--text-dim)] uppercase tracking-wider">ATL · fatigue</p>
              <p className="text-[18px] font-medium text-[var(--text-primary)]">{today ? today.atl.toFixed(1) : "—"}</p>
            </div>
            <div className="min-w-0">
              <p className="text-[10px] text-[var(--text-dim)] uppercase tracking-wider">TSB · form</p>
              <p className="text-[18px] font-medium" style={{ color: toneColor }}>
                {today ? (today.tsb > 0 ? `+${today.tsb.toFixed(1)}` : today.tsb.toFixed(1)) : "—"}
              </p>
              <p className="text-[10px] mt-0.5" style={{ color: toneColor }}>{today ? formLabel(today.tsb) : ""}</p>
            </div>
          </div>

          {/* TSB sparkline */}
          <div className="mt-3 h-[60px] min-w-0">
            {c && c.points.length > 0 && (
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={c.points} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
                  <YAxis hide domain={["auto", "auto"]} />
                  <ReferenceLine y={0} stroke="var(--hairline)" strokeDasharray="2 2" />
                  <ReferenceLine y={5} stroke="var(--positive)" strokeOpacity={0.3} strokeDasharray="2 2" />
                  <ReferenceLine y={-10} stroke="var(--negative)" strokeOpacity={0.3} strokeDasharray="2 2" />
                  <Line
                    type="monotone"
                    dataKey="tsb"
                    stroke={toneColor}
                    strokeWidth={1.5}
                    dot={false}
                    isAnimationActive={false}
                  />
                  <Line
                    type="monotone"
                    dataKey="ctl"
                    stroke="var(--text-dim)"
                    strokeWidth={1}
                    strokeDasharray="3 3"
                    dot={false}
                    isAnimationActive={false}
                  />
                  <Tooltip
                    contentStyle={{
                      background: "var(--panel)",
                      border: "1px solid var(--hairline)",
                      borderRadius: 6,
                      fontSize: 11,
                    }}
                    formatter={(v: number, name: string) => [v.toFixed(1), name.toUpperCase()]}
                    labelFormatter={(l: string) => l}
                  />
                </LineChart>
              </ResponsiveContainer>
            )}
          </div>
        </div>
      </div>

      <p className="mt-3 pt-3 text-[10.5px] text-[var(--text-dim)] leading-snug border-t border-[var(--hairline)]">
        <span className="text-[var(--text-muted)]">How to read this. </span>
        Phase strip shows mesocycle progression — dim cells are upcoming, the glow is this week, amber is the
        scheduled deload. Banister CTL (42d EWMA of composite load) is fitness; ATL (7d) is fatigue;
        TSB = CTL − ATL is form. Aim for −10 to +5 for productive training; +5 to +15 right before peak events.
        Sustained TSB &lt; −20 is overreach territory.
      </p>
    </div>
  );
}
