"""Welch's t-test with an exact Student-t p-value (regularized incomplete beta).

The normal approximation understates p at the small n's this app works with.
"""

from __future__ import annotations

import math
from statistics import variance


def _betacf(a: float, b: float, x: float) -> float:
    """Continued-fraction expansion for the incomplete beta (Numerical Recipes)."""
    maxit, eps, fpmin = 200, 3.0e-12, 1.0e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < fpmin:
        d = fpmin
    d = 1.0 / d
    h = d
    for m in range(1, maxit + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin:
            d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin:
            d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return h


def _betai(a: float, b: float, x: float) -> float:
    """Regularized incomplete beta function I_x(a, b)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    bt = math.exp(
        math.lgamma(a + b)
        - math.lgamma(a)
        - math.lgamma(b)
        + a * math.log(x)
        + b * math.log(1.0 - x)
    )
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * _betacf(a, b, x) / a
    return 1.0 - bt * _betacf(b, a, 1.0 - x) / b


def student_t_p(t: float, df: float) -> float:
    """Two-tailed p-value for Student's t with df degrees of freedom.

    Uses the regularized incomplete beta function — exact for any df, unlike the
    normal (z) approximation that understates p at the small n's used here.
    """
    if df <= 0:
        return 1.0
    x = df / (df + t * t)
    return max(0.0, min(1.0, _betai(df / 2.0, 0.5, x)))


def welch_t(a: list[float], b: list[float]) -> tuple[float, float] | None:
    """Welch's t for unequal variances. Returns (t, two-tailed p) or None."""
    if len(a) < 2 or len(b) < 2:
        return None
    ma, mb = sum(a) / len(a), sum(b) / len(b)
    va = variance(a)
    vb = variance(b)
    se = math.sqrt(va / len(a) + vb / len(b))
    if se == 0:
        return None
    t = (ma - mb) / se
    # Welch–Satterthwaite degrees of freedom, then the exact t-distribution p.
    df = (va / len(a) + vb / len(b)) ** 2 / (
        (va / len(a)) ** 2 / (len(a) - 1) + (vb / len(b)) ** 2 / (len(b) - 1)
    )
    return t, student_t_p(t, df)
