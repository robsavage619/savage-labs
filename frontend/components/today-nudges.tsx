"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";

const REGIONS: [string, string][] = [
  ["knee", "Knee"],
  ["hip", "Hip"],
  ["lower_back", "Lower back"],
  ["shoulder", "Shoulder"],
  ["elbow", "Elbow"],
  ["wrist", "Wrist"],
  ["neck", "Neck"],
  ["ankle", "Ankle"],
];
const LEVEL = ["", "twinge", "limited a lift", "stopped a lift"];
const TONE = ["", "clear", "soft", "hard"];

const WHERE: Record<string, string> = { scale: "/body#composition", tape: "/body#composition", photos: "/body#physique" };

/** What the Feb 1 growth review still needs. Stays up until every item is current. */
export function MeasurementsDue() {
  const { data } = useQuery({ queryKey: ["measurements-due"], queryFn: api.measurementsDue });
  const due = data?.items.filter((i) => i.due) ?? [];
  if (!data || !due.length || data.days_to_review < 0) return null;
  return (
    <section className="wk-card">
      <p className="wk-label">
        Growth review on {data.review_on}, {data.days_to_review} days out. Without these it can only say &ldquo;unknown&rdquo; again.
      </p>
      <div className="wk-grid">
        {due.map((i) => (
          <a key={i.key} href={WHERE[i.key]} className="wk-cell" data-status="worse">
            <span className="wk-label">{i.label}</span>
            <span className="wk-status">{i.detail}</span>
          </a>
        ))}
      </div>
    </section>
  );
}

/** One tap after a lifting session: any joint pain? Tap a region again to raise its severity. */
export function PainTap() {
  const qc = useQueryClient();
  const due = useQuery({ queryKey: ["pain-due"], queryFn: api.painDue });
  const [pain, setPain] = useState<Record<string, number>>({});
  const save = useMutation({
    mutationFn: (p: Record<string, number>) => api.checkinSubmit({ date: due.data?.date ?? undefined, joint_pain: p }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["pain-due"] }),
  });
  if (!due.data?.due) return null;
  const tap = (k: string) =>
    setPain((p) => {
      const n = ((p[k] ?? 0) + 1) % 4;
      const next = { ...p };
      if (n) next[k] = n;
      else delete next[k];
      return next;
    });
  const any = Object.keys(pain).length > 0;
  return (
    <section className="wk-card">
      <p className="wk-label">Session on {due.data.date}: any joint pain?</p>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6, margin: "8px 0" }}>
        {REGIONS.map(([k, label]) => (
          <button key={k} type="button" className={`td-chip ${TONE[pain[k] ?? 0]}`} onClick={() => tap(k)}>
            {label}
            {pain[k] ? ` · ${LEVEL[pain[k]]}` : ""}
          </button>
        ))}
      </div>
      <button type="button" className="td-chip clear" disabled={save.isPending} onClick={() => save.mutate(pain)}>
        {any ? "Save" : "No pain"}
      </button>
      {save.isError && <p className="wk-rpe">{(save.error as Error).message}</p>}
    </section>
  );
}
