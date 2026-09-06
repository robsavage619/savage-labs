"""Is this change real for THIS person, or is it inside their own noise?

Savage Health Center is a single-subject system, so a population threshold
answers the wrong question. "Where does Rob sit among people?" is almost never
what is being asked; "did something change for Rob?" is. A metric compared only
to a population cut-off cannot distinguish a real shift from ordinary day-to-day
variation, and every tile that does so has to render a verdict on a delta it
cannot actually resolve.

The reference for individual monitoring is the person's own variation. Hopkins'
0.2 x BETWEEN-subject SD does not apply to an n-of-1 series; the smallest
worthwhile change here is a fraction of the subject's own baseline SD. See
[[sesoi-typical-error-individual-change]] and
[[french-torres-ronda-2022-ch18-statistical-modeling]].

This module is deliberately read-only and gate-free. Nothing here feeds a
threshold, band-fit, volume decision or classifier — see ENGINE_INVARIANTS.md,
"the rule for changing the engine". It reports; it does not decide.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# Half the baseline SD. The 0.5 multiplier is the conventional "moderate"
# smallest-worthwhile-change for individual monitoring; it is a reporting
# convention, not a fitted parameter, and it is named here so no caller
# re-derives it differently.
_SWC_MULTIPLIER = 0.5

# Below this many observations a standard deviation is not worth quoting, so a
# noise floor built on it would be false precision.
_MIN_BASELINE_N = 7


def swc(baseline: list[float]) -> float | None:
    """Smallest worthwhile change for a subject's own baseline window.

    Args:
        baseline: The comparison window, in the metric's native units. Must be
            the SAME window the value is being compared against — a floor drawn
            from 28 days while banding a 7-day mean answers two different
            questions inside one verdict.

    Returns:
        Half the sample standard deviation, or ``None`` when the window is too
        short to support one. **Zero is a valid answer**, not an absence: a
        perfectly flat baseline means any movement at all sits outside the
        noise. Callers must test ``is not None``, never truthiness.
    """
    if len(baseline) < _MIN_BASELINE_N:
        return None
    mean = sum(baseline) / len(baseline)
    variance = sum((x - mean) ** 2 for x in baseline) / (len(baseline) - 1)
    return _SWC_MULTIPLIER * (variance**0.5)


@dataclass(frozen=True)
class NoiseVerdict:
    """A change, and whether the subject's own variation can resolve it."""

    value: float | None
    baseline: float | None
    delta: float | None
    swc: float | None
    within_noise: bool | None
    direction: Literal["up", "down", "flat", "unknown"]

    def as_dict(self) -> dict:
        return {
            "value": _round(self.value),
            "baseline": _round(self.baseline),
            "delta": _round(self.delta),
            "swc": _round(self.swc),
            "within_noise": self.within_noise,
            "direction": self.direction,
        }


def _round(v: float | None, places: int = 3) -> float | None:
    return None if v is None else round(v, places)


def classify_change(value: float | None, baseline_window: list[float]) -> NoiseVerdict:
    """Compare one observation against the window it came from.

    A delta smaller than the subject's SWC is reported as ``within_noise`` and
    its direction as ``flat``, whatever the sign of the arithmetic — that is the
    entire point. Rendering "improving" for a change the series cannot resolve
    is how a dashboard manufactures a trend.
    """
    if value is None or not baseline_window:
        return NoiseVerdict(value, None, None, None, None, "unknown")

    baseline = sum(baseline_window) / len(baseline_window)
    delta = value - baseline
    floor = swc(baseline_window)
    if floor is None:
        return NoiseVerdict(value, baseline, delta, None, None, "unknown")

    inside = abs(delta) < floor
    direction: Literal["up", "down", "flat", "unknown"] = (
        "flat" if inside else "up" if delta > 0 else "down"
    )
    return NoiseVerdict(value, baseline, delta, floor, inside, direction)
