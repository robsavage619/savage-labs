"use client";

import { useQuery } from "@tanstack/react-query";

import { api, type HealthMarker, type HealthMarkerStatus } from "@/lib/api";
import { PageHead, useWidth } from "@/components/kit";

const CYAN = "#2fa4bf";
const COPPER = "#ce7951";

const STATUS: Record<HealthMarkerStatus, { label: string; color: string }> = {
  "on target": { label: "On target", color: "var(--positive)" },
  drifting: { label: "Drifting", color: COPPER },
  "out of range": { label: "Out of range", color: "var(--negative)" },
  stale: { label: "Re-test due", color: COPPER },
  "no target set": { label: "No target set", color: "var(--text-faint)" },
  "no data": { label: "No reading", color: "var(--text-faint)" },
};

// Needs-attention first; quiet states last.
const ORDER: HealthMarkerStatus[] = ["out of range", "drifting", "stale", "on target", "no target set", "no data"];

const DAY = 86_400_000;

function fmt(n: number): string {
  if (n !== 0 && Math.abs(n) < 1) return String(Number(n.toPrecision(2)));
  return Math.abs(n) >= 100 ? n.toFixed(0) : n.toFixed(1).replace(/\.0$/, "");
}

/** Date arithmetic on whole days; both sides are plain dates, so no timezone drift. */
export function nextRetest(m: Pick<HealthMarker, "date" | "retest_days">): { on: string; days: number } | null {
  if (!m.date) return null;
  const due = new Date(`${m.date}T00:00:00`).getTime() + m.retest_days * DAY;
  const today = new Date().setHours(0, 0, 0, 0);
  return { on: new Date(due).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }), days: Math.round((due - today) / DAY) };
}

function targetText(m: HealthMarker): string | null {
  const { low, high, direction } = m.target;
  if (low == null && high == null) return null;
  if (direction === "lower_better" && high != null) return `${fmt(high)} ${m.unit} or lower`;
  if (direction === "higher_better" && low != null) return `${fmt(low)} ${m.unit} or higher`;
  return `${low != null ? fmt(low) : "–"} to ${high != null ? fmt(high) : "–"} ${m.unit}`;
}

/** The reading against the edges of its target band, drawn at the measured pixel width. */
function RangeStrip({ m }: { m: HealthMarker }) {
  const [ref, W] = useWidth(240);
  const { low, high } = m.target;
  if (m.value == null || (low == null && high == null)) return <div ref={ref} />;
  const edges = [low, high].filter((v): v is number => v != null);
  const hi = Math.max(m.value, ...edges) * 1.25 || 1;
  const x = (v: number) => Math.round((v / hi) * (W - 8)) + 4;
  const bx0 = low != null ? x(low) : 4;
  const bx1 = high != null ? x(high) : W - 4;
  const inside = (low == null || m.value >= low) && (high == null || m.value <= high);
  return (
    <div ref={ref}>
      <svg width={W} height={22} role="img" aria-label={`${m.label} against its target range`}>
        <rect x={4} y={9} width={W - 8} height={4} rx={2} fill="var(--hairline)" />
        <rect x={bx0} y={7} width={Math.max(2, bx1 - bx0)} height={8} rx={2} fill={CYAN} opacity={0.35} />
        <circle cx={x(m.value)} cy={11} r={5} fill={inside ? CYAN : COPPER} />
      </svg>
    </div>
  );
}

function Trend({ m }: { m: HealthMarker }) {
  const t = m.trend;
  if (!t) return <span className="text-[var(--text-faint)]">No readings to trend</span>;
  if (t.slope_per_30d == null) return <span className="text-[var(--text-faint)]">Trend needs 3 readings ({t.n} so far)</span>;
  const s = t.slope_per_30d;
  const flat = s === 0 || t.note === "no clear trend";
  const improving = m.target.direction === "higher_better" ? s > 0 : m.target.direction === "lower_better" ? s < 0 : null;
  const color = flat || improving == null ? "var(--text-dim)" : improving ? "var(--positive)" : COPPER;
  return (
    <span style={{ color }}>
      {flat ? "→" : s > 0 ? "↑" : "↓"} {s > 0 ? "+" : ""}
      {fmt(s)} {t.unit}
      {t.range_per_30d && (
        <span className="text-[var(--text-faint)]">
          {" "}(90% range {fmt(t.range_per_30d[0])} to {fmt(t.range_per_30d[1])}
          {t.note === "no clear trend" ? ", no clear trend" : ""})
        </span>
      )}
      <span className="text-[var(--text-faint)]"> · {t.n} readings</span>
    </span>
  );
}

