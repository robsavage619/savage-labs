"use client";

import { useQuery } from "@tanstack/react-query";
import { api, type DailyState, type NoiseFloorSignal } from "@/lib/api";
import { useExplorer, type MetricKey } from "@/components/metric-explorer";
import { FillLines } from "@/components/kit";

/**
 * The morning read: four figures that say whether today is different from
 * your normal, and why. Every value is rendered as served by DailyState or
 * /api/signals/noise-floor; nothing here is recomputed.
 */

function useDailyState() {
  return useQuery({ queryKey: ["daily-state"], queryFn: api.dailyState, staleTime: 5 * 60 * 1000 });
}

function Shell({ children, error }: { children: React.ReactNode; error?: unknown }) {
  return <div className="ts-card">{error ? <p className="ts-error">Couldn&apos;t load: {String(error)}</p> : children}</div>;
}

// ── Noise floor ─────────────────────────────────────────────────────────────

const SIGNALS: { key: string; label: string; metric?: MetricKey; unitF?: string }[] = [
  { key: "hrv", label: "HRV", metric: "hrv" },
  { key: "rhr", label: "Resting HR", metric: "rhr" },
  { key: "recovery_score", label: "Recovery", metric: "recovery" },
  { key: "sleep_efficiency", label: "Sleep efficiency", metric: "sleep" },
  { key: "respiratory_rate", label: "Breathing rate" },
  // The route reports skin temp in °C; a difference converts by ×1.8.
  { key: "skin_temp", label: "Skin temp", unitF: "°F" },
];

const UNITS: Record<string, string> = { ms: "ms", bpm: "bpm", "%": "%", "br/min": "br/min", degC: "°C" };

function position(s: NoiseFloorSignal) {
  if (s.delta == null || s.swc == null) return null;
  const z = s.swc === 0 ? (s.delta === 0 ? 0 : Math.sign(s.delta) * 3) : s.delta / s.swc;
  return 50 + (Math.max(-3, Math.min(3, z)) / 3) * 50;
}

export function NoiseFloorCard() {
  const q = useQuery({ queryKey: ["noise-floor"], queryFn: () => api.noiseFloor(), staleTime: 5 * 60 * 1000 });
  const open = useExplorer();
  if (q.isError) return <Shell error={q.error}>{null}</Shell>;
  if (!q.data) return <div className="ts-skeleton" style={{ height: 300 }} />;
  const moved = q.data.moved.length;
  return (
    <Shell>
      <p className="ts-lede">
        {moved === 0 ? "Nothing moved past your normal night-to-night wobble." : `${moved} of ${Object.keys(q.data.signals).length} signals moved past your normal wobble.`}
      </p>
      <div className="nf-list">
        {SIGNALS.map(({ key, label, metric, unitF }) => {
          const s = q.data!.signals[key];
          if (!s) return null;
          const f = unitF ? 1.8 : 1;
          const pos = position(s);
          const moved = s.within_noise === false;
          const unit = unitF ?? UNITS[s.unit] ?? s.unit;
          const body = (
            <>
              <span className="nf-label">{label}</span>
              <span className="nf-track" aria-hidden="true">
                <span className="nf-band" />
                <span className="nf-mid" />
                {pos != null && <span className={`nf-dot${moved ? " moved" : ""}`} style={{ left: `${pos}%` }} />}
              </span>
              <span className="nf-delta">
                {s.delta == null ? "–" : `${s.delta * f > 0 ? "+" : ""}${(s.delta * f).toFixed(1)}`} <small>{unit}</small>
              </span>
              <span className={`nf-chip${moved ? " moved" : ""}`}>
                {s.within_noise == null ? "no data" : moved ? (s.direction === "up" ? "moved ↑" : "moved ↓") : "noise"}
              </span>
            </>
          );
          const title = `${label}: ${s.value?.toFixed(1) ?? "–"} vs baseline ${s.baseline?.toFixed(1) ?? "–"}, band ±${((s.swc ?? 0) * f).toFixed(1)} ${unit}, n=${s.n}`;
          return metric ? (
            <button key={key} className="nf-row" title={title} onClick={() => open(metric)}>
              {body}
            </button>
          ) : (
            <div key={key} className="nf-row" title={title}>
              {body}
            </div>
          );
        })}
        <div className="nf-axis" aria-hidden="true">
          <span>lower</span>
          <span>your normal band</span>
          <span>higher</span>
        </div>
      </div>
    </Shell>
  );
}

// ── Readiness, decomposed ───────────────────────────────────────────────────

const TIER_COLOR = { green: "var(--positive)", yellow: "var(--neutral)", red: "var(--negative)" } as const;

