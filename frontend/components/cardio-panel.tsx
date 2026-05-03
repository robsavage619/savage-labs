"use client";

import { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api, type CardioSession } from "@/lib/api";
import { Eyebrow } from "@/components/ui/metric";

const AGE = 39;
// Tanaka formula: 208 − 0.7×age (more accurate than 220−age for 30–65)
function hrMax(shift = 0): number {
  return Math.round(208 - 0.7 * AGE - shift);
}

const MODALITY_LABEL: Record<string, string> = {
  pickleball: "Pickleball",
  tennis: "Tennis",
  walk: "Walk",
  run: "Run",
  bike: "Bike",
  hike: "Hike",
  swim: "Swim",
  yoga: "Yoga",
  other: "Other",
};

const MODALITY_ICON: Record<string, string> = {
  pickleball: "🏓",
  tennis: "🎾",
  walk: "🚶",
  run: "🏃",
  bike: "🚴",
  hike: "🥾",
  swim: "🏊",
  yoga: "🧘",
  other: "•",
};

function modalityKey(kind: string): string {
  const k = kind.toLowerCase();
  for (const m of Object.keys(MODALITY_LABEL)) {
    if (k.includes(m)) return m;
  }
  return "other";
}

function rpeColor(rpe: number | null | undefined): string {
  if (rpe == null) return "var(--text-faint)";
  if (rpe >= 8) return "var(--negative)";
  if (rpe >= 6) return "var(--neutral)";
  return "var(--positive)";
}

function hrZone(hr: number | null | undefined, shift = 0): string {
  if (hr == null) return "—";
  const max = hrMax(shift);
  const pct = hr / max;
  if (pct < 0.6) return "Z1";
  if (pct < 0.7) return "Z2";
  if (pct < 0.8) return "Z3";
  if (pct < 0.9) return "Z4";
  return "Z5";
}

// ── Story-telling charts ──────────────────────────────────────────────────────

const ZONE_FILL = {
  z12: "oklch(0.62 0.16 145 / 0.85)",   // aerobic base — green
  z3:  "oklch(0.65 0.14 80 / 0.85)",    // tempo — amber
  z45: "oklch(0.55 0.20 25 / 0.85)",    // threshold/VO2 — red
};

function bucketByWeek(
  sessions: CardioSession[],
  weeks: number,
  hrShift = 0,
): { weekStart: string; label: string; z12: number; z3: number; z45: number; total: number }[] {
  // Anchor the rightmost bucket to this Monday so the bars stay aligned with
  // calendar weeks rather than rolling 7-day buckets.
  const today = new Date();
  const monday = new Date(today);
  monday.setHours(0, 0, 0, 0);
  monday.setDate(monday.getDate() - ((monday.getDay() + 6) % 7));

  const bins = Array.from({ length: weeks }, (_, i) => {
    const start = new Date(monday);
    start.setDate(monday.getDate() - (weeks - 1 - i) * 7);
    return {
      weekStart: start.toISOString().slice(0, 10),
      label: `${start.getMonth() + 1}/${start.getDate()}`,
      z12: 0,
      z3: 0,
      z45: 0,
      total: 0,
    };
  });

  for (const s of sessions) {
    const ts = new Date(s.date + "T00:00:00").getTime();
    const idx = bins.findIndex((b, i) => {
      const start = new Date(b.weekStart + "T00:00:00").getTime();
      const end = i + 1 < bins.length
        ? new Date(bins[i + 1].weekStart + "T00:00:00").getTime()
        : Number.POSITIVE_INFINITY;
      return ts >= start && ts < end;
    });
    if (idx === -1) continue;
    const dur = s.duration_min ?? 0;
    if (!dur) continue;
    const z = hrZone(s.avg_hr, hrShift);
    if (z === "Z4" || z === "Z5") bins[idx].z45 += dur;
    else if (z === "Z3") bins[idx].z3 += dur;
    else bins[idx].z12 += dur; // Z1, Z2, or unknown HR → assume base aerobic
    bins[idx].total += dur;
  }
  return bins;
}

