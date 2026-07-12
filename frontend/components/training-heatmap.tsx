"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { localDate } from "@/lib/date";
import { Eyebrow } from "@/components/ui/metric";

const INTENSITY_COLORS = [
  "oklch(0.22 0 0)",
  "oklch(0.42 0.12 145)",
  "oklch(0.55 0.16 145)",
  "oklch(0.65 0.18 145)",
  "oklch(0.75 0.20 145)",
];

function buildWeekGrid(days: { date: string; intensity: number; sets: number; volume_kg: number }[]) {
  const map = new Map(days.map(d => [d.date, d]));
  const today = new Date();
  const start = new Date(today);
  start.setDate(start.getDate() - 52 * 7);
  start.setDate(start.getDate() - start.getDay()); // align to Sunday

  const weeks: { date: string; intensity: number; sets: number; volume_kg: number }[][] = [];
  let week: typeof weeks[0] = [];
  const cur = new Date(start);

  while (cur <= today) {
    const key = localDate(cur);
    week.push(map.get(key) ?? { date: key, intensity: 0, sets: 0, volume_kg: 0 });
    if (week.length === 7) { weeks.push(week); week = []; }
    cur.setDate(cur.getDate() + 1);
  }
  if (week.length) weeks.push(week);
  return weeks;
}

export function TrainingHeatmap() {
  const { data = [], isLoading } = useQuery({
    queryKey: ["heatmap"],
    queryFn: () => api.trainingHeatmap(52),
    refetchInterval: 600_000,
  });

  const weeks = buildWeekGrid(data);
  const totalDays = data.filter(d => d.sets > 0).length;
  const totalSets = data.reduce((s, d) => s + d.sets, 0);

  return (
    <div className="space-y-3">
      <div className="flex items-baseline justify-between">
        <Eyebrow>Consistency · 52 weeks</Eyebrow>
        <span className="text-[10.5px] text-[var(--text-dim)] tabular-nums">
          {totalDays} sessions · {totalSets.toLocaleString()} sets
        </span>
      </div>

      {isLoading ? (
        <div className="h-[88px] shc-skeleton rounded" />
      ) : (
        <div className="overflow-x-auto">
          <div className="flex gap-[3px] min-w-max">
            {weeks.map((week, wi) => (
              <div key={wi} className="flex flex-col gap-[3px]">
                {week.map((day, di) => (
                  <div
                    key={di}
                    title={day.sets > 0 ? `${day.date}: ${day.sets} sets · ${day.volume_kg.toLocaleString()}kg` : day.date}
                    className="w-[11px] h-[11px] rounded-[2px] cursor-default transition-opacity hover:opacity-75"
                    style={{ background: INTENSITY_COLORS[day.intensity] }}
                  />
                ))}
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="flex items-center gap-1.5 justify-end">
        <span className="text-[10px] text-[var(--text-faint)]">Less</span>
        {INTENSITY_COLORS.map((c, i) => (
          <div key={i} className="w-[11px] h-[11px] rounded-[2px]" style={{ background: c }} />
        ))}
        <span className="text-[10px] text-[var(--text-faint)]">More</span>
      </div>
    </div>
  );
}
