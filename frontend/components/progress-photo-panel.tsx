"use client";

import { useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api, type ProgressComparison } from "@/lib/api";
import { Eyebrow } from "@/components/ui/metric";

const FLAG_LABEL: Record<string, string> = {
  incomplete_frame: "Frame your torso — shoulders through hips must be in shot",
  low_pose_confidence: "Pose unclear — stand fully facing the camera",
  scale_drift: "Camera distance changed — match your baseline spot",
  uneven_lighting: "Uneven lighting — light both sides evenly",
};

const METRIC_LABEL: Record<string, string> = {
  waist_to_shoulder: "Waist : shoulder",
  waist_to_hip: "Waist : hip",
  waist_width: "Waist width",
  shoulder_width: "Shoulder width",
  hip_width: "Hip width",
  silhouette_area: "Silhouette area",
};

const today = () => new Date().toISOString().slice(0, 10);

// Rolling median absorbs single-shot noise (pose/lighting) so the trend reflects
// real change, not capture variation. Window of 3 by default.
function rollingMedian(values: number[], window = 3): number[] {
  return values.map((_, i) => {
    const slice = values.slice(Math.max(0, i - window + 1), i + 1).slice().sort((a, b) => a - b);
    const mid = Math.floor(slice.length / 2);
    return slice.length % 2 ? slice[mid] : (slice[mid - 1] + slice[mid]) / 2;
  });
}

type QueueStatus = "pending" | "uploading" | "ok" | "flagged" | "error";

interface QueueItem {
  id: string;
  file: File;
  angle: string;
  status: QueueStatus;
  message: string;
}

const STATUS_COLOR: Record<QueueStatus, string> = {
  pending: "var(--text-faint)",
  uploading: "var(--text-muted)",
  ok: "var(--positive)",
  flagged: "var(--negative)",
  error: "var(--negative)",
};

const inferAngle = (name: string) => (/side/i.test(name) ? "side" : "front");

function UploadRow({ onDone }: { onDone: () => void }) {
  const [photoDate, setPhotoDate] = useState(today());
  const [queue, setQueue] = useState<QueueItem[]>([]);
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const addFiles = (files: FileList | null | undefined) => {
    if (!files) return;
    const items = Array.from(files)
      .filter((f) => f.type.startsWith("image/"))
      .map((f) => ({
        id: crypto.randomUUID(),
        file: f,
        angle: inferAngle(f.name),
        status: "pending" as QueueStatus,
        message: "",
      }));
    if (items.length) setQueue((q) => [...q, ...items]);
  };

  const patch = (id: string, p: Partial<QueueItem>) =>
    setQueue((q) => q.map((it) => (it.id === id ? { ...it, ...p } : it)));

  const pending = queue.filter((it) => it.status === "pending" || it.status === "error");

  async function uploadAll() {
    setBusy(true);
    for (const item of pending) {
      patch(item.id, { status: "uploading", message: "" });
      try {
        const res = await api.progressPhotoUpload(item.file, photoDate, item.angle);
        const note = res.advisories?.map((f) => FLAG_LABEL[f] ?? f).join("; ") ?? "";
        patch(item.id, {
          status: res.quality_pass ? "ok" : "flagged",
          message: res.quality_pass
            ? note
              ? `ok · ${note}`
              : `pose ${res.pose_conf.toFixed(2)}`
            : res.quality_flags.map((f) => FLAG_LABEL[f] ?? f).join("; "),
        });
      } catch (e) {
        patch(item.id, { status: "error", message: (e as Error).message });
      }
    }
    setBusy(false);
    onDone();
  }

  return (
    <div className="space-y-2">
      <div
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          addFiles(e.dataTransfer.files);
        }}
        className="flex flex-col items-center justify-center gap-1 rounded-lg border border-dashed px-4 py-6 text-center cursor-pointer transition-colors"
        style={{
          borderColor: dragging ? "var(--sl-accent)" : "var(--hairline-strong)",
          background: dragging ? "var(--sl-accent-soft)" : "transparent",
        }}
      >
        <span className="text-[11px] font-mono" style={{ color: dragging ? "var(--sl-accent)" : "var(--text-muted)" }}>
          Drag photos here, or click to browse
        </span>
        <span className="text-[9.5px] text-[var(--text-faint)]">
          multiple OK · front &amp; side · frame shoulders-to-hips (feet optional)
        </span>
        <input
          ref={inputRef}
          type="file"
          accept="image/*"
          multiple
          className="hidden"
          onChange={(e) => addFiles(e.target.files)}
        />
      </div>

      {queue.length > 0 && (
        <ul className="space-y-1">
          {queue.map((it) => (
            <li key={it.id} className="flex items-center gap-2 text-[11px] font-mono">
              <span className="flex-1 truncate text-[var(--text-muted)]">{it.file.name}</span>
              <select
                value={it.angle}
                disabled={busy || it.status === "ok"}
                onChange={(e) => patch(it.id, { angle: e.target.value })}
                className="bg-[var(--card-hover)] border rounded px-1 py-0.5 disabled:opacity-50"
                style={{ borderColor: "var(--hairline-strong)" }}
              >
                <option value="front">front</option>
                <option value="side">side</option>
              </select>
              <span className="w-28 truncate text-right" style={{ color: STATUS_COLOR[it.status] }}>
                {it.status === "uploading" ? "analyzing…" : it.message || it.status}
              </span>
              <button
                disabled={busy}
                onClick={() => setQueue((q) => q.filter((x) => x.id !== it.id))}
                className="text-[var(--text-faint)] disabled:opacity-30 px-1"
                aria-label="remove"
              >
                ✕
              </button>
            </li>
          ))}
        </ul>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <input
          type="date"
          value={photoDate}
          onChange={(e) => setPhotoDate(e.target.value)}
          className="bg-[var(--card-hover)] border rounded px-2 py-1 text-[11px] font-mono"
          style={{ borderColor: "var(--hairline-strong)" }}
        />
        <button
          disabled={pending.length === 0 || busy}
          onClick={uploadAll}
          className="border rounded px-3 py-1 text-[11px] font-mono disabled:opacity-40"
          style={{ borderColor: "var(--hairline-strong)" }}
        >
          {busy ? "Analyzing…" : `Upload ${pending.length || ""}`.trim()}
        </button>
      </div>
    </div>
  );
}

