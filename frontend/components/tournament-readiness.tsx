"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type PickleballEvent, type PickleballEventDay } from "@/lib/api";
import { cn } from "@/lib/utils";

const MINUS = "−";

/** "2026-08-29" -> "Aug 29, 2026". Parsed field-wise so no timezone can shift the day. */
function fmtDate(iso: string, opts?: { weekday?: boolean }): string {
  const [y, m, d] = iso.split("-").map(Number);
  if (!y || !m || !d) return iso;
  const dt = new Date(y, m - 1, d);
  return dt.toLocaleDateString("en-US", {
    weekday: opts?.weekday ? "short" : undefined,
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function signed(n: number, digits: number): string {
  const s = Math.abs(n).toFixed(digits);
  if (n > 0) return `+${s}`;
  if (n < 0) return `${MINUS}${s}`;
  return s;
}

function offsetLabel(offset: number): string {
  if (offset === 0) return "0";
  return offset > 0 ? `+${offset}` : `${MINUS}${Math.abs(offset)}`;
}

/** WHOOP recovery bands: green >=67, amber 34-66, red <34. */
function recoveryVar(recovery: number | null): string {
  if (recovery == null) return "var(--hairline-strong)";
  if (recovery >= 67) return "var(--positive)";
  if (recovery >= 34) return "var(--neutral)";
  return "var(--negative)";
}

function deltaVar(delta: number | null): string {
  if (delta == null || delta === 0) return "var(--text-dim)";
  return delta > 0 ? "var(--positive)" : "var(--negative)";
}

function dayTitle(day: PickleballEventDay): string {
  const parts = [
    fmtDate(day.date, { weekday: true }),
    day.offset === 0 ? "event day" : `${offsetLabel(day.offset)}d`,
    `recovery ${day.recovery ?? "—"}`,
    `HRV ${day.hrv != null ? `${day.hrv.toFixed(0)} ms` : "—"}`,
    `RHR ${day.rhr != null ? `${day.rhr.toFixed(0)} bpm` : "—"}`,
    `sleep ${day.sleep_h != null ? `${day.sleep_h.toFixed(1)} h` : "—"}`,
    `${day.lifts} lift${day.lifts === 1 ? "" : "s"}`,
    `${Math.round(day.court_min)} court min`,
  ];
  return parts.join(" · ");
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <div className="text-[8.5px] uppercase tracking-[0.12em] text-[var(--text-faint)] truncate">
        {label}
      </div>
      <div
        className="text-[11.5px] tabular-nums text-[var(--text-muted)] truncate"
        style={{ fontFamily: "var(--font-data)" }}
      >
        {value}
      </div>
    </div>
  );
}

function DayColumn({
  day,
  courtMax,
  active,
  onEnter,
}: {
  day: PickleballEventDay;
  courtMax: number;
  active: boolean;
  onEnter: () => void;
}) {
  const isEvent = day.offset === 0;
  const recPct = day.recovery == null ? 0 : Math.max(3, Math.min(100, day.recovery));
  const courtPct = day.court_min > 0 ? Math.max(12, (day.court_min / courtMax) * 100) : 0;
  const liftDots = Math.min(day.lifts, 3);

  return (
    <button
      type="button"
      title={dayTitle(day)}
      aria-label={dayTitle(day)}
      onMouseEnter={onEnter}
      onFocus={onEnter}
      onClick={onEnter}
      className={cn(
        "min-w-0 flex flex-col items-stretch gap-[3px] rounded-[4px] p-[3px] text-left",
        "transition-colors outline-none",
        active && "bg-[var(--card-hover)]",
      )}
      style={
        isEvent
          ? {
              boxShadow: "inset 0 0 0 1px color-mix(in oklch, var(--sl-accent) 45%, transparent)",
              background: active
                ? "var(--card-hover)"
                : "color-mix(in oklch, var(--sl-accent) 8%, transparent)",
            }
          : undefined
      }
    >
      {/* recovery */}
      <div
        className="relative w-full h-[44px] @min-[560px]:h-[58px] rounded-[3px] overflow-hidden"
        style={{ background: "color-mix(in oklch, var(--hairline) 60%, transparent)" }}
      >
        {day.recovery == null ? (
          <div className="absolute inset-x-0 bottom-0 h-px" style={{ background: "var(--hairline-strong)" }} />
        ) : (
          <div
            className="absolute inset-x-0 bottom-0 rounded-[3px]"
            style={{
              height: `${recPct}%`,
              background: recoveryVar(day.recovery),
              opacity: isEvent || active ? 0.95 : 0.62,
            }}
          />
        )}
      </div>

      {/* court minutes */}
      <div
        className="relative w-full h-[12px] @min-[560px]:h-[16px] rounded-[2px] overflow-hidden"
        style={{ background: "color-mix(in oklch, var(--hairline) 45%, transparent)" }}
      >
        {courtPct > 0 && (
          <div
            className="absolute inset-x-0 bottom-0"
            style={{
              height: `${courtPct}%`,
              background: "var(--sl-accent)",
              opacity: isEvent || active ? 0.85 : 0.5,
            }}
          />
        )}
      </div>

      {/* lifts */}
      <div className="flex h-[5px] items-center justify-center gap-[2px]">
        {Array.from({ length: liftDots }).map((_, i) => (
          <span
            key={i}
            className="block h-[4px] w-[4px] rounded-[1px]"
            style={{ background: "var(--text-muted)", opacity: active ? 1 : 0.75 }}
          />
        ))}
      </div>
    </button>
  );
}

function EventBlock({ event }: { event: PickleballEvent }) {
  const days = event.days;
  const eventDay = days.find((d) => d.offset === 0) ?? days[0] ?? null;
  const [hovered, setHovered] = useState<string | null>(null);
  const readout = days.find((d) => d.date === hovered) ?? eventDay;

  const courtMax = useMemo(
    () => Math.max(1, ...days.map((d) => d.court_min)),
    [days],
  );

  const delta = event.dupr_delta;

  return (
    <div
      className="min-w-0 rounded-[var(--r-md)] border border-[var(--hairline)] p-3 @min-[560px]:p-4"
      style={{ background: "var(--card)" }}
      onMouseLeave={() => setHovered(null)}
    >
      {/* header */}
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <div className="min-w-0">
          <div
            className="truncate text-[var(--fs-read)] font-medium text-[var(--text-primary)]"
            title={event.event_name}
          >
            {event.event_name}
          </div>
          <div className="truncate text-[10px] text-[var(--text-faint)]">
            {fmtDate(event.event_date)}
            {event.venue ? ` · ${event.venue}` : ""}
          </div>
        </div>
        <div className="flex min-w-0 shrink-0 items-baseline gap-3">
          <div
            className="tabular-nums text-[13px] text-[var(--text-muted)]"
            style={{ fontFamily: "var(--font-data)" }}
            title={`${event.wins} wins, ${event.losses} losses`}
          >
            {event.wins}
            <span className="text-[var(--text-faint)]">W</span>
            {MINUS}
            {event.losses}
            <span className="text-[var(--text-faint)]">L</span>
          </div>
          <div className="text-right">
            <div
              className="tabular-nums text-[13px]"
              style={{ fontFamily: "var(--font-data)", color: deltaVar(delta) }}
            >
              {delta == null ? "—" : signed(delta, 3)}
            </div>
            <div className="text-[8px] uppercase tracking-[0.12em] text-[var(--text-faint)]">
              DUPR
            </div>
          </div>
        </div>
      </div>

      {/* summary line */}
      <div className="mt-3 flex flex-wrap items-center gap-x-2 gap-y-1 text-[10.5px] text-[var(--text-dim)]">
        <span className="inline-flex items-center gap-1.5">
          <span
            className="inline-block h-[7px] w-[7px] rounded-full"
            style={{ background: recoveryVar(event.recovery_on_day) }}
          />
          <span>
            Recovery on the day{" "}
            <span className="tabular-nums text-[var(--text-primary)]">
              {event.recovery_on_day ?? "—"}
            </span>
          </span>
        </span>
        <span className="text-[var(--hairline-strong)]">|</span>
        <span>
          Played{" "}
          <span className="tabular-nums text-[var(--text-muted)]">
            {Math.round(event.court_min_on_day)} min
          </span>
        </span>
        <span className="text-[var(--hairline-strong)]">|</span>
        <span>
          72h before:{" "}
          <span className="tabular-nums text-[var(--text-muted)]">
            {event.lifts_prior_3d} lift{event.lifts_prior_3d === 1 ? "" : "s"}
          </span>
          {" · "}
          <span className="tabular-nums text-[var(--text-muted)]">
            {Math.round(event.court_min_prior_3d)} court min
          </span>
        </span>
      </div>

      {/* day strip */}
      <div className="mt-3 min-w-0">
        <div className="grid grid-cols-11 gap-[2px] @min-[560px]:gap-[3px]">
          {days.map((d) => (
            <DayColumn
              key={d.date}
              day={d}
              courtMax={courtMax}
              active={readout?.date === d.date}
              onEnter={() => setHovered(d.date)}
            />
          ))}
        </div>
        {/* axis */}
        <div className="mt-1 grid grid-cols-11 gap-[2px] @min-[560px]:gap-[3px]">
          {days.map((d) => (
            <div key={d.date} className="min-w-0 text-center">
              {d.offset === 0 ? (
                <span
                  className="block whitespace-nowrap text-[7.5px] font-medium uppercase tracking-[0.06em] @min-[560px]:text-[8.5px]"
                  style={{ color: "var(--sl-accent)" }}
                >
                  EVENT
                </span>
              ) : (
                <span className="block text-[8px] tabular-nums text-[var(--text-faint)] @min-[560px]:text-[9px]">
                  {offsetLabel(d.offset)}
                </span>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* readout */}
      {readout && (
        <div className="mt-3 min-w-0 rounded-[6px] border border-[var(--hairline)] px-2.5 py-2">
          <div className="mb-1.5 flex flex-wrap items-baseline justify-between gap-x-2 gap-y-0.5">
            <span className="min-w-0 truncate text-[10.5px] text-[var(--text-muted)]">
              {fmtDate(readout.date, { weekday: true })}
            </span>
            <span className="shrink-0 text-[9px] uppercase tracking-[0.12em] text-[var(--text-faint)]">
              {readout.offset === 0 ? "event day" : `${offsetLabel(readout.offset)} days`}
            </span>
          </div>
          <div className="grid grid-cols-3 gap-x-2 gap-y-1.5 @min-[440px]:grid-cols-6">
            <Stat label="Rec" value={readout.recovery != null ? `${readout.recovery}` : "—"} />
            <Stat label="HRV" value={readout.hrv != null ? `${readout.hrv.toFixed(0)}` : "—"} />
            <Stat label="RHR" value={readout.rhr != null ? `${readout.rhr.toFixed(0)}` : "—"} />
            <Stat label="Sleep" value={readout.sleep_h != null ? `${readout.sleep_h.toFixed(1)}h` : "—"} />
            <Stat label="Lifts" value={`${readout.lifts}`} />
            <Stat label="Court" value={readout.court_min > 0 ? `${Math.round(readout.court_min)}m` : "0"} />
          </div>
        </div>
      )}
    </div>
  );
}

export function TournamentReadiness() {
  const q = useQuery({
    queryKey: ["pickleball-events"],
    queryFn: () => api.pickleballEvents(),
    refetchInterval: 60 * 60_000,
  });

  const events = useMemo(() => {
    const list = q.data?.events ?? [];
    return [...list].sort((a, b) => b.event_date.localeCompare(a.event_date));
  }, [q.data]);

  if (q.isLoading) {
    return (
      <div className="space-y-3">
        <div className="shc-skeleton h-[40px] rounded-lg" />
        <div className="shc-skeleton h-[190px] rounded-lg" />
        <div className="shc-skeleton h-[190px] rounded-lg" />
      </div>
    );
  }

  if (q.isError) {
    return (
      <div className="rounded-[var(--r-md)] border border-[var(--hairline)] p-6 text-center">
        <p className="text-[12px] text-[var(--text-dim)]">Couldn&apos;t load tournament history.</p>
      </div>
    );
  }

  return (
    <div className="@container min-w-0 space-y-4">
      <p className="shc-helptext">
        <span className="text-[var(--text-muted)]">A log, not a formula. </span>
        Each block is the week around one tournament — what you carried in, what the day itself
        looked like, and how the days after went. It records what you did; it does not claim any of
        it produced the result.
      </p>

      {q.data?.sample_warning && (
        <div
          className="min-w-0 rounded-[var(--r-md)] border px-3 py-2.5"
          style={{
            borderColor: "color-mix(in oklch, var(--neutral) 32%, transparent)",
            background: "color-mix(in oklch, var(--neutral) 8%, transparent)",
          }}
        >
          <p className="eyebrow" style={{ color: "var(--neutral)" }}>
            Sample warning
          </p>
          <p className="mt-1 text-[11.5px] leading-snug text-[var(--text-muted)]">
            {q.data.sample_warning}
          </p>
        </div>
      )}

      {events.length === 0 ? (
        <div className="rounded-[var(--r-md)] border border-[var(--hairline)] p-6 text-center">
          <p className="text-[12px] text-[var(--text-dim)]">No tournaments logged yet.</p>
          <p className="mt-1 text-[10.5px] text-[var(--text-faint)]">
            Events appear here once DUPR match history is synced.
          </p>
        </div>
      ) : (
        <>
          <div className="space-y-3">
            {events.map((e) => (
              <EventBlock key={`${e.event_date}-${e.event_name}`} event={e} />
            ))}
          </div>

          {/* legend */}
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-[9.5px] text-[var(--text-faint)]">
            <span className="inline-flex items-center gap-1.5">
              <span className="inline-block h-[8px] w-[4px] rounded-[1px]" style={{ background: "var(--positive)" }} />
              <span className="inline-block h-[8px] w-[4px] rounded-[1px]" style={{ background: "var(--neutral)" }} />
              <span className="inline-block h-[8px] w-[4px] rounded-[1px]" style={{ background: "var(--negative)" }} />
              recovery (tall bar)
            </span>
            <span className="inline-flex items-center gap-1.5">
              <span className="inline-block h-[5px] w-[10px] rounded-[1px]" style={{ background: "var(--sl-accent)" }} />
              court minutes
            </span>
            <span className="inline-flex items-center gap-1.5">
              <span className="inline-block h-[4px] w-[4px] rounded-[1px]" style={{ background: "var(--text-muted)" }} />
              one lifting session
            </span>
          </div>

          {events.length < 5 && (
            <p className="text-[10px] leading-snug text-[var(--text-faint)]">
              {events.length} event{events.length === 1 ? "" : "s"} is far too few to read a pattern
              into, in either direction. Preparation, the day, and the result are shown side by side
              because they happened together — not because one explains another. Read each block on
              its own.
            </p>
          )}
        </>
      )}
    </div>
  );
}
