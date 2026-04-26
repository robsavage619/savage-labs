"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type CheckinPayload } from "@/lib/api";
import { Eyebrow } from "@/components/ui/metric";

/**
 * Daily check-in card — drives the deterministic auto-regulation gates.
 *
 * Stacked layout with sliders for 1–10 ratings (replaces 10-button rows),
 * pill toggle for propranolol, and inline state pills for sick/travel.
 */
export function CheckinCard() {
  const qc = useQueryClient();
  const today = useQuery({ queryKey: ["checkin-today"], queryFn: api.checkinToday });

  const [propranolol, setPropranolol] = useState<boolean | null>(null);
  const [weightLbs, setWeightLbs] = useState<string>("");
  const [soreness, setSoreness] = useState<number | null>(null);
  const [sleepQ, setSleepQ] = useState<number | null>(null);
  const [illness, setIllness] = useState<boolean>(false);
  const [travel, setTravel] = useState<boolean>(false);

  useEffect(() => {
    const t = today.data;
    if (!t) return;
    setPropranolol(t.propranolol_taken ?? null);
    setWeightLbs(
      t.body_weight_kg != null ? Math.round(t.body_weight_kg * 2.20462).toString() : "",
    );
    setSoreness(t.soreness_overall ?? null);
    setSleepQ(t.sleep_quality_1_10 ?? null);
    setIllness(!!t.illness_flag);
    setTravel(!!t.travel_flag);
  }, [today.data]);

  const submit = useMutation({
    mutationFn: (body: CheckinPayload) => api.checkinSubmit(body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["checkin-today"] });
      qc.invalidateQueries({ queryKey: ["daily-state"] });
      qc.invalidateQueries({ queryKey: ["readiness-today"] });
    },
  });

  function send(patch: CheckinPayload) {
    submit.mutate(patch);
  }

  function commitWeight() {
    const v = parseFloat(weightLbs);
    if (!Number.isFinite(v) || v <= 0) return;
    send({ body_weight_kg: v / 2.20462 });
  }

  return (
    <div className="shc-card shc-enter p-4 space-y-4">
      <div className="flex items-baseline justify-between">
        <Eyebrow>Today's check-in</Eyebrow>
        {submit.isPending ? (
          <span className="text-[10px] text-[var(--text-faint)]">saving…</span>
        ) : submit.isSuccess ? (
          <span className="text-[10px] text-[var(--positive)]">saved</span>
        ) : null}
      </div>

      {/* Propranolol — pill toggle */}
      <Field label="Propranolol today">
        <PillToggle
          value={propranolol}
          onChange={(v) => {
            setPropranolol(v);
            send({ propranolol_taken: v });
          }}
        />
      </Field>

      {/* Weight — small inline input */}
      <Field label="Weight" suffix="lbs">
        <input
          type="number"
          step="1"
          inputMode="numeric"
          className="bg-transparent border border-[var(--hairline)] rounded-sm px-2 py-1 w-[64px] text-[12.5px] tabular-nums text-right text-[var(--text-primary)] focus:border-[var(--hairline-strong)] focus:outline-none"
          value={weightLbs}
          onChange={(e) => setWeightLbs(e.target.value)}
          onBlur={commitWeight}
          onKeyDown={(e) => e.key === "Enter" && commitWeight()}
        />
      </Field>

      {/* Soreness slider */}
      <Slider
        label="Soreness"
        value={soreness}
        onChange={(v) => { setSoreness(v); send({ soreness_overall: v }); }}
      />

      {/* Sleep quality slider */}
      <Slider
        label="Sleep quality"
        value={sleepQ}
        onChange={(v) => { setSleepQ(v); send({ sleep_quality_1_10: v }); }}
      />

      {/* Sick / Traveling state pills */}
      <div className="flex items-center gap-2 pt-1">
        <StatePill
          label="Sick"
          active={illness}
          tone="warn"
          onClick={() => { const v = !illness; setIllness(v); send({ illness_flag: v }); }}
        />
        <StatePill
          label="Traveling"
          active={travel}
          onClick={() => { const v = !travel; setTravel(v); send({ travel_flag: v }); }}
        />
      </div>

      {submit.isError ? (
        <p className="text-[10.5px] text-[var(--negative)] mt-1">
          {submit.error instanceof Error ? submit.error.message : "save failed"}
        </p>
      ) : null}
    </div>
  );
}

function Field({ label, suffix, children }: { label: string; suffix?: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="text-[11.5px] text-[var(--text-muted)]">
        {label}
        {suffix ? <span className="text-[10px] text-[var(--text-faint)] ml-1">{suffix}</span> : null}
      </span>
      {children}
    </div>
  );
}

function Slider({
  label,
  value,
  onChange,
}: {
  label: string;
  value: number | null;
  onChange: (v: number) => void;
}) {
  const display = value ?? 0;
  const pct = value != null ? ((value - 1) / 9) * 100 : 0;
  // Color shifts: low = soft green (good for soreness=low / quality=high is opposite, but visually we just want a clear scale)
  return (
    <div className="space-y-1.5">
      <div className="flex items-baseline justify-between">
        <span className="text-[11.5px] text-[var(--text-muted)]">{label}</span>
        <span className="text-[12.5px] tabular-nums font-medium text-[var(--text-primary)]">
          {value != null ? value : "—"}
          <span className="text-[9.5px] text-[var(--text-faint)] ml-0.5">/10</span>
        </span>
      </div>
      <div className="relative h-[18px] flex items-center">
        {/* track */}
        <div className="absolute inset-x-0 h-[3px] rounded-full bg-[var(--hairline-strong)]" />
        {/* fill */}
        {value != null && (
          <div
            className="absolute h-[3px] rounded-full bg-[var(--text-primary)]"
            style={{ width: `${pct}%`, transition: "width 140ms ease" }}
          />
        )}
        <input
          type="range"
          min={1}
          max={10}
          step={1}
          value={display}
          onChange={(e) => onChange(parseInt(e.target.value, 10))}
          className="relative w-full appearance-none bg-transparent cursor-pointer slider-input"
          style={{ height: "18px" }}
        />
      </div>
    </div>
  );
}

function PillToggle({
  value,
  onChange,
}: {
  value: boolean | null;
  onChange: (v: boolean | null) => void;
}) {
  return (
    <div className="inline-flex rounded-full border border-[var(--hairline-strong)] overflow-hidden">
      {[
        { v: true, label: "Yes" },
        { v: false, label: "No" },
      ].map((o) => {
        const active = value === o.v;
        return (
          <button
            key={String(o.v)}
            type="button"
            onClick={() => onChange(active ? null : o.v)}
            className="px-2.5 py-0.5 text-[11px] font-medium transition-colors"
            style={{
              background: active ? "var(--text-primary)" : "transparent",
              color: active ? "var(--bg)" : "var(--text-muted)",
            }}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

function StatePill({
  label,
  active,
  onClick,
  tone,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
  tone?: "warn";
}) {
  const accent = tone === "warn" ? "var(--negative)" : "var(--text-primary)";
  return (
    <button
      type="button"
      onClick={onClick}
      className="px-2.5 py-1 text-[11px] rounded-full border transition-colors"
      style={{
        background: active ? `${accent}` : "transparent",
        color: active ? "var(--bg)" : "var(--text-muted)",
        borderColor: active ? accent : "var(--hairline)",
        opacity: active ? 1 : 0.85,
      }}
    >
      {label}
    </button>
  );
}