function RatioTrend() {
  const { data = [], isLoading } = useQuery({
    queryKey: ["progress-photos", "front"],
    queryFn: () => api.progressPhotos("front"),
    refetchInterval: 3_600_000,
  });

  const series = useMemo(() => {
    const passing = data.filter((p) => p.quality_pass);
    const w2s = rollingMedian(passing.map((p) => p.measurements.waist_to_shoulder));
    const w2h = rollingMedian(passing.map((p) => p.measurements.waist_to_hip));
    return passing.map((p, i) => ({
      label: p.photo_date.slice(5),
      waist_to_shoulder: p.measurements.waist_to_shoulder,
      waist_to_hip: p.measurements.waist_to_hip,
      w2s_med: +w2s[i].toFixed(4),
      w2h_med: +w2h[i].toFixed(4),
    }));
  }, [data]);

  if (isLoading) return <div className="h-[140px] shc-skeleton rounded" />;
  if (series.length === 0)
    return (
      <p className="text-[12px] text-[var(--text-faint)] py-8 text-center">
        No passing front photos yet
      </p>
    );

  return (
    <ResponsiveContainer width="100%" height={140}>
      <LineChart data={series} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
        <XAxis dataKey="label" tick={{ fontSize: 9.5, fill: "var(--text-faint)" }} tickLine={false} axisLine={false} />
        <YAxis tick={{ fontSize: 9.5, fill: "var(--text-faint)" }} tickLine={false} axisLine={false} domain={["auto", "auto"]} />
        <Tooltip
          contentStyle={{ background: "var(--card-hover)", border: "1px solid var(--hairline-strong)", fontSize: 11 }}
        />
        {/* Faint raw points; bold lines are the rolling median (the real signal). */}
        <Line type="monotone" dataKey="waist_to_shoulder" stroke="var(--sl-accent)" strokeOpacity={0.25} dot={{ r: 1.5 }} strokeWidth={0.8} />
        <Line type="monotone" dataKey="waist_to_hip" stroke="var(--text-muted)" strokeOpacity={0.25} dot={{ r: 1.5 }} strokeWidth={0.8} />
        <Line type="monotone" dataKey="w2s_med" name="waist:shoulder (median)" stroke="var(--sl-accent)" dot={false} strokeWidth={1.8} />
        <Line type="monotone" dataKey="w2h_med" name="waist:hip (median)" stroke="var(--text-muted)" dot={false} strokeWidth={1.5} />
      </LineChart>
    </ResponsiveContainer>
  );
}

