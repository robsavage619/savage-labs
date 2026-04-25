"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type CheckinPayload } from "@/lib/api";
import { Eyebrow } from "@/components/ui/metric";

/**
 * Daily check-in card — drives the deterministic auto-regulation gates.
 *
 * Replaces the dead "Goals" card. The four highest-leverage inputs:
 *   propranolol_taken (β-blocker correction), body_weight_kg, soreness_overall,
 *   sleep_quality. Plus illness/travel toggles for explicit overrides.
 *
 * Updates land in /api/checkin and immediately reshape today's
 * DailyState (readiness composite + gates).
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
      t.body_weight_kg != null ? (t.body_weight_kg * 2.20462).toFixed(1) : "",
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
    <div className="shc-card shc-enter p-4 space-y-3">
      <div className="flex items-baseline justify-between">
        <Eyebrow>Today's check-in</Eyebrow>
        {submit.isPending ? (
          <span className="text-[10px] text-[var(--text-faint)]">saving…</span>
        ) : submit.isSuccess ? (
          <span className="text-[10px] text-[var(--positive)]">saved</span>
        ) : null}
      </div>

      {/* Propranolol — most important input for β-blocker corrections */}
      <Row label="Propranolol today">
        <Toggle
          options={[
            { v: true, label: "Yes" },
            { v: false, label: "No" },
          ]}
          value={propranolol}
          onChange={(v) => {
            setPropranolol(v);
            send({ propranolol_taken: v });
          }}
        />
      </Row>

      <Row label="Weight (lbs)">
        <input
          type="number"
          step="0.1"
          inputMode="decimal"
          className="bg-[var(--surface-1)] border border-[var(--hairline)] rounded-sm px-2 py-1 w-[80px] text-[12px] tabular-nums text-right"
          value={weightLbs}
          onChange={(e) => setWeightLbs(e.target.value)}
          onBlur={commitWeight}
          onKeyDown={(e) => e.key === "Enter" && commitWeight()}
        />
      </Row>

      <Row label="Soreness 1–10">
        <Stepper value={soreness} onChange={(v) => { setSoreness(v); send({ soreness_overall: v }); }} />
      </Row>

      <Row label="Sleep quality 1–10">
        <Stepper value={sleepQ} onChange={(v) => { setSleepQ(v); send({ sleep_quality_1_10: v }); }} />
      </Row>

      <div className="flex items-center gap-3 pt-1">
        <Toggle
          options={[{ v: true, label: "Sick" }]}
          value={illness ? true : null}
          onChange={(v) => { setIllness(!!v); send({ illness_flag: !!v }); }}
          tone="warn"
        />
        <Toggle
          options={[{ v: true, label: "Traveling" }]}
          value={travel ? true : null}
          onChange={(v) => { setTravel(!!v); send({ travel_flag: !!v }); }}
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

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="text-[11.5px] text-[var(--text-muted)]">{label}</span>
      {children}
    </div>
  );
}

function Toggle<T>({
  options,
  value,
  onChange,
  tone,
}: {
  options: { v: T; label: string }[];
  value: T | null;
  onChange: (v: T | null) => void;
  tone?: "warn";
}) {
  return (
    <div className="flex gap-1">
      {options.map((o) => {
        const active = value === o.v;
        const accent =
          tone === "warn"
            ? "var(--negative)"
            : "var(--text-primary)";
        return (
          <button
            key={String(o.v)}
            type="button"
            onClick={() => onChange(active ? null : o.v)}
            className="px-2 py-1 text-[11px] rounded-sm border tabular-nums transition-colors"
            style={{
              background: active ? accent : "transparent",
              color: active ? "var(--surface-0)" : "var(--text-muted)",
              borderColor: active ? accent : "var(--hairline)",
            }}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

function Stepper({
  value,
  onChange,
}: {
  value: number | null;
  onChange: (v: number | null) => void;
}) {
  return (
    <div className="flex gap-0.5">
      {[1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map((n) => {
        const active = value === n;
        return (
          <button
            key={n}
            type="button"
            onClick={() => onChange(active ? null : n)}
            className="w-[18px] h-[18px] text-[10px] rounded-sm border tabular-nums transition-colors"
            style={{
              background: active ? "var(--text-primary)" : "transparent",
              color: active ? "var(--surface-0)" : "var(--text-muted)",
              borderColor: active ? "var(--text-primary)" : "var(--hairline)",
            }}
          >
            {n}
          </button>
        );
      })}
    </div>
  );
}
