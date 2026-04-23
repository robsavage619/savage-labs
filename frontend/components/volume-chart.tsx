"use client";

import { useQuery } from "@tanstack/react-query";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine } from "recharts";
import { api } from "@/lib/api";
import { Eyebrow } from "@/components/ui/metric";

const CustomTooltip = ({ active, payload, label }: any) => {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  return (
    <div className="rounded-lg border px-3 py-2 text-xs font-mono" style={{ background: "var(--card-hover)", borderColor: "var(--hairline-strong)" }}>
      <p className="mb-1 text-[var(--text-dim)]">{label}</p>
      <p className="text-[var(--text-primary)]">{d.volume_kg.toLocaleString()} kg total</p>
      <p className="text-[var(--text-muted)]">{d.sets} sets · {d.sessions} sessions</p>
    </div>
  );
};

export function VolumeChart() {
  const { data = [], isLoading } = useQuery({
    queryKey: ["weekly-volume"],
    queryFn: () => api.trainingWeekly(104),
    refetchInterval: 600_000,
  });

  // Show last 52 weeks for the chart; use all data for avg
  const formatted = data.slice(-52).map(d => ({ ...d, label: d.week.slice(5) }));
  const avg = data.length ? data.reduce((s, d) => s + d.volume_kg, 0) / data.length : 0;

  return (
    <div className="space-y-3">
      <div className="flex items-baseline justify-between">
        <Eyebrow>Weekly volume · 52 weeks</Eyebrow>
        {avg > 0 && (
          <span className="text-[10.5px] text-[var(--text-dim)] tabular-nums">avg {Math.round(avg / 1000)}k kg/wk</span>
        )}
      </div>
      {isLoading ? (
        <div className="h-[140px] shc-skeleton rounded" />
      ) : (
        <ResponsiveContainer width="100%" height={140}>
          <BarChart data={formatted} margin={{ top: 4, right: 0, left: -24, bottom: 0 }}>
            <XAxis dataKey="label" tick={{ fontSize: 9.5, fill: "var(--text-faint)" }} tickLine={false} axisLine={false} />
            <YAxis tick={{ fontSize: 9.5, fill: "var(--text-faint)" }} tickLine={false} axisLine={false} tickFormatter={v => `${(v / 1000).toFixed(0)}k`} />
            <Tooltip content={<CustomTooltip />} cursor={{ fill: "oklch(1 0 0 / 0.03)" }} />
            <ReferenceLine y={avg} stroke="var(--chart-baseline)" strokeDasharray="3 3" />
            <Bar dataKey="volume_kg" fill="var(--chart-line)" radius={[3, 3, 0, 0]} maxBarSize={28} />
          </BarChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}
