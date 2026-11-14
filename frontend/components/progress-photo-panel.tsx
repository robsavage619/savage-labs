"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api, type ProgressComparison } from "@/lib/api";
import { localDate } from "@/lib/date";
import { Eyebrow } from "@/components/ui/metric";
import { Markdown } from "@/components/ui/markdown";

const FLAG_LABEL: Record<string, string> = {
  incomplete_frame: "Frame your torso — shoulders through hips must be in shot",
  low_pose_confidence: "Pose unclear — stand fully facing the camera",
  scale_drift: "Camera distance changed — match your baseline spot",
  uneven_lighting: "Uneven lighting — light both sides evenly",
};

const METRIC_LABEL: Record<string, string> = {
  waist_to_shoulder: "Waist : shoulder",
  waist_to_hip: "Waist : hip",
};

const today = () => localDate();

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
  preview: string;
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
  const cameraRef = useRef<HTMLInputElement>(null);

  // Preview URLs hold the file in memory until revoked.
  const previews = useRef(new Set<string>());
  useEffect(() => {
    const urls = previews.current;
    return () => urls.forEach((u) => URL.revokeObjectURL(u));
  }, []);

  const addFiles = (files: FileList | null | undefined) => {
    if (!files) return;
    const picked = Array.from(files).filter((f) => f.type.startsWith("image/"));
    if (!picked.length) return;
    // The first photo queued dates the session: the day it was taken, not the day it is uploaded.
    if (queue.length === 0) setPhotoDate(localDate(new Date(picked[0].lastModified)));
    const items = picked.map((f) => {
      const preview = URL.createObjectURL(f);
      previews.current.add(preview);
      return {
        id: crypto.randomUUID(),
        file: f,
        preview,
        angle: inferAngle(f.name),
        status: "pending" as QueueStatus,
        message: "",
      };
    });
    setQueue((q) => [...q, ...items]);
  };

  const patch = (id: string, p: Partial<QueueItem>) =>
    setQueue((q) => q.map((it) => (it.id === id ? { ...it, ...p } : it)));

  const remove = (item: QueueItem) => {
    URL.revokeObjectURL(item.preview);
    previews.current.delete(item.preview);
    setQueue((q) => q.filter((x) => x.id !== item.id));
  };

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
              ? `Measured. ${note}`
              : "Measured"
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
          onChange={(e) => {
            addFiles(e.target.files);
            e.target.value = ""; // so picking the same file again still fires
          }}
        />
      </div>

      {queue.length > 0 && (
        <ul className="space-y-1.5">
          {queue.map((it) => (
            <li key={it.id} className="flex items-center gap-2 text-[11px] font-mono">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={it.preview}
                alt=""
                className="h-14 w-[42px] shrink-0 rounded object-cover"
                style={{ background: "var(--card-hover)" }}
                // Chrome can't decode HEIC; the server can, so only the thumbnail is lost.
                onError={(e) => (e.currentTarget.style.visibility = "hidden")}
              />
              <div className="min-w-0 flex-1">
                <p className="truncate text-[var(--text-muted)]">{it.file.name}</p>
                <p className="leading-snug" style={{ color: STATUS_COLOR[it.status] }}>
                  {it.status === "uploading" ? "Measuring…" : it.message || "Ready"}
                </p>
              </div>
              <select
                value={it.angle}
                disabled={busy || it.status === "ok"}
                onChange={(e) => patch(it.id, { angle: e.target.value })}
                aria-label={`Angle for ${it.file.name}`}
                className="bg-[var(--card-hover)] border rounded px-1 py-0.5 disabled:opacity-50"
                style={{ borderColor: "var(--hairline-strong)" }}
              >
                <option value="front">front</option>
                <option value="side">side</option>
              </select>
              <button
                disabled={busy}
                onClick={() => remove(it)}
                className="text-[var(--text-faint)] disabled:opacity-30 px-1"
                aria-label={`Remove ${it.file.name}`}
              >
                ✕
              </button>
            </li>
          ))}
        </ul>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <button
          disabled={busy}
          onClick={() => cameraRef.current?.click()}
          className="border rounded px-3 py-1 text-[11px] font-mono disabled:opacity-40"
          style={{ borderColor: "var(--hairline-strong)" }}
        >
          Take photo
        </button>
        {/* Kept outside the drop zone, whose click handler would open the library picker too.
            `capture` opens the phone's rear camera; desktops fall back to a file picker. */}
        <input
          ref={cameraRef}
          type="file"
          accept="image/*"
          capture="environment"
          className="hidden"
          onChange={(e) => {
            addFiles(e.target.files);
            e.target.value = "";
          }}
        />
        <input
          type="date"
          value={photoDate}
          onChange={(e) => setPhotoDate(e.target.value)}
          aria-label="Date the photos were taken"
          className="bg-[var(--card-hover)] border rounded px-2 py-1 text-[11px] font-mono"
          style={{ borderColor: "var(--hairline-strong)" }}
        />
        <button
          disabled={pending.length === 0 || busy}
          onClick={uploadAll}
          className="border rounded px-3 py-1 text-[11px] font-mono disabled:opacity-40"
          style={{ borderColor: "var(--hairline-strong)" }}
        >
          {busy ? "Measuring…" : `Upload ${pending.length || ""}`.trim()}
        </button>
      </div>
    </div>
  );
}

