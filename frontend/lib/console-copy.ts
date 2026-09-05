import type { DailyState } from "@/lib/api";

/**
 * Plain-English reads for the console channels.
 *
 * The rule these all follow: say the IMPLICATION, not the definition. Rob built
 * this engine — he knows what ACWR is. What "0.92" does not tell him is
 * "so you can push today", and that is the sentence worth the pixels.
 *
 * Three further rules, because they are what keep the board scannable:
 *   1. Second person. "You're training 8% under" beats "acute load is 8% below".
 *   2. Comparators in words, not raw baselines. "1 below your normal", not
 *      "base 42" — the number alone makes the reader do the subtraction.
 *   3. No enum, no snake_case and no bare acronym in the headline slot. The
 *      acronym survives as a quiet secondary tag for cross-reference.
 */

/** Where a value sits relative to its useful range. Drives colour, and colour
 *  is spent ONLY on this — a board where everything is tinted says nothing. */
export type ChannelState = "good" | "watch" | "alert" | "unknown";

export interface ChannelRead {
  /** Plain-language name. The acronym goes in `tag`, never here. */
  label: string;
  /** Optional cross-reference for Rob's own vocabulary, e.g. "ACWR". */
  tag?: string;
  value: string;
  unit?: string;
  state: ChannelState;
  /** One or two words. Shown beside the value. */
  status: string;
  /** The implication, in a sentence. This is the whole point of the channel. */
  read: string;
  /** Position of the marker on the band, 0–1. Null hides the band. */
  pos: number | null;
  /** Word labels under the band — left, middle, right. */
  bandLabels?: [string, string, string];
}

const NO_DATA = (label: string, tag?: string): ChannelRead => ({
  label,
  tag,
  value: "—",
  state: "unknown",
  status: "no data",
  read: "Nothing synced for this yet.",
  pos: null,
});

/** Clamp to 0–1 for band marker placement. */
function clamp01(x: number): number {
  return Math.max(0, Math.min(1, x));
}

/** "8% under", "3% over", "right on" — a signed ratio said in words. */
function pctPhrase(actual: number, reference: number): string {
  if (reference === 0) return "right on";
  const pct = Math.round(((actual - reference) / reference) * 100);
  if (pct === 0) return "right on";
  return `${Math.abs(pct)}% ${pct > 0 ? "over" : "under"}`;
}

function plural(n: number, one: string, many: string): string {
  return n === 1 ? one : many;
}

export function recoveryRead(s: DailyState): ChannelRead {
  const score = s.recovery.score;
  if (score == null) return NO_DATA("Recovery", "WHOOP");
  const state: ChannelState = score >= 67 ? "good" : score >= 34 ? "watch" : "alert";
  const read =
    score >= 67
      ? "Your body is ready for a hard session. Nothing is holding you back today."
      : score >= 34
        ? "Middling. Train, but this is not the day to chase a personal best."
        : "Your body is still paying off the last few days. Keep it light.";
  return {
    label: "Recovery",
    tag: "WHOOP",
    value: String(Math.round(score)),
    state,
    status: score >= 67 ? "ready" : score >= 34 ? "moderate" : "depleted",
    read,
    pos: clamp01(score / 100),
    bandLabels: ["depleted", "moderate", "ready"],
  };
}

export function hrvRead(s: DailyState): ChannelRead {
  const { hrv_ms: hrv, hrv_baseline_28d: base, hrv_sigma: sigma } = s.recovery;
  if (hrv == null) return NO_DATA("Heart rate variability", "HRV");
  const state: ChannelState =
    sigma == null ? "unknown" : sigma >= -1 ? "good" : sigma >= -2 ? "watch" : "alert";

  let read: string;
  if (sigma == null || base == null) {
    read = "Not enough history yet to say whether this is normal for you.";
  } else if (sigma >= 1) {
    read = `Well above your normal ${Math.round(base)}. Your nervous system is fresh — this is a green light for intensity.`;
  } else if (sigma >= -1) {
    read = `Normal for you — your usual is around ${Math.round(base)}. No signal either way.`;
  } else if (sigma >= -2) {
    read = `Below your usual ${Math.round(base)}. One night like this is noise; two or three in a row is fatigue.`;
  } else {
    read = `Well below your usual ${Math.round(base)}. Your nervous system is suppressed — treat today as recovery.`;
  }

  return {
    label: "Heart rate variability",
    tag: "HRV",
    value: hrv.toFixed(0),
    unit: "ms",
    state,
    status: sigma == null ? "—" : sigma >= 1 ? "elevated" : sigma >= -1 ? "normal" : "suppressed",
    read,
    // −3σ … +3σ mapped onto the band.
    pos: sigma == null ? null : clamp01((sigma + 3) / 6),
    bandLabels: ["suppressed", "normal", "fresh"],
  };
}

