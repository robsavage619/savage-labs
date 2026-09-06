"""Correlation with an interval, because a bare r is not a finding.

Every claim this package makes about one signal predicting another has to carry
its uncertainty. An r of +0.21 on n=54 and an r of +0.21 on n=5000 are different
statements, and the version of this analysis that reports only the coefficient
lets the first masquerade as the second.
"""

from __future__ import annotations

import math
from statistics import mean


def pearson(xs: list[float], ys: list[float]) -> float | None:
    """Pearson product-moment correlation, or None if it is undefined."""
    if len(xs) != len(ys) or len(xs) < 3:
        return None
    mx, my = mean(xs), mean(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den = (sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys)) ** 0.5
    return num / den if den else None


def fisher_ci(r: float | None, n: int, conf: float = 1.96) -> tuple[float | None, float | None]:
    """95% CI for a correlation via Fisher's z-transform."""
    if r is None or n < 6 or abs(r) >= 1.0:
        return (None, None)
    z = 0.5 * math.log((1 + r) / (1 - r))
    se = 1.0 / math.sqrt(n - 3)
    return (round(math.tanh(z - conf * se), 3), round(math.tanh(z + conf * se), 3))


def correlate(xs: list[float], ys: list[float]) -> dict:
    """r, n, CI, and whether the interval excludes zero — the whole verdict."""
    r = pearson(xs, ys)
    lo, hi = fisher_ci(r, len(xs))
    return {
        "r": round(r, 3) if r is not None else None,
        "n": len(xs),
        "ci95": [lo, hi],
        # The only field a caller should branch on. "Significant" is doing no
        # work here beyond "the interval does not contain zero".
        "excludes_zero": bool(lo is not None and hi is not None and lo * hi > 0),
    }