function Ring({ score, color }: { score: number | null; color: string }) {
  const r = 46;
  const c = 2 * Math.PI * r;
  const pct = score == null ? 0 : Math.max(0, Math.min(100, score)) / 100;
  return (
    <svg width={112} height={112} viewBox="0 0 112 112" role="img" aria-label={`Readiness ${score ?? "not available"}`}>
      <circle cx={56} cy={56} r={r} fill="none" stroke="oklch(1 0 0 / 0.07)" strokeWidth={9} />
      <circle
        cx={56}
        cy={56}
        r={r}
        fill="none"
        stroke={color}
        strokeWidth={9}
        strokeLinecap="round"
        strokeDasharray={`${c * pct} ${c}`}
        transform="rotate(-90 56 56)"
        className="ts-ring-fill"
      />
      <text x={56} y={63} textAnchor="middle" className="ts-ring-num">
        {score == null ? "–" : Math.round(score)}
      </text>
    </svg>
  );
}

export function ReadinessBreakdown() {
  const q = useDailyState();
  if (q.isError) return <Shell error={q.error}>{null}</Shell>;
  if (!q.data) return <div className="ts-skeleton" style={{ height: 300 }} />;
  const r = q.data.readiness;
  const parts: { key: keyof DailyState["readiness"]["components"]; label: string }[] = [
    { key: "hrv", label: "HRV" },
    { key: "sleep", label: "Sleep" },
    { key: "rhr", label: "Resting HR" },
    { key: "subj", label: "Check-in" },
  ];
  const weakest = parts.filter((p) => r.components[p.key] != null).sort((a, b) => (r.components[a.key] ?? 0) - (r.components[b.key] ?? 0))[0];
  return (
    <Shell>
      <div className="rd-wrap">
        <Ring score={r.score} color={r.tier ? TIER_COLOR[r.tier] : "var(--text-dim)"} />
        <div className="rd-bars">
          {parts.map((p) => {
            const v = r.components[p.key];
            return (
              <div key={p.key} className="rd-row">
                <span className="rd-label">
                  {p.label} <small>{Math.round(r.weights[p.key] * 100)}%</small>
                </span>
                <span className="rd-track">
                  <span className="rd-fill" style={{ width: `${v ?? 0}%`, background: p.key === weakest?.key ? "var(--neutral)" : "var(--series-1)" }} />
                </span>
                <b className="rd-val">{v == null ? "not logged" : Math.round(v)}</b>
              </div>
            );
          })}
        </div>
      </div>
      {weakest && <p className="ts-foot">Dragging it down most: {weakest.label.toLowerCase()} at {Math.round(r.components[weakest.key] ?? 0)}.</p>}
      <RecoveryMini />
    </Shell>
  );
}

// ── Load ratio, split ───────────────────────────────────────────────────────

const AX_LO = 0.6;
const AX_HI = 1.8;
const ax = (v: number) => ((Math.max(AX_LO, Math.min(AX_HI, v)) - AX_LO) / (AX_HI - AX_LO)) * 100;

export function LoadSplit() {
  const q = useDailyState();
  if (q.isError) return <Shell error={q.error}>{null}</Shell>;
  if (!q.data) return <div className="ts-skeleton" style={{ height: 300 }} />;
  const t = q.data.training_load;
  const rows: [string, number | null | undefined][] = [
    ["All training", t.acwr],
    ["Lifting", t.resistance_acwr],
    ["Conditioning", t.conditioning_acwr],
  ];
  return (
    <Shell>
      <div className="ls-plot">
        {rows.map(([label, v]) => (
          <div key={label} className="ls-row">
            <span className="ls-label">{label}</span>
            <span
              className="ls-track"
              style={{
                background: `linear-gradient(90deg, var(--hairline-strong) 0 ${ax(0.8)}%, var(--positive) ${ax(0.8)}% ${ax(1.3)}%, var(--hairline-strong) ${ax(1.3)}% ${ax(1.5)}%, var(--negative) ${ax(1.5)}% 100%)`,
              }}
            >
              {v != null && <span className={`ls-dot${v >= 1.5 ? " hot" : ""}`} style={{ left: `${ax(v)}%` }} />}
            </span>
            <b className="ls-val">{v == null ? "–" : v.toFixed(2)}</b>
          </div>
        ))}
        <div className="ls-axis" aria-hidden="true">
          <span style={{ left: `${ax(0.8)}%` }}>0.8</span>
          <span style={{ left: `${ax(1.5)}%` }}>1.5 gate</span>
        </div>
      </div>
      <LoadCurveMini />
      <p className="ts-foot">Green is steady building. Past 1.5 the engine starts locking muscles.</p>
    </Shell>
  );
}