function Row({ m }: { m: HealthMarker }) {
  const st = STATUS[m.status];
  const retest = nextRetest(m);
  const target = targetText(m);
  const cited = m.target.source !== "no target set";
  return (
    <li className="k-panel" style={{ padding: "14px 16px", display: "grid", gap: 10 }}>
      <div className="flex items-baseline justify-between gap-3 flex-wrap">
        <h3 className="k-panel-title">{m.label}</h3>
        <span style={{ color: st.color, fontFamily: "var(--font-data)", fontSize: 11, letterSpacing: "0.1em", textTransform: "uppercase" }}>{st.label}</span>
      </div>
      {m.value == null ? (
        <p style={{ color: "var(--text-dim)", fontSize: 13 }}>
          No reading yet. Nothing is stored for this marker, so there is no value, trend or re-test date to show.
        </p>
      ) : (
        <div className="flex items-baseline gap-2">
          <span style={{ fontFamily: "var(--font-data)", fontSize: 28 }}>{fmt(m.value)}</span>
          <span style={{ color: "var(--text-dim)", fontSize: 13 }}>{m.unit}</span>
          <span style={{ color: "var(--text-faint)", fontSize: 12 }}>
            on {m.date}
            {m.age_days != null ? ` (${m.age_days}d ago)` : ""}
          </span>
        </div>
      )}
      <RangeStrip m={m} />
      <dl className="grid gap-1" style={{ fontSize: 13, gridTemplateColumns: "auto 1fr", columnGap: 12 }}>
        <dt style={{ color: "var(--text-faint)" }}>Target</dt>
        <dd>
          {target ? (
            <>
              {target} <span style={{ color: "var(--text-faint)" }}>· source: {cited ? m.target.source : "none"}</span>
            </>
          ) : (
            <span style={{ color: "var(--text-dim)" }}>No target set. The cited notes give no number for this marker, and none is invented.</span>
          )}
        </dd>
        <dt style={{ color: "var(--text-faint)" }}>Trend</dt>
        <dd>
          <Trend m={m} />
        </dd>
        <dt style={{ color: "var(--text-faint)" }}>Re-test</dt>
        <dd>
          {retest ? (
            retest.days < 0 ? (
              <span style={{ color: COPPER }}>
                Was due {retest.on} ({-retest.days}d overdue)
              </span>
            ) : (
              <>
                {retest.on} <span style={{ color: "var(--text-faint)" }}>· in {retest.days}d, every {m.retest_days}d</span>
              </>
            )
          ) : (
            <span style={{ color: "var(--text-dim)" }}>Every {m.retest_days}d once a first reading exists</span>
          )}
        </dd>
      </dl>
    </li>
  );
}

export function HealthspanBoard() {
  const q = useQuery({ queryKey: ["healthspan"], queryFn: api.healthspan, staleTime: 60_000 });
  const rows = [...(q.data ?? [])].sort((a, b) => ORDER.indexOf(a.status) - ORDER.indexOf(b.status) || a.label.localeCompare(b.label));
  const due = rows.filter((r) => ["stale", "drifting", "out of range"].includes(r.status)).length;
  return (
    <div id="markers">
      <PageHead
        eyebrow="Healthspan"
        question="What needs re-testing, and what is drifting?"
        lede={q.data ? `${rows.length} markers, ${due} need attention.` : undefined}
      />
      <p
        role="note"
        style={{ border: "1px solid var(--hairline)", borderRadius: 10, padding: "10px 14px", margin: "0 0 16px", fontSize: 13, color: "var(--text-dim)" }}
      >
        Not medical advice. Targets here are published reference ranges from the cited notes, not targets set for you. Your clinician sets
        yours and decides what to do about any reading.
      </p>
      {q.isError && (
        <p role="alert" style={{ color: "var(--negative)", fontSize: 14 }}>
          Couldn&apos;t load markers: {(q.error as Error).message}.{" "}
          <button type="button" className="btn" onClick={() => q.refetch()}>
            Retry
          </button>
        </p>
      )}
      {q.isLoading && <p style={{ color: "var(--text-dim)" }}>Loading markers…</p>}
      {q.data && rows.length === 0 && <p style={{ color: "var(--text-dim)" }}>No markers are registered yet.</p>}
      <ul className="grid gap-4" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(min(100%, 340px), 1fr))" }}>
        {rows.map((m) => (
          <Row key={m.marker} m={m} />
        ))}
      </ul>
    </div>
  );
}