function WeeklyZoneVolume({
  sessions,
  hrShift,
}: {
  sessions: CardioSession[];
  hrShift: number;
}) {
  const data = useMemo(() => bucketByWeek(sessions, 12, hrShift), [sessions, hrShift]);
  const recent4 = data.slice(-4);
  const totalMin = recent4.reduce((a, b) => a + b.total, 0);
  const lowMin = recent4.reduce((a, b) => a + b.z12, 0);
  const highMin = recent4.reduce((a, b) => a + b.z3 + b.z45, 0);
  const polarizedPctLow = totalMin > 0 ? (lowMin / totalMin) * 100 : 0;
  // 80/20 polarized model: 80% Z1+Z2, 20% Z3-5. Within ±5% = on model.
  const polarizedStatus =
    totalMin === 0
      ? "no data"
      : polarizedPctLow >= 75 && polarizedPctLow <= 85
        ? "polarized ✓"
        : polarizedPctLow >= 70 && polarizedPctLow < 90
          ? "near polarized"
          : polarizedPctLow < 70
            ? "intensity-heavy"
            : "all base";
  const polarizedColor =
    polarizedStatus === "polarized ✓"
      ? "var(--positive)"
      : polarizedStatus === "intensity-heavy"
        ? "var(--negative)"
        : "var(--neutral)";

  const maxBar = Math.max(...data.map((d) => d.total), 200);

  return (
    <div className="space-y-2">
      <div className="flex items-baseline justify-between">
        <Eyebrow>Weekly volume by zone · 12w</Eyebrow>
        <span className="text-[10.5px] tabular-nums" style={{ color: polarizedColor }}>
          {polarizedPctLow.toFixed(0)}% low / {(100 - polarizedPctLow).toFixed(0)}% high
          <span className="text-[var(--text-faint)] ml-1">· {polarizedStatus}</span>
        </span>
      </div>
      <div className="h-[160px]">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 4, right: 8, left: -22, bottom: 0 }}>
            <CartesianGrid stroke="var(--hairline)" strokeDasharray="2 4" vertical={false} />
            <XAxis
              dataKey="label"
              tick={{ fontSize: 9.5, fill: "var(--text-faint)" }}
              axisLine={false}
              tickLine={false}
              interval={1}
            />
            <YAxis
              tick={{ fontSize: 9.5, fill: "var(--text-faint)" }}
              axisLine={false}
              tickLine={false}
              width={30}
              domain={[0, maxBar]}
              tickFormatter={(v) => `${v}`}
            />
            <ReferenceLine
              y={150}
              stroke="var(--chart-baseline)"
              strokeDasharray="3 3"
              label={{ value: "150 min/wk", position: "right", fontSize: 9, fill: "var(--text-faint)" }}
            />
            <Tooltip
              contentStyle={{
                background: "var(--card-hover)",
                border: "1px solid var(--hairline-strong)",
                borderRadius: 8,
                fontSize: 11,
              }}
              cursor={{ fill: "oklch(1 0 0 / 0.03)" }}
              formatter={(v: number, name: string) => [`${v} min`, name]}
            />
            <Bar dataKey="z12" stackId="a" fill={ZONE_FILL.z12} name="Z1–Z2" radius={[0, 0, 0, 0]} />
            <Bar dataKey="z3"  stackId="a" fill={ZONE_FILL.z3}  name="Z3"     radius={[0, 0, 0, 0]} />
            <Bar dataKey="z45" stackId="a" fill={ZONE_FILL.z45} name="Z4–Z5"  radius={[3, 3, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <div className="flex flex-wrap gap-3 text-[10px] text-[var(--text-muted)]">
        <span className="flex items-center gap-1">
          <span className="inline-block w-2.5 h-2.5 rounded-sm" style={{ background: ZONE_FILL.z12 }} />
          Z1–Z2 base
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block w-2.5 h-2.5 rounded-sm" style={{ background: ZONE_FILL.z3 }} />
          Z3 tempo
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block w-2.5 h-2.5 rounded-sm" style={{ background: ZONE_FILL.z45 }} />
          Z4–Z5 threshold/VO2
        </span>
        <span className="text-[var(--text-faint)] ml-auto">Polarized model: 80% low / 20% high</span>
      </div>
    </div>
  );
}

