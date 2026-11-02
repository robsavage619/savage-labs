"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, type TapeField } from "@/lib/api";
import { Eyebrow } from "@/components/ui/metric";

const FIELDS: { key: TapeField; label: string }[] = [
  { key: "waist_in", label: "Waist" },
  { key: "arm_in", label: "Arm, flexed" },
  { key: "thigh_in", label: "Mid-thigh" },
  { key: "chest_in", label: "Chest" },
];

/** Tape every four weeks: the direct check on whether muscle is growing. */
export function TapeCard() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["body-tape"], queryFn: api.tape });
  const [values, setValues] = useState<Partial<Record<TapeField, string>>>({});
  const save = useMutation({
    mutationFn: () =>
      api.saveTape(
        Object.fromEntries(
          Object.entries(values)
            .filter(([, v]) => v)
            .map(([k, v]) => [k, Number(v)]),
        ),
      ),
    onSuccess: () => {
      setValues({});
      qc.invalidateQueries({ queryKey: ["body-tape"] });
    },
  });

  return (
    <div className="shc-card shc-enter p-6">
      <Eyebrow>Tape measure · every 4 weeks</Eyebrow>
      <div className="mt-3 grid grid-cols-2 sm:grid-cols-4 gap-3">
        {FIELDS.map(({ key, label }) => {
          const last = data?.[key];
          return (
            <label key={key} className="text-[12px] text-[var(--text-muted)]">
              {label} (in)
              <input
                type="number"
                step="0.1"
                inputMode="decimal"
                value={values[key] ?? ""}
                onChange={(e) => setValues((v) => ({ ...v, [key]: e.target.value }))}
                className="mt-1 block w-full rounded border border-[var(--hairline-strong)] bg-transparent px-2 py-1.5 text-[14px] text-[var(--text-primary)]"
              />
              <span className="mt-1 block text-[11px]">
                {last ? `Last ${last.inches} on ${last.date}` : "No reading yet"}
              </span>
            </label>
          );
        })}
      </div>
      <div className="mt-3 flex items-center gap-3">
        <button
          type="button"
          onClick={() => save.mutate()}
          disabled={save.isPending || !Object.values(values).some(Boolean)}
          className="btn"
        >
          Save
        </button>
        {save.isError && (
          <span className="text-[12px] text-[var(--negative)]">
            Not saved. Check that the numbers are realistic.
          </span>
        )}
        {save.isSuccess && <span className="text-[12px] text-[var(--text-muted)]">Saved.</span>}
      </div>
    </div>
  );
}
