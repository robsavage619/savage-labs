"""Smallest-detectable-change gate, grounded in ISAK technical error of measurement.

Intra-rater girth TEM is ~1–2% (see METHODOLOGY.md §2). We adopt the conservative
2% bound: any measurement delta smaller than 2% of baseline is statistically
indistinguishable from measurement noise and must be reported as "no detectable
change" rather than as progress.
"""

from __future__ import annotations

from dataclasses import dataclass

# ISAK intra-rater girth TEM upper bound (METHODOLOGY.md §2).
GIRTH_NOISE_FRACTION = 0.02


@dataclass(frozen=True)
class ChangeVerdict:
    """Result of comparing one metric across two dates.

    Attributes:
        metric: Metric name.
        before: Earlier normalized value.
        after: Later normalized value.
        delta: after - before.
        pct: Signed fractional change relative to ``before``.
        detectable: True only if ``|delta|`` exceeds the ISAK noise floor.
        direction: 'up', 'down', or 'none' (none when not detectable).
    """

    metric: str
    before: float
    after: float
    delta: float
    pct: float
    detectable: bool
    direction: str


def classify_change(metric: str, before: float, after: float) -> ChangeVerdict:
    """Classify a metric change against the ISAK-derived noise floor.

    Args:
        metric: Metric name (e.g. ``"waist_to_shoulder"``).
        before: Earlier normalized measurement.
        after: Later normalized measurement.

    Returns:
        A :class:`ChangeVerdict`. ``detectable`` is False when the change sits
        inside the 2% measurement-error band, in which case ``direction`` is
        ``"none"`` regardless of the sign of the delta.
    """
    delta = after - before
    pct = delta / before if before else 0.0
    detectable = abs(pct) >= GIRTH_NOISE_FRACTION
    direction = "none" if not detectable else ("up" if delta > 0 else "down")
    return ChangeVerdict(
        metric=metric,
        before=before,
        after=after,
        delta=delta,
        pct=pct,
        detectable=detectable,
        direction=direction,
    )
