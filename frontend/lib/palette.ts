/**
 * Concrete colour strings for the "premium instrument" palette.
 *
 * Recharts writes `fill` / `stroke` straight onto SVG presentation attributes
 * and into `<defs>` gradients, where `var(--token)` does not resolve. Anything
 * handed to Recharts must therefore be a literal — these constants mirror the
 * `:root` token values in `app/globals.css` so the two stay in step.
 */

const BG = "oklch(0.145 0.008 250)";
const BG_ELEVATED = "oklch(0.185 0.009 250)";
const CARD_HOVER = "oklch(0.215 0.010 250)";

const HAIRLINE = "oklch(0.235 0.010 250)";
const HAIRLINE_STRONG = "oklch(0.285 0.012 250)";

const TEXT_PRIMARY = "oklch(0.965 0.003 250)";
const TEXT_MUTED = "oklch(0.760 0.010 250)";
const TEXT_DIM = "oklch(0.615 0.012 250)";
const TEXT_FAINT = "oklch(0.480 0.012 250)";

const ACCENT = "oklch(0.760 0.115 215)";
const OK = "oklch(0.760 0.130 155)";
const WARN = "oklch(0.800 0.135 78)";
const BAD = "oklch(0.680 0.170 25)";

/** Append an alpha channel to an `oklch(l c h)` literal from this module. */
export function withAlpha(color: string, a: number): string {
  return color.replace(/\)\s*$/, ` / ${a})`);
}

export const CHART = {
  // surfaces
  bg: BG,
  surface: BG_ELEVATED,
  tooltip: CARD_HOVER,
  // lines
  hairline: HAIRLINE,
  hairlineStrong: HAIRLINE_STRONG,
  grid: "oklch(1 0 0 / 0.05)",
  cursor: "oklch(1 0 0 / 0.04)",
  // text / axes
  text: TEXT_PRIMARY,
  textMuted: TEXT_MUTED,
  textDim: TEXT_DIM,
  axis: TEXT_FAINT,
  // series
  line: ACCENT,
  lineDim: withAlpha(ACCENT, 0.25),
  baseline: TEXT_FAINT,
  band: withAlpha(ACCENT, 0.1),
  ctl: ACCENT,
  atl: WARN,
  // semantic
  ok: OK,
  warn: WARN,
  bad: BAD,
} as const;