export function rhrRead(s: DailyState): ChannelRead {
  const { rhr, rhr_baseline_28d: base } = s.recovery;
  if (rhr == null) return NO_DATA("Resting heart rate", "RHR");
  const delta = base != null ? rhr - base : null;
  const state: ChannelState =
    delta == null ? "unknown" : delta <= 1 ? "good" : delta <= 4 ? "watch" : "alert";

  let read: string;
  if (delta == null) {
    read = "No baseline yet to compare against.";
  } else if (delta <= -2) {
    read = `${Math.abs(delta).toFixed(0)} below your normal — a sign you have absorbed the recent training.`;
  } else if (delta <= 1) {
    read = "Sitting at your normal. Nothing unusual going on underneath.";
  } else if (delta <= 4) {
    read = `${delta.toFixed(0)} above your normal. Usually means poor sleep, alcohol, heat or the start of something.`;
  } else {
    read = `${delta.toFixed(0)} above your normal — a big jump. Worth checking whether you are getting sick.`;
  }

  return {
    label: "Resting heart rate",
    tag: "RHR",
    value: rhr.toFixed(0),
    unit: "bpm",
    state,
    status: delta == null ? "—" : delta <= 1 ? "normal" : "elevated",
    // Band spans −6 … +8 around baseline.
    pos: delta == null ? null : clamp01((delta + 6) / 14),
    bandLabels: ["low", "normal", "elevated"],
    read,
  };
}

export function sleepRead(s: DailyState): ChannelRead {
  const hours = s.sleep.last_hours;
  const debt = s.sleep.debt_7d_h;
  if (hours == null) return NO_DATA("Sleep");
  const state: ChannelState = hours >= 7.5 ? "good" : hours >= 6.5 ? "watch" : "alert";

  const debtClause =
    debt == null || Math.abs(debt) < 0.25
      ? ""
      : debt > 0
        ? ` You are carrying about ${debt.toFixed(1)}h of debt across the week.`
        : ` You are ${Math.abs(debt).toFixed(1)}h ahead across the week.`;

  const base =
    hours >= 7.5
      ? "A full night. This is the single biggest lever you have on tomorrow's recovery."
      : hours >= 6.5
        ? "A bit short. One night is survivable; a pattern of these is what flattens HRV."
        : "Short night. Expect today's recovery number to under-read what you can actually do.";

  return {
    label: "Sleep",
    value: hours.toFixed(1),
    unit: "h",
    state,
    status: hours >= 7.5 ? "full" : hours >= 6.5 ? "short" : "very short",
    read: base + debtClause,
    pos: clamp01((hours - 4) / 6), // 4h … 10h
    bandLabels: ["4h", "7h", "10h"],
  };
}

export function loadRead(s: DailyState): ChannelRead {
  const { acwr, acute_load_7d: acute, chronic_load_21d: chronic } = s.training_load;
  if (acwr == null) return NO_DATA("Training load balance", "ACWR");

  const state: ChannelState =
    acwr >= 0.8 && acwr <= 1.3 ? "good" : acwr <= 1.5 ? "watch" : "alert";

  const compare =
    acute != null && chronic != null ? pctPhrase(acute, chronic) : null;
  const vs = compare ? `You are training ${compare} your three-week average. ` : "";

  const read =
    acwr < 0.8
      ? `${vs}That is less than your body is used to — you have room to add work.`
      : acwr <= 1.3
        ? `${vs}That is the range where fitness builds without piling up injury risk.`
        : acwr <= 1.5
          ? `${vs}You are ramping faster than usual. Fine for a week, not a month.`
          : `${vs}That is a sharp spike above what you are conditioned for — the zone where injuries happen.`;

  return {
    label: "Training load balance",
    tag: "ACWR",
    value: acwr.toFixed(2),
    state,
    status: acwr < 0.8 ? "under" : acwr <= 1.3 ? "building" : acwr <= 1.5 ? "ramping" : "spiking",
    read,
    pos: clamp01(acwr / 2),
    bandLabels: ["undertrained", "building", "too much"],
  };
}

export function freshnessRead(s: DailyState): ChannelRead {
  const { days_since_legs: legs, days_since_push: push, days_since_pull: pull } = s.training_load;
  const parts: [string, number][] = [
    ["legs", legs],
    ["push", push],
    ["pull", pull],
  ];
  const stalest = parts.reduce((a, b) => (b[1] > a[1] ? b : a));
  const freshest = parts.reduce((a, b) => (b[1] < a[1] ? b : a));

  // The rested group can also be the gated one — pickleball debits leg recovery
  // without ever showing up as a leg session, so "legs are your most rested
  // tissue" and "legs are locked" are both true at once. Saying only the first
  // reads as a contradiction against the lockout chips, so say both.
  const locked = new Set(
    [...(s.gates.forbid_muscle_groups ?? []), ...(s.gates.forbid_muscles ?? [])].map((m) =>
      m.toLowerCase(),
    ),
  );
  const stalestLocked = locked.has(stalest[0]);

  const days = `${stalest[1]} ${plural(stalest[1], "day", "days")}`;
  const opener = stalestLocked
    ? `Your ${stalest[0]} have had ${days} off, but they are gated today anyway — court time loads them without logging as a session.`
    : `Your ${stalest[0]} have had ${days} off, the freshest tissue you own.`;
  const closer =
    freshest[1] === 0
      ? ` You trained ${freshest[0]} today.`
      : ` ${freshest[0].charAt(0).toUpperCase()}${freshest[0].slice(1)} last went ${freshest[1]} ${plural(freshest[1], "day", "days")} ago.`;

  return {
    label: "What's rested",
    value: String(stalest[1]),
    unit: plural(stalest[1], "day", "days"),
    state: stalestLocked ? "watch" : stalest[1] >= 6 ? "watch" : "good",
    status: stalestLocked ? `${stalest[0]} · gated` : stalest[0],
    read: opener + closer,
    pos: null,
  };
}

