"use client";

import { useQuery } from "@tanstack/react-query";
import { api, type SubjectProfile } from "@/lib/api";
import { Eyebrow } from "@/components/ui/metric";

function enrolledLabel(profile: SubjectProfile): string {
  if (!profile.enrolled_on) return "—";
  const d = new Date(profile.enrolled_on);
  return d.toLocaleDateString("en-US", { month: "short", year: "numeric" });
}

function PersonalizationMeter({ fitted, total }: { fitted: number; total: number }) {
  const pct = total > 0 ? Math.round((fitted / total) * 100) : 0;
  const color =
    pct >= 60 ? "var(--positive)" : pct >= 30 ? "var(--warn)" : "var(--text-muted)";
  return (
    <div>
      <div className="flex items-baseline justify-between mb-1">
        <span className="text-[10px] uppercase tracking-wider text-[var(--text-dim)]">
          Personalization
        </span>
        <span className="text-[11px] tabular-nums" style={{ color }}>
          {fitted}/{total} params fitted
        </span>
      </div>
      <div className="h-1 rounded-full bg-[var(--hairline)] overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-500"
          style={{ width: `${pct}%`, background: color }}
        />
      </div>
    </div>
  );
}

function AccuracySparkline({
  history,
  current,
}: {
  history: SubjectProfile["engine_accuracy"]["history"];
  current: number | null;
}) {
  const vals = history.map((h) => h.overall).filter((v): v is number => v != null);
  if (vals.length < 2) return null;
  const w = 88;
  const h = 16;
  const min = Math.min(...vals);
  const max = Math.max(...vals);
  const span = max - min || 0.05;
  const step = w / (vals.length - 1);
  const d = vals
    .map(
      (v, i) =>
        `${i === 0 ? "M" : "L"}${(i * step).toFixed(1)},${(h - ((v - min) / span) * h).toFixed(1)}`,
    )
    .join(" ");
  const col =
    current != null
      ? current >= 0.7
        ? "var(--positive)"
        : current >= 0.5
          ? "var(--warn)"
          : "var(--negative)"
      : "var(--text-muted)";
  const last = vals[vals.length - 1];
  return (
    <svg width={w} height={h} className="overflow-visible">
      <path d={d} fill="none" stroke={col} strokeWidth={1.5} strokeLinejoin="round" />
      <circle
        cx={w}
        cy={h - ((last - min) / span) * h}
        r={2}
        fill={col}
      />
    </svg>
  );
}