/** Working sets per week for eight weeks: how much there has been to recover from. */
function WeeklySetsMini() {
  const q = useQuery({ queryKey: ["training-weekly", 8], queryFn: () => api.trainingWeekly(8), staleTime: 10 * 60 * 1000 });
  const pts = q.data ?? [];
  return (
    <div className="ls-mini">
      <p className="ls-mini-label">Working sets per week, last 8 weeks</p>
      {pts.length > 1 ? (
        <FillLines labels={pts.map((w) => w.week)} series={[{ name: "Sets", color: "var(--series-1)", y: pts.map((w) => w.sets) }]} min={110} />
      ) : (
        <div className="ts-skeleton" style={{ height: 110 }} />
      )}
    </div>
  );
}

/** WHOOP recovery for four weeks, with its green and red cut-offs. */
function RecoveryMini() {
  const q = useQuery({ queryKey: ["recovery-trend", 28], queryFn: () => api.recoveryTrend(28), staleTime: 10 * 60 * 1000 });
  const pts = q.data ?? [];
  return (
    <div className="ls-mini">
      <p className="ls-mini-label">WHOOP recovery, last 4 weeks</p>
      {pts.length > 1 ? (
        <FillLines
          labels={pts.map((p) => p.date)}
          series={[{ name: "Recovery", color: "var(--series-1)", y: pts.map((p) => p.score) }]}
          refs={[
            { y: 67, label: "green 67" },
            { y: 34, label: "red 34" },
          ]}
          min={120}
        />
      ) : (
        <div className="ts-skeleton" style={{ height: 120 }} />
      )}
    </div>
  );
}

/** Six weeks of fitness vs fatigue: the trend the ratio above is a snapshot of. */
function LoadCurveMini() {
  const q = useQuery({ queryKey: ["load-curve", 42], queryFn: () => api.loadCurve(42), staleTime: 10 * 60 * 1000 });
  const pts = q.data?.points ?? [];
  return (
    <div className="ls-mini">
      <p className="ls-mini-label">Fitness vs fatigue, last 6 weeks</p>
      {pts.length > 1 ? (
        <FillLines
          labels={pts.map((p) => p.date)}
          series={[
            { name: "Fitness", color: "var(--series-1)", y: pts.map((p) => p.ctl) },
            { name: "Fatigue", color: "var(--series-2)", y: pts.map((p) => p.atl) },
          ]}
          min={130}
          fmt={(v) => v.toFixed(0)}
        />
      ) : (
        <div className="ts-skeleton" style={{ height: 130 }} />
      )}
    </div>
  );
}

// ── Muscle freshness ────────────────────────────────────────────────────────

export function MuscleFreshness() {
  const q = useDailyState();
  if (q.isError) return <Shell error={q.error}>{null}</Shell>;
  if (!q.data) return <div className="ts-skeleton" style={{ height: 220 }} />;
  const mr = Object.entries(q.data.training_load.muscle_recovery ?? {}).sort((a, b) => (b[1].days_since_dose ?? 0) - (a[1].days_since_dose ?? 0));
  return (
    <Shell>
      {mr.length === 0 ? (
        <p className="ts-lede">No muscle has a dose record yet.</p>
      ) : (
        <div className="mf-grid">
          {mr.map(([m, v]) => {
            const d = v.days_since_dose;
            const f = d == null ? 0 : Math.min(d / 4, 1);
            return (
              <div key={m} className="mf-tile" style={{ ["--f" as string]: f }} title={`${m}: last dose ${v.last_dose_sets ?? "–"} sets at RPE ${v.last_rpe ?? "–"}`}>
                <b>{d == null ? "–" : `${d}d`}</b>
                <span>{m.replace(/_/g, " ")}</span>
              </div>
            );
          })}
        </div>
      )}
      <div className="mf-patterns">
        {(
          [
            ["Legs", q.data.training_load.days_since_legs],
            ["Push", q.data.training_load.days_since_push],
            ["Pull", q.data.training_load.days_since_pull],
            ["Pickleball", q.data.training_load.days_since_pickleball ?? null],
          ] as [string, number | null][]
        ).map(([label, d]) => (
          <div key={label}>
            <span>{label}</span>
            <b>{d == null ? "–" : `${d}d`}</b>
          </div>
        ))}
      </div>
      <p className="ts-foot">Tiles: a dose is {mr[0]?.[1].dose_threshold_sets ?? 4}+ hard sets, greener means more rested. Row: days since any session of that kind.</p>
      <WeeklySetsMini />
    </Shell>
  );
}