export function aerobicRead(s: DailyState): ChannelRead {
  // The metabolic zone-2 dose, which spans WHOOP Z2 AND Z3. Reporting WHOOP's
  // own Z2 band alone undercounts the aerobic base by roughly 40%.
  const mins = s.training_load.cardio_aerobic_base_min_7d;
  if (mins == null) return NO_DATA("Aerobic base", "Zone 2");
  const target = 180;
  const state: ChannelState = mins >= target ? "good" : mins >= target * 0.6 ? "watch" : "alert";
  const short = Math.max(0, target - mins);

  return {
    label: "Aerobic base",
    tag: "Zone 2",
    value: String(Math.round(mins)),
    unit: "min",
    state,
    status: mins >= target ? "on target" : "short",
    read:
      mins >= target
        ? `Past the ${target} min/week that builds the aerobic engine. This is the work that makes everything else recover faster.`
        : `${Math.round(short)} min short of the ${target} min/week target. Easy pace counts — a long walk or a relaxed court session closes most of this.`,
    pos: clamp01(mins / (target * 1.4)),
    bandLabels: ["none", `${target} min`, "plenty"],
  };
}

export function balanceRead(s: DailyState): ChannelRead {
  const r = s.training_load.push_pull_ratio_28d;
  const { push_sets_28d: push, pull_sets_28d: pull } = s.training_load;
  if (r == null) return NO_DATA("Push / pull balance");
  const state: ChannelState = r >= 0.8 && r <= 1.2 ? "good" : "watch";

  return {
    label: "Push / pull balance",
    value: r.toFixed(2),
    state,
    status: r < 0.8 ? "pull-heavy" : r > 1.2 ? "push-heavy" : "balanced",
    read:
      r > 1.2
        ? `${push} pushing sets against ${pull} pulling over four weeks. Pressing is outpacing rowing — add back work before your shoulders complain.`
        : r < 0.8
          ? `${push} pushing sets against ${pull} pulling over four weeks. You are rowing more than you press, which is the safer way to be unbalanced.`
          : `${push} pushing sets against ${pull} pulling over four weeks. That is even, which is what keeps shoulders healthy.`,
    pos: clamp01((r - 0.4) / 1.2),
    bandLabels: ["all pull", "even", "all push"],
  };
}

/**
 * The two-or-three sentence lede that reads the whole board.
 *
 * Density only works if something orients you before you start scanning; this
 * is the paragraph that says what today is, so the channels below are evidence
 * rather than a quiz.
 */
export function boardLede(s: DailyState, verdict: string): string {
  const bits: string[] = [];
  const rec = s.recovery.score;
  const sleep = s.sleep.last_hours;
  const acwr = s.training_load.acwr;

  if (rec != null && sleep != null) {
    bits.push(
      `You slept ${sleep.toFixed(1)}h and came back at ${Math.round(rec)} recovery, so the call is ${verdict.toLowerCase()}.`,
    );
  } else if (rec != null) {
    bits.push(`Recovery is ${Math.round(rec)}, so the call is ${verdict.toLowerCase()}.`);
  } else {
    bits.push(`Today's call is ${verdict.toLowerCase()}.`);
  }

  if (acwr != null) {
    bits.push(
      acwr > 1.5
        ? "Your load has spiked well above what you are conditioned for, which is doing most of the work in that decision."
        : acwr >= 0.8 && acwr <= 1.3
          ? "Your training load is sitting in the range where fitness builds safely."
          : acwr < 0.8
            ? "You have been training below your usual volume, so there is room to add."
            : "You are ramping faster than usual — worth watching, not worth stopping for.",
    );
  }

  const locked = [
    ...(s.gates.forbid_muscle_groups ?? []),
    ...(s.gates.forbid_muscles ?? []),
  ];
  if (locked.length > 0) {
    bits.push(
      `${locked.slice(0, 3).join(", ").replace(/_/g, " ")} ${locked.length === 1 ? "is" : "are"} locked out today${
        s.gates.deload_reason ? ` — ${s.gates.deload_reason.toLowerCase()}` : ""
      }.`,
    );
  }

  return bits.join(" ");
}

export function allChannels(s: DailyState): ChannelRead[] {
  return [
    recoveryRead(s),
    hrvRead(s),
    rhrRead(s),
    sleepRead(s),
    loadRead(s),
    aerobicRead(s),
    freshnessRead(s),
    balanceRead(s),
  ];
}