function PickleballEfficiency({
  sessions,
  hrShift,
}: {
  sessions: CardioSession[];
  hrShift: number;
}) {
  // Filter to pickleball sessions with HR, sort ascending by date, take last 16.
  const points = useMemo(() => {
    const filtered = sessions
      .filter((s) => modalityKey(s.kind) === "pickleball" && s.avg_hr != null && (s.duration_min ?? 0) >= 10)
      .sort((a, b) => a.date.localeCompare(b.date));
    const tail = filtered.slice(-16);
    return tail.map((s) => ({
      date: s.date.slice(5),
      hr: s.avg_hr!,
      pctHrMax: Math.round((s.avg_hr! / hrMax(hrShift)) * 100),
      duration: s.duration_min ?? 0,
    }));
  }, [sessions, hrShift]);

  // Linear regression to detect drift direction.
  const slope = useMemo(() => {
    if (points.length < 4) return null;
    const n = points.length;
    const xs = points.map((_, i) => i);
    const ys = points.map((p) => p.hr);
    const sx = xs.reduce((a, b) => a + b, 0);
    const sy = ys.reduce((a, b) => a + b, 0);
    const sxy = xs.reduce((a, b, i) => a + b * ys[i], 0);
    const sxx = xs.reduce((a, b) => a + b * b, 0);
    return (n * sxy - sx * sy) / (n * sxx - sx * sx);
  }, [points]);

  const trendLabel =
    slope == null
      ? null
      : slope < -0.3
        ? "↓ HR dropping (fitness ↑)"
        : slope > 0.3
          ? "↑ HR creeping up"
          : "→ stable";
  const trendColor =
    slope == null
      ? "var(--text-faint)"
      : slope < -0.3
        ? "var(--positive)"
        : slope > 0.3
          ? "var(--negative)"
          : "var(--neutral)";

  if (points.length < 3) {
    return (
      <div className="space-y-2">
        <Eyebrow>Pickleball HR efficiency</Eyebrow>
        <div className="h-[160px] flex items-center justify-center text-[11px] text-[var(--text-faint)]">
          Need ≥3 pickleball sessions with HR.
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <div className="flex items-baseline justify-between">
        <Eyebrow>Pickleball HR efficiency · last {points.length}</Eyebrow>
        {trendLabel && (
          <span className="text-[10.5px] tabular-nums" style={{ color: trendColor }}>
            {trendLabel}
          </span>
        )}
      </div>
      <div className="h-[160px]">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={points} margin={{ top: 4, right: 8, left: -22, bottom: 0 }}>
            <CartesianGrid stroke="var(--hairline)" strokeDasharray="2 4" vertical={false} />
            <XAxis
              dataKey="date"
              tick={{ fontSize: 9.5, fill: "var(--text-faint)" }}
              axisLine={false}
              tickLine={false}
              interval={Math.max(0, Math.floor(points.length / 6))}
            />
            <YAxis
              tick={{ fontSize: 9.5, fill: "var(--text-faint)" }}
              axisLine={false}
              tickLine={false}
              width={30}
              domain={["dataMin - 5", "dataMax + 5"]}
              tickFormatter={(v) => `${v}`}
            />
            {/* Z2 ceiling: 70% HRmax */}
            <ReferenceLine
              y={Math.round(hrMax(hrShift) * 0.7)}
              stroke="oklch(0.62 0.16 145 / 0.6)"
              strokeDasharray="3 3"
              label={{ value: "Z2 ceiling", position: "right", fontSize: 9, fill: "oklch(0.62 0.16 145)" }}
            />
            <Tooltip
              contentStyle={{
                background: "var(--card-hover)",
                border: "1px solid var(--hairline-strong)",
                borderRadius: 8,
                fontSize: 11,
              }}
              cursor={{ stroke: "var(--hairline-strong)" }}
              formatter={(_v: number, _name: string, ctx: { payload?: { hr: number; pctHrMax: number; duration: number } }) => {
                const p = ctx.payload;
                if (!p) return [`${_v}`, "HR"];
                return [`${p.hr} bpm · ${p.pctHrMax}% HRmax · ${p.duration} min`, "session"];
              }}
            />
            <Line
              dataKey="hr"
              stroke="var(--chart-line)"
              strokeWidth={1.8}
              dot={{ r: 3, fill: "var(--chart-line)" }}
              activeDot={{ r: 4 }}
              isAnimationActive={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <p className="text-[10px] text-[var(--text-faint)] leading-snug">
        Same sport, lower HR = improving aerobic fitness. Trend uses linear regression
        across the last {points.length} sessions.
      </p>
    </div>
  );
}

function LogForm({ onLogged }: { onLogged: () => void }) {
  const [modality, setModality] = useState("pickleball");
  const [duration, setDuration] = useState("60");
  const [avgHr, setAvgHr] = useState("");
  const [rpe, setRpe] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      await api.cardioLog({
        modality,
        duration_min: parseInt(duration, 10),
        avg_hr: avgHr ? parseInt(avgHr, 10) : null,
        rpe: rpe ? parseFloat(rpe) : null,
      });
      setDuration("60");
      setAvgHr("");
      setRpe("");
      onLogged();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "log failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form
      onSubmit={submit}
      className="flex flex-wrap items-end gap-2 px-3 py-2.5 rounded-[var(--r-md)]"
      style={{ background: "oklch(1 0 0 / 0.025)", border: "1px solid var(--hairline)" }}
    >
      <label className="flex flex-col gap-1">
        <span className="text-[9.5px] text-[var(--text-faint)] uppercase tracking-wider">Sport</span>
        <select
          value={modality}
          onChange={(e) => setModality(e.target.value)}
          className="text-[12px] bg-transparent border border-[var(--hairline)] rounded-sm px-2 py-1 text-[var(--text-primary)]"
        >
          {Object.entries(MODALITY_LABEL).map(([k, v]) => (
            <option key={k} value={k} style={{ background: "var(--card)" }}>
              {v}
            </option>
          ))}
        </select>
      </label>
      <label className="flex flex-col gap-1">
        <span className="text-[9.5px] text-[var(--text-faint)] uppercase tracking-wider">Min</span>
        <input
          type="number"
          inputMode="numeric"
          required
          min={1}
          value={duration}
          onChange={(e) => setDuration(e.target.value)}
          className="w-16 text-[12px] tabular-nums bg-transparent border border-[var(--hairline)] rounded-sm px-2 py-1 text-[var(--text-primary)]"
        />
      </label>
      <label className="flex flex-col gap-1">
        <span className="text-[9.5px] text-[var(--text-faint)] uppercase tracking-wider">Avg HR</span>
        <input
          type="number"
          inputMode="numeric"
          value={avgHr}
          onChange={(e) => setAvgHr(e.target.value)}
          placeholder="—"
          className="w-16 text-[12px] tabular-nums bg-transparent border border-[var(--hairline)] rounded-sm px-2 py-1 text-[var(--text-primary)]"
        />
      </label>
      <label className="flex flex-col gap-1">
        <span className="text-[9.5px] text-[var(--text-faint)] uppercase tracking-wider">RPE</span>
        <input
          type="number"
          inputMode="decimal"
          step="0.5"
          min={1}
          max={10}
          value={rpe}
          onChange={(e) => setRpe(e.target.value)}
          placeholder="—"
          className="w-16 text-[12px] tabular-nums bg-transparent border border-[var(--hairline)] rounded-sm px-2 py-1 text-[var(--text-primary)]"
        />
      </label>
      <button
        type="submit"
        disabled={busy}
        className="text-[11px] font-semibold px-3 py-1.5 rounded-sm transition-colors disabled:opacity-40"
        style={{
          background: "oklch(0.72 0.12 250 / 0.12)",
          border: "1px solid oklch(0.72 0.12 250 / 0.3)",
          color: "var(--chart-line)",
        }}
      >
        {busy ? "Saving…" : "+ Log"}
      </button>
      {err && <span className="text-[11px] text-[var(--negative)]">{err}</span>}
    </form>
  );
}

// Keytel formula (male): kcal/min = (-55.0969 + 0.6309×HR + 0.1988×kg + 0.2017×age) / 4.184
// Rob: 108.8 kg, age 39. On propranolol days, HR is blunted ~20 bpm → multiply by kcal_multiplier (1.25).
function estimateKcal(avgHr: number, durationMin: number, kcalMultiplier = 1.0): number {
  const kcalPerMin = (-55.0969 + 0.6309 * avgHr + 0.1988 * 108.8 + 0.2017 * AGE) / 4.184;
  return Math.round(Math.max(0, kcalPerMin) * durationMin * kcalMultiplier);
}

const HIDDEN_KEY = "shc:cardio:hidden";
function loadHidden(): Set<string> {
  try { return new Set(JSON.parse(localStorage.getItem(HIDDEN_KEY) ?? "[]")); } catch { return new Set(); }
}
function saveHidden(s: Set<string>) {
  localStorage.setItem(HIDDEN_KEY, JSON.stringify([...s]));
}

function TrendKpi({
  label,
  value,
  unit,
  delta,
  deltaUnit,
  higherIsBetter,
}: {
  label: string;
  value: string;
  unit?: string;
  delta: number | null;
  deltaUnit: string;
  higherIsBetter: boolean;
}) {
  const tone =
    delta == null || Math.abs(delta) < 0.5
      ? "neutral"
      : (delta > 0) === higherIsBetter
        ? "positive"
        : "negative";
  const color =
    tone === "positive" ? "var(--positive)" : tone === "negative" ? "var(--negative)" : "var(--text-faint)";
  const arrow = delta == null ? "·" : Math.abs(delta) < 0.5 ? "→" : delta > 0 ? "↑" : "↓";
  return (
    <div>
      <p
        className="text-[9px] uppercase tracking-[0.18em] text-[var(--text-dim)] mb-1"
        style={{ fontFamily: "var(--font-orbitron)" }}
      >
        {label}
      </p>
      <div className="flex items-baseline gap-1.5">
        <span
          className="text-[22px] leading-none font-light tabular-nums text-[var(--text-primary)]"
          style={{ fontFamily: "var(--font-orbitron)" }}
        >
          {value}
        </span>
        {unit && <span className="text-[10px] text-[var(--text-faint)]">{unit}</span>}
      </div>
      <p className="text-[10px] tabular-nums mt-1" style={{ color }}>
        {delta == null
          ? <span className="text-[var(--text-faint)]">no prior data</span>
          : <>{arrow} {Math.abs(delta) < 0.5 ? "flat" : `${delta > 0 ? "+" : ""}${delta.toFixed(deltaUnit === "%" ? 0 : 1)}${deltaUnit}`} <span className="text-[var(--text-faint)]">vs prior 14d</span></>}
      </p>
    </div>
  );
}

function SessionRow({
  s,
  hrShift,
  kcalMultiplier,
  onDelete,
  onHide,
}: {
  s: CardioSession;
  hrShift: number;
  kcalMultiplier: number;
  onDelete: (id: string) => void;
  onHide: (id: string) => void;
}) {
  const m = modalityKey(s.kind);
  const days = Math.floor((Date.now() - new Date(s.date + "T00:00:00").getTime()) / 86_400_000);
  const ago = days === 0 ? "today" : days === 1 ? "yesterday" : `${days}d ago`;
  const shifted = days === 0 && hrShift > 0;
  return (
    <tr className="hover:bg-[var(--card-hover)] transition-colors group">
      <td className="px-3 py-2 text-[var(--text-muted)] tabular-nums whitespace-nowrap">
        <span className="text-[var(--text-faint)] text-[10px] mr-1">{ago}</span>
      </td>
      <td className="px-3 py-2 text-[var(--text-primary)] font-medium">
        <span className="mr-1.5">{MODALITY_ICON[m]}</span>
        {MODALITY_LABEL[m]}
      </td>
      <td className="px-3 py-2 text-right tabular-nums text-[var(--text-muted)]">
        {s.duration_min ?? "—"}
        <span className="text-[var(--text-faint)] text-[10px] ml-0.5">min</span>
      </td>
      <td className="px-3 py-2 text-right tabular-nums">
        {s.avg_hr != null ? (
          <span>
            <span className="text-[var(--text-primary)]">{s.avg_hr}</span>
            <span
              className="text-[9.5px] ml-1"
              style={{ color: shifted ? "var(--neutral)" : "var(--text-faint)" }}
              title={shifted ? `Zone adjusted for propranolol (−${hrShift} bpm HR max)` : undefined}
            >
              {hrZone(s.avg_hr, shifted ? hrShift : 0)}
              {shifted && "*"}
            </span>
          </span>
        ) : (
          <span className="text-[var(--text-faint)]">—</span>
        )}
      </td>
      <td className="px-3 py-2 text-right tabular-nums">
        <span style={{ color: rpeColor(s.rpe) }}>{s.rpe != null ? s.rpe.toFixed(1) : "—"}</span>
      </td>
      <td className="px-3 py-2 text-right tabular-nums text-[var(--text-muted)]">
        {s.kcal != null ? (
          shifted ? (
            <span title={`WHOOP value ×${kcalMultiplier} for propranolol-adjusted exertion`}>
              ~{Math.round(s.kcal * kcalMultiplier)}
              <span className="text-[9px] text-[var(--text-faint)] ml-0.5">β-adj</span>
            </span>
          ) : s.kcal
        ) : s.avg_hr && s.duration_min ? (
          <span title={`Estimated from avg HR (Keytel)${shifted ? ` ×${kcalMultiplier} β-adj` : ""}`}>
            ~{estimateKcal(s.avg_hr, s.duration_min, shifted ? kcalMultiplier : 1.0)}
            <span className="text-[9px] text-[var(--text-faint)] ml-0.5">{shifted ? "β-adj" : "est"}</span>
          </span>
        ) : "—"}
      </td>
      <td className="px-1 py-2 text-right">
        <button
          onClick={() => s.source === "manual" ? onDelete(s.id) : onHide(s.id)}
          className="text-[var(--text-faint)] hover:text-[var(--negative)] opacity-0 group-hover:opacity-100 transition-opacity text-[12px] px-1"
          title={s.source === "manual" ? "Delete" : "Hide (WHOOP false positive)"}
        >
          ✕
        </button>
      </td>
    </tr>
  );
}

export function CardioPanel() {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["cardio-recent"],
    queryFn: () => api.cardioRecent(60),
    refetchInterval: 600_000,
  });
  const stateQ = useQuery({
    queryKey: ["daily-state"],
    queryFn: api.dailyState,
    staleTime: 5 * 60 * 1000,
  });
  const hrShift = stateQ.data?.gates.hr_zone_shift_bpm ?? 0;
  const kcalMultiplier = stateQ.data?.gates.kcal_multiplier ?? 1.0;
  const [hidden, setHidden] = useState<Set<string>>(() => loadHidden());

  function handleHide(id: string) {
    setHidden(prev => {
      const next = new Set(prev).add(id);
      saveHidden(next);
      return next;
    });
  }

  async function refresh() {
    await qc.invalidateQueries({ queryKey: ["cardio-recent"] });
  }

  async function handleDelete(id: string) {
    if (!confirm("Delete this session?")) return;
    await api.cardioDelete(id);
    refresh();
  }

  const sessions = (data?.sessions ?? []).filter(s => !hidden.has(s.id));
  const summary = data?.summary_28d ?? [];
  const total28d = useMemo(
    () => summary.reduce((acc, s) => ({ minutes: acc.minutes + s.minutes, sessions: acc.sessions + s.sessions, kcal: acc.kcal + s.kcal }), { minutes: 0, sessions: 0, kcal: 0 }),
    [summary],
  );

  // ── 4-week trend windows (this fortnight vs prior fortnight) ─────────────
  const [showAll, setShowAll] = useState(false);
  const trends = useMemo(() => {
    const allSessions = data?.sessions ?? [];
    const now = Date.now();
    const oneDay = 86_400_000;
    const recent: typeof allSessions = [];
    const prior: typeof allSessions = [];
    for (const s of allSessions) {
      const t = new Date(s.date + "T00:00:00").getTime();
      const ageDays = (now - t) / oneDay;
      if (ageDays <= 14) recent.push(s);
      else if (ageDays <= 28) prior.push(s);
    }
    const sumMin = (arr: typeof allSessions) => arr.reduce((a, s) => a + (s.duration_min ?? 0), 0);
    const avg = (arr: number[]) => (arr.length ? arr.reduce((a, b) => a + b, 0) / arr.length : null);
    const hrPts = (arr: typeof allSessions) => arr.map((s) => s.avg_hr ?? null).filter((x): x is number => x != null);
    const rpePts = (arr: typeof allSessions) => arr.map((s) => s.rpe ?? null).filter((x): x is number => x != null);
    const kcalSum = (arr: typeof allSessions) => arr.reduce((a, s) => a + (s.kcal ?? 0), 0);

    const minNow = sumMin(recent), minPrev = sumMin(prior);
    const hrNow = avg(hrPts(recent)), hrPrev = avg(hrPts(prior));
    const rpeNow = avg(rpePts(recent)), rpePrev = avg(rpePts(prior));
    const kcalNow = kcalSum(recent), kcalPrev = kcalSum(prior);

    const pctChange = (nowV: number | null, prev: number | null) =>
      nowV != null && prev != null && prev > 0 ? ((nowV - prev) / prev) * 100 : null;

    return {
      minPerWeek: minNow / 2,
      minPctChange: pctChange(minNow, minPrev),
      avgHr: hrNow,
      avgHrChange: hrNow != null && hrPrev != null ? hrNow - hrPrev : null,
      avgRpe: rpeNow,
      avgRpeChange: rpeNow != null && rpePrev != null ? rpeNow - rpePrev : null,
      kcalPerWeek: kcalNow / 2,
      kcalPctChange: pctChange(kcalNow, kcalPrev),
    };
  }, [data]);

  return (
    <div className="shc-card shc-enter p-5 space-y-4">
      <div className="flex items-baseline justify-between">
        <h2 className="shc-section-title">Cardio &amp; Sports</h2>
        <span className="text-[10.5px] text-[var(--text-faint)]">last 60 days · manual + WHOOP</span>
      </div>
      <p className="shc-helptext -mt-2">
        <span className="text-[var(--text-muted)]">How to read this. </span>
        Time in Z2 (60–70% HRmax) builds aerobic capacity. Avg HR drifting <em>down</em> at the same RPE = improving fitness.
        Aim for ≥150 cardio min/wk with ≥45 min in Z2.
      </p>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 pb-4 border-b border-[var(--hairline)]">
        <div>
          <p className="text-[10px] uppercase tracking-wider text-[var(--text-dim)] mb-0.5">28d sessions</p>
          <div className="flex items-baseline gap-1.5">
            <span className="text-[22px] font-light tabular-nums leading-none text-[var(--text-primary)]">{total28d.sessions}</span>
            <span className="text-[11px] text-[var(--text-faint)]">{summary.length} sports</span>
          </div>
        </div>
        <div>
          <p className="text-[10px] uppercase tracking-wider text-[var(--text-dim)] mb-0.5">28d minutes</p>
          <div className="flex items-baseline gap-1.5">
            <span className="text-[22px] font-light tabular-nums leading-none text-[var(--text-primary)]">{total28d.minutes}</span>
            <span className="text-[11px] text-[var(--text-faint)]">{(total28d.minutes / 4).toFixed(0)}/wk</span>
          </div>
        </div>
        <div>
          <p className="text-[10px] uppercase tracking-wider text-[var(--text-dim)] mb-0.5">Top sport</p>
          {summary[0] ? (
            <div className="flex items-baseline gap-1.5">
              <span className="text-[16px] font-medium leading-none text-[var(--text-primary)]">
                {MODALITY_ICON[modalityKey(summary[0].kind)] ?? "•"} {MODALITY_LABEL[modalityKey(summary[0].kind)] ?? summary[0].kind}
              </span>
            </div>
          ) : (
            <span className="text-[11px] text-[var(--text-faint)]">—</span>
          )}
          {summary[0] && (
            <p className="text-[10px] text-[var(--text-faint)] mt-1 tabular-nums">
              {summary[0].minutes} min · {summary[0].sessions} sessions
            </p>
          )}
        </div>
        <div>
          <p className="text-[10px] uppercase tracking-wider text-[var(--text-dim)] mb-0.5">Mix</p>
          <div className="flex h-3 rounded-sm overflow-hidden mt-1.5 bg-[oklch(1_0_0/0.04)]">
            {summary.map((s, i) => {
              const pct = total28d.minutes > 0 ? (s.minutes / total28d.minutes) * 100 : 0;
              if (pct < 1) return null;
              const colors = ["var(--chart-line)", "var(--positive)", "var(--neutral)", "var(--negative)", "oklch(0.55 0.05 230)"];
              return (
                <div
                  key={s.kind}
                  style={{ width: `${pct}%`, background: colors[i % colors.length] }}
                  title={`${MODALITY_LABEL[modalityKey(s.kind)] ?? s.kind} · ${s.minutes} min`}
                />
              );
            })}
          </div>
          <p className="text-[10px] text-[var(--text-faint)] mt-1 tabular-nums">
            {summary.slice(0, 3).map((s) => MODALITY_LABEL[modalityKey(s.kind)] ?? s.kind).join(" · ")}
          </p>
        </div>
      </div>

      {/* ── Trend KPIs · last 14d vs prior 14d ─────────────────────────── */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 pb-4 border-b border-[var(--hairline)]">
        <TrendKpi
          label="Cardio · min/wk"
          value={trends.minPerWeek > 0 ? Math.round(trends.minPerWeek).toString() : "—"}
          delta={trends.minPctChange}
          deltaUnit="%"
          higherIsBetter
        />
        <TrendKpi
          label="Avg HR"
          value={trends.avgHr != null ? Math.round(trends.avgHr).toString() : "—"}
          unit="bpm"
          delta={trends.avgHrChange}
          deltaUnit=" bpm"
          // Lower avg HR at same effort = improving fitness
          higherIsBetter={false}
        />
        <TrendKpi
          label="Avg RPE"
          value={trends.avgRpe != null ? trends.avgRpe.toFixed(1) : "—"}
          delta={trends.avgRpeChange}
          deltaUnit=""
          higherIsBetter={false}
        />
        <TrendKpi
          label="kcal / wk"
          value={trends.kcalPerWeek > 0 ? Math.round(trends.kcalPerWeek).toString() : "—"}
          delta={trends.kcalPctChange}
          deltaUnit="%"
          higherIsBetter
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 pb-4 border-b border-[var(--hairline)]">
        <WeeklyZoneVolume sessions={data?.sessions ?? []} hrShift={hrShift} />
        <PickleballEfficiency sessions={data?.sessions ?? []} hrShift={hrShift} />
      </div>

      <LogForm onLogged={refresh} />

      <div className="rounded-[var(--r-md)] overflow-hidden" style={{ border: "1px solid var(--hairline)" }}>
        <table className="w-full text-[12px]">
          <thead>
            <tr className="text-[10px] text-[var(--text-faint)] uppercase tracking-wider" style={{ borderBottom: "1px solid var(--hairline)" }}>
              <th className="px-3 py-2 text-left font-normal w-24">Date</th>
              <th className="px-3 py-2 text-left font-normal">Sport</th>
              <th className="px-3 py-2 text-right font-normal w-16">Time</th>
              <th className="px-3 py-2 text-right font-normal w-20">Avg HR</th>
              <th className="px-3 py-2 text-right font-normal w-12">RPE</th>
              <th className="px-3 py-2 text-right font-normal w-16">kcal</th>
              <th className="w-6" />
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              [...Array(3)].map((_, i) => (
                <tr key={i}>
                  <td colSpan={7} className="px-3 py-2"><div className="h-5 shc-skeleton rounded" /></td>
                </tr>
              ))
            ) : sessions.length === 0 ? (
              <tr>
                <td colSpan={7} className="px-3 py-6 text-center text-[11px] text-[var(--text-faint)]">
                  No sessions yet. Log your first one above — pickleball, walks, biking, anything.
                </td>
              </tr>
            ) : (
              (showAll ? sessions : sessions.slice(0, 8)).map((s) => <SessionRow key={s.id} s={s} hrShift={hrShift} kcalMultiplier={kcalMultiplier} onDelete={handleDelete} onHide={handleHide} />)
            )}
          </tbody>
        </table>
        {sessions.length > 8 && (
          <button
            type="button"
            onClick={() => setShowAll((v) => !v)}
            className="w-full text-center py-2 text-[10.5px] uppercase tracking-wider text-[var(--text-dim)] hover:text-[var(--text-muted)] transition-colors border-t border-[var(--hairline)]"
            style={{ fontFamily: "var(--font-orbitron)", letterSpacing: "0.18em" }}
          >
            {showAll ? `Show recent only` : `View all ${sessions.length} sessions`}
          </button>
        )}
      </div>
      <p className="text-[10px] text-[var(--text-faint)] leading-snug">
        HR zones use Tanaka formula (208 − 0.7×age ≈ {hrMax()} max
        {hrShift > 0 ? `, shifted −${hrShift} bpm today for propranolol` : ""}).
        Z2 (60–70%) builds aerobic base, Z3 (70–80%) is tempo, Z4–5 are threshold/VO2.
        {hrShift > 0 && <> Zones marked * are propranolol-adjusted. kcal ×{kcalMultiplier} to correct for blunted HR.</>}
      </p>
    </div>
  );
}