function ComparePanel() {
  const { data = [] } = useQuery({
    queryKey: ["progress-photos", "front"],
    queryFn: () => api.progressPhotos("front"),
  });
  const dates = data.filter((p) => p.quality_pass).map((p) => p.photo_date);
  const [before, setBefore] = useState("");
  const [after, setAfter] = useState("");

  const compare = useQuery<ProgressComparison>({
    queryKey: ["progress-compare", before, after],
    queryFn: () => api.progressPhotoCompare("front", before, after),
    enabled: Boolean(before && after && before !== after),
  });

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2 text-[11px] font-mono">
        <span className="text-[var(--text-faint)]">Compare</span>
        <select value={before} onChange={(e) => setBefore(e.target.value)} className="bg-[var(--card-hover)] border rounded px-2 py-1" style={{ borderColor: "var(--hairline-strong)" }}>
          <option value="">before…</option>
          {dates.map((d) => <option key={d} value={d}>{d}</option>)}
        </select>
        <span className="text-[var(--text-faint)]">→</span>
        <select value={after} onChange={(e) => setAfter(e.target.value)} className="bg-[var(--card-hover)] border rounded px-2 py-1" style={{ borderColor: "var(--hairline-strong)" }}>
          <option value="">after…</option>
          {dates.map((d) => <option key={d} value={d}>{d}</option>)}
        </select>
      </div>

      {compare.data && (
        <div className="space-y-2">
          {compare.data.conflict && (
            <p className="text-[11px] rounded border px-2 py-1" style={{ color: "var(--negative)", borderColor: "var(--negative)" }}>
              ⚠ {compare.data.conflict}
            </p>
          )}
          {!compare.data.any_detectable && (
            <p className="text-[11px] text-[var(--text-muted)]">
              No change exceeds the ±2% measurement-error floor — indistinguishable from noise.
            </p>
          )}
          <ul className="space-y-1">
            {compare.data.verdicts.map((v) => (
              <li key={v.metric} className="flex items-center justify-between text-[11px] font-mono">
                <span className="text-[var(--text-muted)]">{METRIC_LABEL[v.metric] ?? v.metric}</span>
                {v.detectable ? (
                  <span style={{ color: v.direction === "down" ? "var(--positive)" : "var(--negative)" }}>
                    {v.direction === "down" ? "▼" : "▲"} {v.pct_change}%
                  </span>
                ) : (
                  <span className="text-[var(--text-faint)]">no detectable change</span>
                )}
              </li>
            ))}
          </ul>
          {compare.data.any_detectable && (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={api.progressHeatmapUrl("front", before, after)}
              alt="silhouette change heatmap"
              className="rounded border w-full max-w-[280px] mx-auto"
              style={{ borderColor: "var(--hairline-strong)" }}
            />
          )}
        </div>
      )}
    </div>
  );
}

function CritiquePanel() {
  const { data } = useQuery({
    queryKey: ["progress-critique"],
    queryFn: () => api.progressCritique(),
    refetchInterval: 60_000,
  });
  const [copied, setCopied] = useState(false);

  const copyPrompt = async () => {
    const p = await api.progressCritiquePrompt();
    await navigator.clipboard.writeText(p.prompt);
    setCopied(true);
    setTimeout(() => setCopied(false), 2500);
  };

  const c = data?.critique;
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <Eyebrow>Physique critique · anchored to measured state</Eyebrow>
        <button
          onClick={copyPrompt}
          className="border rounded px-2 py-0.5 text-[10px] font-mono"
          style={{ borderColor: "var(--hairline-strong)" }}
        >
          {copied ? "copied — run in Claude Code" : "copy critique prompt"}
        </button>
      </div>

      {data && (
        <p className="text-[10px]" style={{ color: data.stale ? "var(--negative)" : "var(--text-faint)" }}>
          {data.reason}
        </p>
      )}

      {c ? (
        <div className="space-y-2 text-[11.5px] leading-relaxed">
          <div>
            <span className="text-[9.5px] font-mono uppercase tracking-wide" style={{ color: "var(--sl-accent)" }}>
              Shape &amp; change · verdict: {c.verdict}
            </span>
            <p className="whitespace-pre-wrap text-[var(--text-primary)]">{c.shape_change_md}</p>
          </div>
          {c.visible_detail_md && (
            <div>
              <span className="text-[9.5px] font-mono uppercase tracking-wide text-[var(--text-faint)]">
                Visible detail · lighting-dependent
              </span>
              <p className="whitespace-pre-wrap text-[var(--text-muted)]">{c.visible_detail_md}</p>
            </div>
          )}
        </div>
      ) : (
        <p className="text-[11px] text-[var(--text-faint)]">
          No critique yet. Copy the prompt, run it in Claude Code with your latest front &amp; side
          photos attached, and it posts the critique back here.
        </p>
      )}
    </div>
  );
}

export function ProgressPhotoPanel() {
  const qc = useQueryClient();
  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <Eyebrow>Capture · standardized morning, fasted, ≥24h post-training</Eyebrow>
        <UploadRow onDone={() => qc.invalidateQueries({ queryKey: ["progress-photos"] })} />
      </div>
      <div className="space-y-2">
        <Eyebrow>Waist ratios · front · lower is leaner trunk</Eyebrow>
        <RatioTrend />
      </div>
      <ComparePanel />
      <CritiquePanel />
      <p className="text-[10px] text-[var(--text-faint)] leading-relaxed">
        Measurements are deterministic (pose + silhouette geometry), arms excluded,
        normalized to your shoulder→hip span. Lines are a rolling median so one off shot
        can&apos;t swing the trend; change below the ISAK 2% error floor is reported as no
        change. Photos never leave this machine.
      </p>
    </div>
  );
}
