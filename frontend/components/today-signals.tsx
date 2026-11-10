"use client";

import { useQuery } from "@tanstack/react-query";
import { api, type DailyState, type NoiseFloorSignal } from "@/lib/api";
import { Eyebrow } from "@/components/ui/metric";
import { ExploreButton, useExplorer, type MetricKey } from "@/components/metric-explorer";

/**
 * The morning read: four figures that say whether today is different from
 * your normal, and why. Every value is rendered as served by DailyState or
 * /api/signals/noise-floor; nothing here is recomputed.
 */

function useDailyState() {
  return useQuery({ queryKey: ["daily-state"], queryFn: api.dailyState, staleTime: 5 * 60 * 1000 });
}

function Head({ eyebrow, title, metric }: { eyebrow: string; title: string; metric?: MetricKey }) {
  return (
    <div className="ts-head">
      <div>
        <Eyebrow>{eyebrow}</Eyebrow>
        <h3 className="shc-section-title mt-1">{title}</h3>
      </div>
      {metric && <ExploreButton metric={metric} />}
    </div>
  );
}

function Shell({ children, error }: { children: React.ReactNode; error?: unknown }) {
  return (
    <div className="shc-card shc-enter p-6 ts-card">
      {error ? <p className="ts-error">Couldn&apos;t load: {String(error)}</p> : children}
    </div>
  );
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
  if (!q.data) return <div className="shc-card p-6 ts-card ts-skeleton" style={{ height: 300 }} />;
  const moved = q.data.moved.length;
  return (
    <Shell>
      <Head eyebrow={`Overnight · vs your last ${q.data.window_days} days`} title="Did anything actually move?" metric="hrv" />
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
  if (!q.data) return <div className="shc-card p-6 ts-card ts-skeleton" style={{ height: 300 }} />;
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
      <Head eyebrow="Readiness" title="What the score is made of" metric="recovery" />
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
  if (!q.data) return <div className="shc-card p-6 ts-card ts-skeleton" style={{ height: 300 }} />;
  const t = q.data.training_load;
  const rows: [string, number | null | undefined][] = [
    ["All training", t.acwr],
    ["Lifting", t.resistance_acwr],
    ["Conditioning", t.conditioning_acwr],
  ];
  return (
    <Shell>
      <Head eyebrow="Load ratio · last 7 days vs prior 21" title="Building or spiking?" metric="load" />
      <div className="ls-plot">
        <div className="ls-zones" aria-hidden="true">
          <span className="ls-build" style={{ left: `${ax(0.8)}%`, width: `${ax(1.3) - ax(0.8)}%` }} />
          <span className="ls-gate" style={{ left: `${ax(1.5)}%`, right: 0 }} />
        </div>
        {rows.map(([label, v]) => (
          <div key={label} className="ls-row">
            <span className="ls-label">{label}</span>
            <span className="ls-track">{v != null && <span className={`ls-dot${v >= 1.5 ? " hot" : ""}`} style={{ left: `${ax(v)}%` }} />}</span>
            <b className="ls-val">{v == null ? "–" : v.toFixed(2)}</b>
          </div>
        ))}
        <div className="ls-axis" aria-hidden="true">
          <span style={{ left: `${ax(0.8)}%` }}>0.8</span>
          <span style={{ left: `${ax(1.5)}%` }}>1.5 gate</span>
        </div>
      </div>
      <p className="ts-foot">Green band is steady building. Past 1.5 the engine starts locking muscles.</p>
    </Shell>
  );
}

// ── Muscle freshness ────────────────────────────────────────────────────────

export function MuscleFreshness() {
  const q = useDailyState();
  if (q.isError) return <Shell error={q.error}>{null}</Shell>;
  if (!q.data) return <div className="shc-card p-6 ts-card ts-skeleton" style={{ height: 220 }} />;
  const mr = Object.entries(q.data.training_load.muscle_recovery ?? {}).sort((a, b) => (b[1].days_since_dose ?? 0) - (a[1].days_since_dose ?? 0));
  return (
    <Shell>
      <Head eyebrow="Days since a real dose" title="What's fresh" metric="sets" />
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
      <p className="ts-foot">A dose is {mr[0]?.[1].dose_threshold_sets ?? 4}+ hard sets. Greener means more rested.</p>
    </Shell>
  );
}