function SessionGallery() {
  const { data = [] } = useQuery({
    queryKey: ["progress-photos", "all"],
    queryFn: () => api.progressPhotos(),
  });
  const sessions = useMemo(() => {
    const byDate = new Map<string, typeof data>();
    for (const p of data) byDate.set(p.photo_date, [...(byDate.get(p.photo_date) ?? []), p]);
    return [...byDate.entries()].sort(([a], [b]) => b.localeCompare(a));
  }, [data]);

  if (sessions.length === 0) return null;
  return (
    <div className="space-y-2">
      <Eyebrow>Sessions · newest first</Eyebrow>
      <ul className="flex gap-3 overflow-x-auto pb-1">
        {sessions.map(([date, photos]) => (
          <li key={date} className="shrink-0 space-y-1">
            <div className="flex gap-1">
              {["front", "side"].flatMap((angle) => {
                const p = photos.find((x) => x.angle === angle);
                if (!p) return [];
                return (
                  <a
                    key={angle}
                    href={api.progressPhotoUrl(angle, date, 1600)}
                    target="_blank"
                    rel="noreferrer"
                    className="relative block"
                    title={`${date} ${angle}: open full size`}
                  >
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img
                      src={api.progressPhotoUrl(angle, date, 240)}
                      alt={`${angle} photo, ${date}`}
                      className="h-[128px] w-24 rounded border object-cover"
                      style={{ borderColor: p.quality_pass ? "var(--hairline-strong)" : "var(--negative)" }}
                    />
                    <span
                      className="absolute bottom-1 left-1 rounded px-1 text-[9px] font-mono"
                      style={{ background: "oklch(0 0 0 / 0.6)", color: p.quality_pass ? "var(--text-muted)" : "var(--negative)" }}
                    >
                      {p.quality_pass ? angle : `${angle} · not measured`}
                    </span>
                  </a>
                );
              })}
            </div>
            <p className="text-[10px] font-mono text-[var(--text-faint)]">{date}</p>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Two registered photos under one draggable divider. The range input carries drag and keyboard. */
function CompareSlider({ before, after }: { before: string; after: string }) {
  const [pos, setPos] = useState(50);
  return (
    <div
      className="relative mx-auto w-full max-w-[360px] select-none overflow-hidden rounded border"
      style={{ borderColor: "var(--hairline-strong)" }}
    >
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={api.progressPhotoUrl("front", before, 720)} alt={`Front photo, ${before}`} className="block w-full" />
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={api.progressPhotoUrl("front", after, 720, before)}
        alt={`Front photo, ${after}, aligned to ${before}`}
        className="absolute inset-0 h-full w-full"
        style={{ clipPath: `inset(0 0 0 ${pos}%)` }}
      />
      <div className="pointer-events-none absolute inset-y-0 w-px" style={{ left: `${pos}%`, background: "var(--sl-accent)" }} />
      {[
        { label: before, side: "left-1" },
        { label: after, side: "right-1" },
      ].map((t) => (
        <span
          key={t.label}
          className={`pointer-events-none absolute top-1 ${t.side} rounded px-1 text-[9px] font-mono text-[var(--text-muted)]`}
          style={{ background: "oklch(0 0 0 / 0.6)" }}
        >
          {t.label}
        </span>
      ))}
      <input
        type="range"
        min={0}
        max={100}
        value={pos}
        onChange={(e) => setPos(Number(e.target.value))}
        aria-label={`Slide between ${before} and ${after}`}
        className="absolute inset-0 h-full w-full cursor-ew-resize opacity-0"
      />
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

  // One session is not a trend. Two lone dots on a 140px time axis read as a
  // broken chart; the same two numbers against the 1.0 taper line read as a
  // starting point, which is what they are.
  if (series.length === 1) {
    const only = series[0];
    const rows: { label: string; value: number; color: string; note: string }[] = [
      {
        label: "waist : shoulder",
        value: only.waist_to_shoulder,
        color: "var(--sl-accent)",
        note: only.waist_to_shoulder >= 1 ? "no taper — waist is the widest line" : "trunk tapers",
      },
      {
        label: "waist : hip",
        value: only.waist_to_hip,
        color: "var(--text-muted)",
        note: only.waist_to_hip >= 1 ? "waist at or past the hip line" : "waist inside the hip line",
      },
    ];
    return (
      <div className="space-y-3 py-1">
        {rows.map((r) => {
          // Fixed 0.80–1.20 scale so the two readings are comparable to each
          // other and to the same picture next month.
          const pct = Math.max(2, Math.min(98, ((r.value - 0.8) / 0.4) * 100));
          return (
            <div key={r.label}>
              <div className="flex items-baseline justify-between gap-2">
                <span className="text-[11px] text-[var(--text-muted)]">{r.label}</span>
                <span className="text-[12px] font-mono tabular-nums" style={{ color: r.color }}>
                  {r.value.toFixed(2)}
                </span>
              </div>
              <div
                className="relative h-[6px] rounded-full mt-1.5"
                style={{ background: "var(--hairline)" }}
              >
                <div
                  className="absolute inset-y-0 left-1/2 w-px"
                  style={{ background: "var(--hairline-strong)" }}
                />
                <div
                  className="absolute rounded-full"
                  style={{
                    left: `${pct}%`,
                    top: -2,
                    bottom: -2,
                    width: 2.5,
                    marginLeft: -1.25,
                    background: r.color,
                  }}
                />
              </div>
              <p className="text-[10px] text-[var(--text-faint)] mt-1">{r.note}</p>
            </div>
          );
        })}
        <p className="text-[10px] text-[var(--text-faint)] pt-1">
          One session on record ({only.label}) — the midline is 1.00, where the two widths are
          equal. A second passing photo turns this into a trend.
        </p>
      </div>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={140}>
      <LineChart data={series} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
        <XAxis dataKey="label" tick={{ fontSize: 9.5, fill: "var(--text-faint)" }} tickLine={false} axisLine={false} />
        <YAxis tick={{ fontSize: 9.5, fill: "var(--text-faint)" }} tickLine={false} axisLine={false} domain={["auto", "auto"]} />
        <Tooltip
          contentStyle={{ background: "var(--card-hover)", border: "1px solid var(--hairline-strong)", fontSize: 11 }}
        />
        {/* Faint raw points; bold lines are the rolling median (the real signal). */}
        <Line type="monotone" dataKey="waist_to_shoulder" stroke="var(--sl-accent)" strokeOpacity={0.25} dot={{ r: 1.5 }} strokeWidth={0.8} isAnimationActive={false} />
        <Line type="monotone" dataKey="waist_to_hip" stroke="var(--text-muted)" strokeOpacity={0.25} dot={{ r: 1.5 }} strokeWidth={0.8} isAnimationActive={false} />
        <Line type="monotone" dataKey="w2s_med" name="waist:shoulder (median)" stroke="var(--sl-accent)" dot={false} strokeWidth={1.8} isAnimationActive={false} />
        <Line type="monotone" dataKey="w2h_med" name="waist:hip (median)" stroke="var(--text-muted)" dot={false} strokeWidth={1.5} isAnimationActive={false} />
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
  const [picked, setPicked] = useState<{ before?: string; after?: string }>({});
  // Until chosen otherwise: first session against the latest.
  const before = picked.before ?? dates[0] ?? "";
  const after = picked.after ?? dates.at(-1) ?? "";
  const ready = Boolean(before && after && before !== after);

  const compare = useQuery<ProgressComparison>({
    queryKey: ["progress-compare", before, after],
    queryFn: () => api.progressPhotoCompare("front", before, after),
    enabled: ready,
  });

  if (dates.length < 2)
    return (
      <p className="text-[11px] text-[var(--text-faint)]">
        Before/after needs two measured front photos. {dates.length === 1 ? "One on record so far." : ""}
      </p>
    );

  const selectClass = "bg-[var(--card-hover)] border rounded px-2 py-1";
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2 text-[11px] font-mono">
        <span className="text-[var(--text-faint)]">Compare</span>
        <select aria-label="Before date" value={before} onChange={(e) => setPicked((p) => ({ ...p, before: e.target.value }))} className={selectClass} style={{ borderColor: "var(--hairline-strong)" }}>
          {dates.map((d) => <option key={d} value={d}>{d}</option>)}
        </select>
        <span className="text-[var(--text-faint)]">→</span>
        <select aria-label="After date" value={after} onChange={(e) => setPicked((p) => ({ ...p, after: e.target.value }))} className={selectClass} style={{ borderColor: "var(--hairline-strong)" }}>
          {dates.map((d) => <option key={d} value={d}>{d}</option>)}
        </select>
      </div>

      {ready && <CompareSlider before={before} after={after} />}

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
            <Markdown text={c.shape_change_md} />
          </div>
          {c.visible_detail_md && (
            <div>
              <span className="text-[9.5px] font-mono uppercase tracking-wide text-[var(--text-faint)]">
                Visible detail · lighting-dependent
              </span>
              <Markdown text={c.visible_detail_md} />
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
      <SessionGallery />
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