export function SubjectDossier() {
  const q = useQuery({
    queryKey: ["subject-profile"],
    queryFn: api.subjectProfile,
    refetchInterval: 5 * 60_000,
  });

  const profile = q.data;

  return (
    <div className="shc-card shc-enter p-5">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <div
            className="text-[9px] uppercase tracking-[0.25em] text-[var(--text-faint)] mb-1"
            style={{ fontFamily: "var(--font-orbitron)" }}
          >
            Research Subject
          </div>
          <h2
            className="text-[17px] font-semibold tracking-tight text-[var(--text-primary)] leading-none"
            style={{ fontFamily: "var(--font-orbitron)" }}
          >
            SUBJECT {profile?.subject_id ?? "001"}{" "}
            <span className="text-[var(--text-muted)] font-normal">·</span>{" "}
            <span className="text-[var(--text-dim)] font-normal">{profile?.name ?? "Rob Savage"}</span>
          </h2>
        </div>
        {profile && (
          <div className="flex items-center gap-4 text-right">
            <div>
              <div className="text-[10px] text-[var(--text-faint)] uppercase tracking-wider">
                Enrolled
              </div>
              <div className="text-[12px] text-[var(--text-muted)]">
                {enrolledLabel(profile)}
              </div>
            </div>
            <div>
              <div className="text-[10px] text-[var(--text-faint)] uppercase tracking-wider">
                Days observed
              </div>
              <div
                className="text-[16px] font-medium tabular-nums"
                style={{ color: "var(--text-primary)" }}
              >
                {profile.days_observed?.toLocaleString() ?? "—"}
              </div>
            </div>
          </div>
        )}
      </div>

      {q.isLoading && (
        <div className="mt-4 text-[11px] text-[var(--text-faint)]">Loading profile…</div>
      )}

      {profile && (
        <>
          {/* Personalization meter */}
          <div className="mt-5">
            <PersonalizationMeter
              fitted={profile.personalization.fitted_params}
              total={profile.personalization.total_params}
            />
            <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[10px] text-[var(--text-dim)]">
              <span>
                Landmarks{" "}
                <span className={profile.personalization.families.volume_landmarks.fitted > 0 ? "text-[var(--positive)]" : ""}>
                  {profile.personalization.families.volume_landmarks.fitted}/
                  {profile.personalization.families.volume_landmarks.total}
                </span>
              </span>
              <span>
                ACWR{" "}
                <span style={{ color: profile.personalization.families.acwr_bands ? "var(--positive)" : "var(--text-faint)" }}>
                  {profile.personalization.families.acwr_bands ? "fitted" : "population"}
                </span>
              </span>
              <span>
                Sleep{" "}
                <span style={{ color: profile.personalization.families.sleep_bands ? "var(--positive)" : "var(--text-faint)" }}>
                  {profile.personalization.families.sleep_bands ? "fitted" : "population"}
                </span>
              </span>
              <span>
                Deload{" "}
                <span style={{ color: profile.personalization.families.deload_trigger ? "var(--positive)" : "var(--text-faint)" }}>
                  {profile.personalization.families.deload_trigger ? "fitted" : "population"}
                </span>
              </span>
            </div>
          </div>

          {/* Phenotype chips */}
          {profile.phenotype.length > 0 && (
            <div className="mt-4 flex flex-wrap gap-2">
              {profile.phenotype.map((tag) => (
                <span
                  key={tag}
                  className="text-[10px] px-2 py-0.5 rounded-full border border-[var(--hairline)] text-[var(--text-dim)]"
                >
                  {tag}
                </span>
              ))}
            </div>
          )}

          {/* Bottom stats row */}
          <div className="mt-5 pt-4 border-t border-[var(--hairline)] grid grid-cols-3 gap-4">
            {/* Engine accuracy */}
            <div>
              <div className="text-[10px] uppercase tracking-wider text-[var(--text-faint)] mb-1">
                Engine accuracy
              </div>
              <div className="flex items-end gap-2">
                <span
                  className="text-[16px] font-medium tabular-nums"
                  style={{
                    color:
                      profile.engine_accuracy.current != null
                        ? profile.engine_accuracy.current >= 0.7
                          ? "var(--positive)"
                          : profile.engine_accuracy.current >= 0.5
                            ? "var(--warn)"
                            : "var(--negative)"
                        : "var(--text-faint)",
                  }}
                >
                  {profile.engine_accuracy.current != null
                    ? `${Math.round(profile.engine_accuracy.current * 100)}%`
                    : "—"}
                </span>
                {profile.engine_accuracy.history.length >= 2 && (
                  <AccuracySparkline
                    history={profile.engine_accuracy.history}
                    current={profile.engine_accuracy.current}
                  />
                )}
              </div>
              {profile.engine_accuracy.n_scored != null && (
                <div className="text-[9.5px] text-[var(--text-faint)] mt-0.5">
                  {profile.engine_accuracy.n_scored.toLocaleString()} scored
                </div>
              )}
            </div>

            {/* Experiments */}
            <div>
              <div className="text-[10px] uppercase tracking-wider text-[var(--text-faint)] mb-1">
                Studies
              </div>
              <div className="text-[16px] font-medium tabular-nums text-[var(--text-primary)]">
                {profile.experiments.registered}
              </div>
              <div className="text-[9.5px] text-[var(--text-faint)] mt-0.5">
                {profile.experiments.confirmed} confirmed
                {profile.experiments.active_priors > 0 &&
                  ` · ${profile.experiments.active_priors} active prior`}
              </div>
            </div>

            {/* Muscle coverage */}
            <div>
              <div className="text-[10px] uppercase tracking-wider text-[var(--text-faint)] mb-1">
                Muscle coverage
              </div>
              <div className="text-[16px] font-medium tabular-nums text-[var(--text-primary)]">
                {profile.muscle_coverage.personalized}
                <span className="text-[12px] font-normal text-[var(--text-dim)]">
                  /{profile.muscle_coverage.total}
                </span>
              </div>
              <div className="text-[9.5px] text-[var(--text-faint)] mt-0.5">personalized</div>
            </div>
          </div>

          {/* Data sources */}
          {profile.data_sources.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-2">
              {profile.data_sources.map((ds) => (
                <span
                  key={ds.source}
                  className="text-[9px] px-1.5 py-0.5 rounded uppercase tracking-wider"
                  style={{
                    color: ds.streaming ? "var(--positive)" : "var(--text-faint)",
                    border: `1px solid ${ds.streaming ? "var(--positive)" : "var(--hairline)"}40`,
                    background: ds.streaming ? "var(--positive)/0.05" : "transparent",
                  }}
                >
                  {ds.source} {ds.streaming ? "●" : "○"}
                </span>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
