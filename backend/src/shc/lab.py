from __future__ import annotations

"""Personal research lab — runs the pre-registered hypothesis catalogue against
the live time-series and writes verdicts to lab_findings.

Each question has a fixed test type and threshold so we can't p-hack — only
the data moves. Triggered weekly via `shc lab-run` or on-demand via
POST /api/lab/run.
"""

import json
import logging
import math
import statistics as _st
import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

log = logging.getLogger(__name__)

# Significance level for confirming a finding, and the family-wise FDR rate
# applied across the whole catalogue (see _apply_fdr). A correlation or mean
# difference must clear BOTH its effect-size threshold AND p < _ALPHA, then
# survive Benjamini–Hochberg correction, before it is reported as CONFIRMED.
_ALPHA = 0.10


@dataclass
class LabFinding:
    question_id: str
    n: int
    effect_size: float | None
    effect_unit: str
    p_value: float | None
    # 'error' is not a result — it means the runner raised and the hypothesis
    # was never actually tested. Kept distinct from 'inconclusive' so a crash
    # can't masquerade as a null finding.
    verdict: str  # 'confirmed' | 'refuted' | 'insufficient' | 'inconclusive' | 'error'
    summary: str
    evidence: list[dict]


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
        math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
        + a * math.log(x) + b * math.log(1.0 - x)
    )
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * _betacf(a, b, x) / a
    return 1.0 - bt * _betacf(b, a, 1.0 - x) / b


def _student_t_p(t: float, df: float) -> float:
    """Two-tailed p-value for Student's t with df degrees of freedom.

    Uses the regularized incomplete beta function — exact for any df, unlike the
    normal (z) approximation that understates p at the small n's used here.
    """
    if df <= 0:
        return 1.0
    x = df / (df + t * t)
    return max(0.0, min(1.0, _betai(df / 2.0, 0.5, x)))


def _welch_t(a: list[float], b: list[float]) -> tuple[float, float] | None:
    """Welch's t for unequal variances. Returns (t, two-tailed p) or None."""
    if len(a) < 2 or len(b) < 2:
        return None
    ma, mb = sum(a) / len(a), sum(b) / len(b)
    va = _st.variance(a)
    vb = _st.variance(b)
    se = math.sqrt(va / len(a) + vb / len(b))
    if se == 0:
        return None
    t = (ma - mb) / se
    # Welch–Satterthwaite degrees of freedom, then the exact t-distribution p.
    df = (va / len(a) + vb / len(b)) ** 2 / (
        (va / len(a)) ** 2 / (len(a) - 1) + (vb / len(b)) ** 2 / (len(b) - 1)
    )
    return t, _student_t_p(t, df)


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 3 or len(xs) != len(ys):
        return None
    mx = sum(xs) / len(xs)
    my = sum(ys) / len(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if dx == 0 or dy == 0:
        return None
    return num / (dx * dy)


def _pearson_p(r: float, n: int) -> float | None:
    """Two-tailed significance of a Pearson r via t = r·√((n−2)/(1−r²))."""
    if n < 3 or abs(r) >= 1.0:
        return None
    t = r * math.sqrt((n - 2) / (1.0 - r * r))
    return _student_t_p(t, n - 2)


def _hrv_baseline_28d(rows: list[tuple]) -> dict[date, float]:
    """Return {date: trailing_28d_mean_hrv}.

    Expects rows shaped ``(date, hrv, ...)`` — HRV at index 1, the second
    column every caller selects. Keyed by the raw ``datetime.date`` so the
    date-object lookups in every caller resolve.
    """
    out: dict[date, float] = {}
    for i, r in enumerate(rows):
        prev = [float(x[1]) for x in rows[max(0, i - 28):i] if x[1] is not None]
        if len(prev) >= 7:
            # Key by the raw date object — every caller looks up with a
            # datetime.date, so stringifying the key here silently misses.
            out[r[0]] = sum(prev) / len(prev)
    return out


def _run_sleep_short_hrv_drop(conn, q: dict) -> LabFinding:
    """Paired comparison: HRV after <6.5h sleep vs HRV after ≥7h sleep."""
    since = (date.today() - timedelta(days=q["window_days"])).isoformat()
    rows = conn.execute(
        """
        SELECT r.date, r.hrv,
               (SELECT epoch(s.ts_out - s.ts_in) / 3600.0
                FROM sleep s
                WHERE s.night_date = r.date
                  AND COALESCE(s.is_nap, FALSE) = FALSE
                ORDER BY s.ts_in LIMIT 1) AS hours
        FROM recovery r
        WHERE r.date >= $s AND r.hrv IS NOT NULL
        ORDER BY r.date
        """,
        {"s": since},
    ).fetchall()
    if len(rows) < q["min_n"]:
        return LabFinding(q["id"], len(rows), None, "ms", None, "insufficient",
                          f"Only {len(rows)} matched days — need {q['min_n']}.", [])

    short_next: list[float] = []
    normal_next: list[float] = []
    evidence: list[dict] = []
    for i in range(len(rows) - 1):
        d, _hrv, hrs = rows[i]
        next_hrv = rows[i + 1][1]
        if hrs is None or next_hrv is None:
            continue
        h = float(hrs)
        if h < 6.5:
            short_next.append(float(next_hrv))
            evidence.append({"date": str(d), "sleep_h": round(h, 2), "next_hrv": float(next_hrv), "bucket": "short"})
        elif h >= 7.5:
            normal_next.append(float(next_hrv))
            evidence.append({"date": str(d), "sleep_h": round(h, 2), "next_hrv": float(next_hrv), "bucket": "normal"})

    if len(short_next) < 3 or len(normal_next) < 3:
        return LabFinding(q["id"], len(short_next), None, "ms", None, "insufficient",
                          f"Need ≥3 nights in each bucket; have {len(short_next)} short / {len(normal_next)} normal.",
                          evidence[-30:])

    delta = sum(short_next) / len(short_next) - sum(normal_next) / len(normal_next)
    res = _welch_t(short_next, normal_next)
    p = res[1] if res else None
    threshold = -float(q["threshold"])  # direction='negative'

    if delta <= threshold and (p is None or p < 0.10):
        verdict = "confirmed"
    elif delta > 0:
        verdict = "refuted"
    else:
        verdict = "inconclusive"

    return LabFinding(
        q["id"], len(short_next) + len(normal_next), round(delta, 2), "ms", p, verdict,
        f"Short-sleep nights ({len(short_next)}) average {sum(short_next)/len(short_next):.1f}ms next-morning HRV "
        f"vs {sum(normal_next)/len(normal_next):.1f}ms after ≥7.5h ({len(normal_next)} nights). Δ={delta:+.1f}ms.",
        evidence[-60:],
    )


def _run_long_sleep_hrv_lift(conn, q: dict) -> LabFinding:
    since = (date.today() - timedelta(days=q["window_days"])).isoformat()
    rows = conn.execute(
        """
        SELECT r.date, r.hrv,
               (SELECT epoch(s.ts_out - s.ts_in) / 3600.0 FROM sleep s
                WHERE s.night_date = r.date AND COALESCE(s.is_nap, FALSE) = FALSE
                ORDER BY s.ts_in LIMIT 1) AS hours
        FROM recovery r WHERE r.date >= $s AND r.hrv IS NOT NULL ORDER BY r.date
        """,
        {"s": since},
    ).fetchall()
    long_next: list[float] = []
    normal_next: list[float] = []
    evidence: list[dict] = []
    for i in range(len(rows) - 1):
        d, _hrv, hrs = rows[i]
        nxt = rows[i + 1][1]
        if hrs is None or nxt is None:
            continue
        h = float(hrs)
        if h >= 8.0:
            long_next.append(float(nxt))
            evidence.append({"date": str(d), "sleep_h": round(h, 2), "next_hrv": float(nxt), "bucket": "long"})
        elif 6.5 <= h < 7.5:
            normal_next.append(float(nxt))
            evidence.append({"date": str(d), "sleep_h": round(h, 2), "next_hrv": float(nxt), "bucket": "normal"})
    if len(long_next) < 3 or len(normal_next) < 3:
        return LabFinding(q["id"], len(long_next) + len(normal_next), None, "ms", None, "insufficient",
                          f"Need ≥3 nights in each bucket; have {len(long_next)} long / {len(normal_next)} normal.",
                          evidence[-30:])
    delta = sum(long_next) / len(long_next) - sum(normal_next) / len(normal_next)
    res = _welch_t(long_next, normal_next)
    p = res[1] if res else None
    threshold = float(q["threshold"])
    if delta >= threshold and (p is None or p < 0.10):
        verdict = "confirmed"
    elif delta < 0:
        verdict = "refuted"
    else:
        verdict = "inconclusive"
    return LabFinding(
        q["id"], len(long_next) + len(normal_next), round(delta, 2), "ms", p, verdict,
        f"After ≥8h sleep ({len(long_next)} nights) HRV averages {sum(long_next)/len(long_next):.1f}ms vs "
        f"{sum(normal_next)/len(normal_next):.1f}ms after 6.5-7.5h ({len(normal_next)}). Δ={delta:+.1f}ms.",
        evidence[-60:],
    )


def _run_pickleball_next_morning(conn, q: dict) -> LabFinding:
    since = (date.today() - timedelta(days=q["window_days"])).isoformat()
    rows = conn.execute(
        """
        WITH pb AS (
            SELECT date AS day, COUNT(*) AS n
            FROM cardio_sessions
            WHERE LOWER(modality) = 'pickleball'
              AND date >= $s
            GROUP BY date
        )
        SELECT r.date, r.hrv, COALESCE(pb.n, 0) AS pb
        FROM recovery r
        LEFT JOIN pb ON pb.day = r.date
        WHERE r.date >= $s AND r.hrv IS NOT NULL
        ORDER BY r.date
        """,
        {"s": since},
    ).fetchall()
    pb_next: list[float] = []
    rest_next: list[float] = []
    evidence: list[dict] = []
    for i in range(len(rows) - 1):
        d, _hrv, pb = rows[i]
        nxt = rows[i + 1][1]
        if nxt is None:
            continue
        if pb and int(pb) > 0:
            pb_next.append(float(nxt))
            evidence.append({"date": str(d), "session": "pickleball", "next_hrv": float(nxt)})
        else:
            rest_next.append(float(nxt))
    if len(pb_next) < 3 or len(rest_next) < 3:
        return LabFinding(q["id"], len(pb_next), None, "ms", None, "insufficient",
                          f"Need ≥3 sessions; have {len(pb_next)} pickleball / {len(rest_next)} rest.",
                          evidence[-30:])
    delta = sum(pb_next) / len(pb_next) - sum(rest_next) / len(rest_next)
    res = _welch_t(pb_next, rest_next)
    p = res[1] if res else None
    threshold = -float(q["threshold"])
    if delta <= threshold and (p is None or p < 0.10):
        verdict = "confirmed"
    elif delta > 0:
        verdict = "refuted"
    else:
        verdict = "inconclusive"
    return LabFinding(
        q["id"], len(pb_next) + len(rest_next), round(delta, 2), "ms", p, verdict,
        f"After pickleball ({len(pb_next)} days): next-AM HRV {sum(pb_next)/len(pb_next):.1f}ms; "
        f"after rest ({len(rest_next)}): {sum(rest_next)/len(rest_next):.1f}ms. Δ={delta:+.1f}ms.",
        evidence[-60:],
    )


def _run_skin_temp_illness_alarm(conn, q: dict) -> LabFinding:
    since = (date.today() - timedelta(days=q["window_days"])).isoformat()
    rows = conn.execute(
        """
        SELECT date, score, skin_temp
        FROM recovery
        WHERE date >= $s AND skin_temp IS NOT NULL
        ORDER BY date
        """,
        {"s": since},
    ).fetchall()
    if len(rows) < q["min_n"]:
        return LabFinding(q["id"], len(rows), None, "rate", None, "insufficient",
                          f"Only {len(rows)} days with skin-temp readings.", [])

    # Compute trailing 28d mean per row
    temps = [float(r[2]) for r in rows]
    triggers = 0
    triggers_followed_by_red = 0
    evidence: list[dict] = []
    for i in range(28, len(rows) - 2):
        baseline = sum(temps[i - 28:i]) / 28
        # 1°F ≈ 0.556°C — convert if storage is °C
        delta_c = temps[i] - baseline
        delta_f = delta_c * 1.8 if abs(delta_c) < 5 else delta_c  # heuristic if already °F
        if delta_f >= 1.0:
            triggers += 1
            next2 = [r[1] for r in rows[i + 1:i + 3] if r[1] is not None]
            red_next = any(s is not None and float(s) < 34 for s in next2)
            if red_next:
                triggers_followed_by_red += 1
            evidence.append({
                "date": str(rows[i][0]),
                "skin_temp": temps[i],
                "delta_f": round(delta_f, 2),
                "red_next_48h": red_next,
            })

    if triggers < 3:
        return LabFinding(q["id"], triggers, None, "rate", None, "insufficient",
                          f"Only {triggers} skin-temp triggers in window — need ≥3.", evidence[-30:])

    rate = triggers_followed_by_red / triggers
    if rate >= float(q["threshold"]):
        verdict = "confirmed"
    elif rate < 0.2:
        verdict = "refuted"
    else:
        verdict = "inconclusive"
    return LabFinding(
        q["id"], triggers, round(rate, 3), "rate", None, verdict,
        f"{triggers_followed_by_red}/{triggers} skin-temp ≥+1°F days were followed by a red-recovery day "
        f"within 48h ({rate*100:.0f}%).",
        evidence[-30:],
    )


def _run_strain_high_rhr_next(conn, q: dict) -> LabFinding:
    since = (date.today() - timedelta(days=q["window_days"])).isoformat()
    rows = conn.execute(
        """
        WITH d AS (
            SELECT date, MAX(strain) AS strain
            FROM daily_cycle
            WHERE date >= $s
            GROUP BY date
        )
        SELECT r.date, r.rhr, d.strain
        FROM recovery r
        LEFT JOIN d ON d.date = r.date
        WHERE r.date >= $s AND r.rhr IS NOT NULL
        ORDER BY r.date
        """,
        {"s": since},
    ).fetchall()
    rhrs = [float(r[1]) for r in rows]
    high_strain_next: list[float] = []
    rest_next: list[float] = []
    evidence: list[dict] = []
    for i in range(28, len(rows) - 1):
        baseline = sum(rhrs[i - 28:i]) / 28
        d, _rhr, strain = rows[i]
        nxt_rhr = rows[i + 1][1]
        if strain is None or nxt_rhr is None:
            continue
        delta = float(nxt_rhr) - baseline
        if float(strain) > 12:
            high_strain_next.append(delta)
            evidence.append({"date": str(d), "strain": float(strain), "next_rhr_delta": round(delta, 1)})
        elif float(strain) < 6:
            rest_next.append(delta)
    if len(high_strain_next) < 3 or len(rest_next) < 3:
        return LabFinding(q["id"], len(high_strain_next), None, "bpm", None, "insufficient",
                          f"Need ≥3 in each bucket — high strain {len(high_strain_next)} / rest {len(rest_next)}.",
                          evidence[-30:])
    diff = sum(high_strain_next) / len(high_strain_next) - sum(rest_next) / len(rest_next)
    threshold = float(q["threshold"])
    res = _welch_t(high_strain_next, rest_next)
    p = res[1] if res else None
    if diff >= threshold and (p is None or p < 0.10):
        verdict = "confirmed"
    elif diff <= 0:
        verdict = "refuted"
    else:
        verdict = "inconclusive"
    return LabFinding(
        q["id"], len(high_strain_next) + len(rest_next), round(diff, 2), "bpm", p, verdict,
        f"After high-strain days RHR averages {sum(high_strain_next)/len(high_strain_next):+.1f}bpm vs baseline; "
        f"after rest days {sum(rest_next)/len(rest_next):+.1f}bpm. Δ={diff:+.1f}bpm.",
        evidence[-60:],
    )


def _run_push_pull_imbalance(conn, q: dict) -> LabFinding:
    since = (date.today() - timedelta(days=q["window_days"])).isoformat()
    # Build weekly windows
    rows = conn.execute(
        "SELECT date, score FROM recovery WHERE date >= $s ORDER BY date",
        {"s": since},
    ).fetchall()
    if len(rows) < q["min_n"]:
        return LabFinding(q["id"], len(rows), None, "r", None, "insufficient",
                          f"Only {len(rows)} recovery days available.", [])
    # For each rolling 7d window endpoint, compute push:pull from workout_sets_dedup
    sets_rows = conn.execute(
        "SELECT day_d, exercise FROM workout_sets_dedup WHERE day_d >= $s AND is_warmup = FALSE",
        {"s": since},
    ).fetchall()
    # naive classifier
    PUSH = ("press", "push", "fly", "dip")
    PULL = ("row", "pull", "curl", "lat")
    by_day_push: dict[date, int] = {}
    by_day_pull: dict[date, int] = {}
    for d, ex in sets_rows:
        ex_low = (ex or "").lower()
        if any(k in ex_low for k in PUSH):
            by_day_push[d] = by_day_push.get(d, 0) + 1
        elif any(k in ex_low for k in PULL):
            by_day_pull[d] = by_day_pull.get(d, 0) + 1
    rec_by_day = {r[0]: float(r[1]) for r in rows if r[1] is not None}
    ratios: list[float] = []
    rec_means: list[float] = []
    evidence: list[dict] = []
    days_sorted = sorted(rec_by_day.keys())
    for end in days_sorted[7:]:
        window = [end - timedelta(days=i) for i in range(7)]
        push_sum = sum(by_day_push.get(d, 0) for d in window)
        pull_sum = sum(by_day_pull.get(d, 0) for d in window)
        if push_sum + pull_sum < 6:
            continue
        if pull_sum == 0 or push_sum == 0:
            continue
        ratio = push_sum / pull_sum
        rec_mean = sum(rec_by_day.get(d, 0) for d in window if d in rec_by_day) / max(
            1, sum(1 for d in window if d in rec_by_day)
        )
        ratios.append(ratio)
        rec_means.append(rec_mean)
        evidence.append({"window_end": str(end), "push": push_sum, "pull": pull_sum, "ratio": round(ratio, 2),
                         "recovery_avg": round(rec_mean, 1)})
    if len(ratios) < 5:
        return LabFinding(q["id"], len(ratios), None, "r", None, "insufficient",
                          f"Only {len(ratios)} 7d windows with sufficient training volume.", evidence[-30:])
    # Use |log(ratio)| as the imbalance score so a 0.5 ratio = a 2.0 ratio
    imbalance = [abs(math.log(r)) for r in ratios]
    r_corr = _pearson(imbalance, rec_means)
    if r_corr is None:
        return LabFinding(q["id"], len(ratios), None, "r", None, "inconclusive",
                          "Variance too low for correlation.", evidence[-30:])
    p = _pearson_p(r_corr, len(ratios))
    threshold = float(q["threshold"])
    sig = p is not None and p < _ALPHA
    if abs(r_corr) >= threshold and sig:
        verdict = "confirmed"  # direction='either' — magnitude in either sign
    elif abs(r_corr) >= 0.15:
        verdict = "inconclusive"
    else:
        verdict = "refuted"
    return LabFinding(
        q["id"], len(ratios), round(r_corr, 3), "r", p, verdict,
        f"Across {len(ratios)} rolling 7d windows, |log push:pull| correlates with avg recovery at r={r_corr:+.3f} (p={p:.3f}).",
        evidence[-60:],
    )


def _run_yoga_hrv_lift(conn, q: dict) -> LabFinding:
    """Yoga sessions → higher next-morning HRV vs non-yoga days."""
    since = (date.today() - timedelta(days=q["window_days"])).isoformat()
    hrv_rows = conn.execute(
        "SELECT date, hrv FROM recovery WHERE date >= $s AND hrv IS NOT NULL ORDER BY date",
        {"s": since},
    ).fetchall()
    if len(hrv_rows) < q["min_n"]:
        return LabFinding(q["id"], len(hrv_rows), None, "ms", None, "insufficient",
                          f"Only {len(hrv_rows)} HRV days.", [])
    baselines = _hrv_baseline_28d(hrv_rows)
    yoga_days = {
        r[0] for r in conn.execute(
            "SELECT date FROM cardio_sessions WHERE date >= $s AND modality ILIKE '%yoga%'",
            {"s": since},
        ).fetchall()
    }
    yoga_next, rest_next, evidence = [], [], []
    for i, (d, hrv) in enumerate(hrv_rows):
        if d not in baselines or hrv is None:
            continue
        prev = hrv_rows[i - 1][0] if i > 0 else None
        if prev is None:
            continue
        deviation = float(hrv) - baselines[d]
        entry = {"date": str(d), "hrv": float(hrv), "baseline": round(baselines[d], 1),
                 "deviation": round(deviation, 1), "yoga_prev": prev in yoga_days}
        evidence.append(entry)
        if prev in yoga_days:
            yoga_next.append(deviation)
        else:
            rest_next.append(deviation)
    if len(yoga_next) < 6 or len(rest_next) < 6:
        return LabFinding(q["id"], len(yoga_next) + len(rest_next), None, "ms", None, "insufficient",
                          f"Too few yoga ({len(yoga_next)}) or rest ({len(rest_next)}) days.", evidence)
    delta = sum(yoga_next) / len(yoga_next) - sum(rest_next) / len(rest_next)
    ttest = _welch_t(yoga_next, rest_next)
    p = ttest[1] if ttest else None
    threshold = float(q["threshold"])
    if delta >= threshold and (p is None or p < 0.1):
        verdict = "confirmed"
    elif delta <= -threshold:
        verdict = "refuted"
    elif abs(delta) >= threshold * 0.5:
        verdict = "inconclusive"
    else:
        verdict = "refuted"
    return LabFinding(
        q["id"], len(yoga_next) + len(rest_next), round(delta, 2), "ms", p, verdict,
        f"After yoga ({len(yoga_next)} days): next-AM HRV deviation {delta:+.1f}ms vs rest days. Δ={delta:+.1f}ms.",
        evidence[-60:],
    )


def _run_consecutive_training_recovery_drop(conn, q: dict) -> LabFinding:
    """Two+ consecutive strength training days → lower next-day recovery."""
    since = (date.today() - timedelta(days=q["window_days"])).isoformat()
    rec_rows = conn.execute(
        "SELECT date, score FROM recovery WHERE date >= $s AND score IS NOT NULL ORDER BY date",
        {"s": since},
    ).fetchall()
    if len(rec_rows) < q["min_n"]:
        return LabFinding(q["id"], len(rec_rows), None, "pts", None, "insufficient",
                          f"Only {len(rec_rows)} recovery days.", [])
    training_days = {
        r[0] for r in conn.execute(
            "SELECT DISTINCT day_d FROM workout_sets_dedup WHERE day_d >= $s AND is_warmup = FALSE",
            {"s": since},
        ).fetchall()
    }
    rec_by_day = {r[0]: float(r[1]) for r in rec_rows}
    consec_next, rest_next, evidence = [], [], []
    days_sorted = sorted(rec_by_day.keys())
    for i, d in enumerate(days_sorted):
        if i < 2:
            continue
        prev1, prev2 = days_sorted[i - 1], days_sorted[i - 2]
        both_trained = prev1 in training_days and prev2 in training_days
        entry = {"date": str(d), "recovery": rec_by_day[d],
                 "consecutive_training": both_trained}
        evidence.append(entry)
        if both_trained:
            consec_next.append(rec_by_day[d])
        elif prev1 not in training_days:
            rest_next.append(rec_by_day[d])
    if len(consec_next) < 6 or len(rest_next) < 6:
        return LabFinding(q["id"], len(consec_next) + len(rest_next), None, "pts", None, "insufficient",
                          f"Too few consecutive ({len(consec_next)}) or rest ({len(rest_next)}) observations.", evidence)
    delta = sum(consec_next) / len(consec_next) - sum(rest_next) / len(rest_next)
    ttest = _welch_t(consec_next, rest_next)
    p = ttest[1] if ttest else None
    threshold = float(q["threshold"])
    if delta <= -threshold and (p is None or p < 0.1):
        verdict = "confirmed"
    elif delta >= threshold:
        verdict = "refuted"
    elif abs(delta) >= threshold * 0.5:
        verdict = "inconclusive"
    else:
        verdict = "refuted"
    return LabFinding(
        q["id"], len(consec_next) + len(rest_next), round(delta, 2), "pts", p, verdict,
        f"After 2+ consecutive training days ({len(consec_next)} obs): recovery {delta:+.1f}pts vs post-rest days.",
        evidence[-60:],
    )


def _run_two_pb_3d_hrv_drop(conn, q: dict) -> LabFinding:
    """2+ pickleball sessions in any 3-day window → more HRV depression than 1 session."""
    since = (date.today() - timedelta(days=q["window_days"])).isoformat()
    hrv_rows = conn.execute(
        "SELECT date, hrv FROM recovery WHERE date >= $s AND hrv IS NOT NULL ORDER BY date",
        {"s": since},
    ).fetchall()
    if len(hrv_rows) < q["min_n"]:
        return LabFinding(q["id"], len(hrv_rows), None, "ms", None, "insufficient",
                          f"Only {len(hrv_rows)} HRV days.", [])
    baselines = _hrv_baseline_28d(hrv_rows)
    pb_days = {
        r[0] for r in conn.execute(
            "SELECT date FROM cardio_sessions WHERE date >= $s AND modality ILIKE '%pickleball%'",
            {"s": since},
        ).fetchall()
    }
    multi_next, single_next, evidence = [], [], []
    hrv_by_day = {r[0]: float(r[1]) for r in hrv_rows}
    for d, hrv in hrv_rows:
        if d not in baselines or hrv is None:
            continue
        window = [d - timedelta(days=i) for i in range(1, 4)]
        pb_count = sum(1 for w in window if w in pb_days)
        if pb_count == 0:
            continue
        deviation = float(hrv) - baselines[d]
        entry = {"date": str(d), "deviation": round(deviation, 1), "pb_in_3d": pb_count}
        evidence.append(entry)
        if pb_count >= 2:
            multi_next.append(deviation)
        else:
            single_next.append(deviation)
    if len(multi_next) < 5 or len(single_next) < 5:
        return LabFinding(q["id"], len(multi_next) + len(single_next), None, "ms", None, "insufficient",
                          f"Too few multi ({len(multi_next)}) or single ({len(single_next)}) pickleball windows.", evidence)
    delta = sum(multi_next) / len(multi_next) - sum(single_next) / len(single_next)
    ttest = _welch_t(multi_next, single_next)
    p = ttest[1] if ttest else None
    threshold = float(q["threshold"])
    if delta <= -threshold and (p is None or p < 0.15):
        verdict = "confirmed"
    elif delta >= threshold:
        verdict = "refuted"
    elif abs(delta) >= threshold * 0.5:
        verdict = "inconclusive"
    else:
        verdict = "refuted"
    return LabFinding(
        q["id"], len(multi_next) + len(single_next), round(delta, 2), "ms", p, verdict,
        f"After 2+ pickleball in 3d ({len(multi_next)} obs): HRV deviation {delta:+.1f}ms vs single-session windows.",
        evidence[-60:],
    )


def _run_weekly_volume_spike_recovery(conn, q: dict) -> LabFinding:
    """Weeks where set count > 1.5× 4-week avg correlate with lower avg recovery."""
    since = (date.today() - timedelta(days=q["window_days"])).isoformat()
    rec_rows = conn.execute(
        "SELECT date, score FROM recovery WHERE date >= $s AND score IS NOT NULL ORDER BY date",
        {"s": since},
    ).fetchall()
    if len(rec_rows) < q["min_n"]:
        return LabFinding(q["id"], len(rec_rows), None, "r", None, "insufficient",
                          f"Only {len(rec_rows)} recovery days.", [])
    set_rows = conn.execute(
        "SELECT day_d FROM workout_sets_dedup WHERE day_d >= $s AND is_warmup = FALSE",
        {"s": since},
    ).fetchall()
    # Count sets per week (Monday-based ISO week)
    sets_by_week: dict[str, int] = {}
    for (d,) in set_rows:
        wk = d.strftime("%G-W%V")
        sets_by_week[wk] = sets_by_week.get(wk, 0) + 1
    rec_by_day = {r[0]: float(r[1]) for r in rec_rows}
    # Weekly recovery average
    rec_by_week: dict[str, list[float]] = {}
    for d, score in rec_by_day.items():
        wk = d.strftime("%G-W%V")
        rec_by_week.setdefault(wk, []).append(score)
    weeks = sorted(set(sets_by_week) & set(rec_by_week))
    if len(weeks) < 8:
        return LabFinding(q["id"], len(weeks), None, "r", None, "insufficient",
                          f"Only {len(weeks)} weeks with both training and recovery data.", [])
    # For each week, check if volume > 1.5× prior 4-week average
    spike_rec, normal_rec, evidence = [], [], []
    for i, wk in enumerate(weeks[4:], start=4):
        prior_4 = [sets_by_week.get(weeks[i - j - 1], 0) for j in range(4)]
        prior_avg = sum(prior_4) / 4
        this_sets = sets_by_week.get(wk, 0)
        avg_rec = sum(rec_by_week[wk]) / len(rec_by_week[wk])
        is_spike = prior_avg > 0 and this_sets > 1.5 * prior_avg
        entry = {"week": wk, "sets": this_sets, "prior_avg": round(prior_avg, 1),
                 "spike": is_spike, "avg_recovery": round(avg_rec, 1)}
        evidence.append(entry)
        if is_spike:
            spike_rec.append(avg_rec)
        else:
            normal_rec.append(avg_rec)
    if len(spike_rec) < 3 or len(normal_rec) < 3:
        return LabFinding(q["id"], len(evidence), None, "r", None, "insufficient",
                          f"Too few spike ({len(spike_rec)}) or normal ({len(normal_rec)}) weeks.", evidence)
    # Correlation: spike weeks → recovery
    xs = [1.0 if e["spike"] else 0.0 for e in evidence]
    ys = [e["avg_recovery"] for e in evidence]
    r_corr = _pearson(xs, ys) or 0.0
    p = _pearson_p(r_corr, len(xs))
    threshold = float(q["threshold"])
    delta = (sum(spike_rec) / len(spike_rec)) - (sum(normal_rec) / len(normal_rec))
    sig = p is not None and p < _ALPHA
    if r_corr <= -threshold and sig:
        verdict = "confirmed"
    elif r_corr >= threshold:
        verdict = "refuted"
    elif abs(r_corr) >= 0.15:
        verdict = "inconclusive"
    else:
        verdict = "refuted"
    p_str = f", p={p:.3f}" if p is not None else ""
    return LabFinding(
        q["id"], len(evidence), round(r_corr, 3), "r", p, verdict,
        f"Volume-spike weeks ({len(spike_rec)}): avg recovery {sum(spike_rec)/len(spike_rec):.0f}; "
        f"normal weeks ({len(normal_rec)}): {sum(normal_rec)/len(normal_rec):.0f}. Δ={delta:+.1f}pts, r={r_corr:+.3f}{p_str}.",
        evidence,
    )


def _run_rest_day_hrv_rebound(conn, q: dict) -> LabFinding:
    """Full rest days (no Hevy, no cardio) → higher next-morning HRV."""
    since = (date.today() - timedelta(days=q["window_days"])).isoformat()
    hrv_rows = conn.execute(
        "SELECT date, hrv FROM recovery WHERE date >= $s AND hrv IS NOT NULL ORDER BY date",
        {"s": since},
    ).fetchall()
    if len(hrv_rows) < q["min_n"]:
        return LabFinding(q["id"], len(hrv_rows), None, "ms", None, "insufficient",
                          f"Only {len(hrv_rows)} HRV days.", [])
    baselines = _hrv_baseline_28d(hrv_rows)
    training_days = {
        r[0] for r in conn.execute(
            "SELECT DISTINCT day_d FROM workout_sets_dedup WHERE day_d >= $s AND is_warmup = FALSE",
            {"s": since},
        ).fetchall()
    }
    cardio_days = {
        r[0] for r in conn.execute(
            "SELECT DISTINCT date FROM cardio_sessions WHERE date >= $s",
            {"s": since},
        ).fetchall()
    }
    active_days = training_days | cardio_days
    rest_next, active_next, evidence = [], [], []
    hrv_list = list(hrv_rows)
    for i in range(1, len(hrv_list)):
        d, hrv = hrv_list[i]
        prev = hrv_list[i - 1][0]
        if d not in baselines or hrv is None:
            continue
        deviation = float(hrv) - baselines[d]
        is_rest_prev = prev not in active_days
        entry = {"date": str(d), "deviation": round(deviation, 1), "prev_was_rest": is_rest_prev}
        evidence.append(entry)
        if is_rest_prev:
            rest_next.append(deviation)
        else:
            active_next.append(deviation)
    if len(rest_next) < 6 or len(active_next) < 6:
        return LabFinding(q["id"], len(rest_next) + len(active_next), None, "ms", None, "insufficient",
                          f"Too few rest ({len(rest_next)}) or active ({len(active_next)}) days.", evidence)
    delta = sum(rest_next) / len(rest_next) - sum(active_next) / len(active_next)
    ttest = _welch_t(rest_next, active_next)
    p = ttest[1] if ttest else None
    threshold = float(q["threshold"])
    if delta >= threshold and (p is None or p < 0.1):
        verdict = "confirmed"
    elif delta <= -threshold:
        verdict = "refuted"
    elif abs(delta) >= threshold * 0.5:
        verdict = "inconclusive"
    else:
        verdict = "refuted"
    return LabFinding(
        q["id"], len(rest_next) + len(active_next), round(delta, 2), "ms", p, verdict,
        f"After rest days ({len(rest_next)} obs): HRV deviation {delta:+.1f}ms vs after active days.",
        evidence[-60:],
    )


def _run_energy_checkin_hrv_correlation(conn, q: dict) -> LabFinding:
    """Self-reported energy (1–10) correlates with same-morning HRV."""
    since = (date.today() - timedelta(days=q["window_days"])).isoformat()
    rows = conn.execute(
        """
        SELECT r.date, r.hrv, c.energy_1_10
        FROM recovery r
        JOIN daily_checkin c ON c.date = r.date
        WHERE r.date >= $s AND r.hrv IS NOT NULL AND c.energy_1_10 IS NOT NULL
        ORDER BY r.date
        """,
        {"s": since},
    ).fetchall()
    if len(rows) < q["min_n"]:
        return LabFinding(q["id"], len(rows), None, "r", None, "insufficient",
                          f"Only {len(rows)} days with both HRV and energy check-in.", [])
    xs = [float(r[2]) for r in rows]  # energy
    ys = [float(r[1]) for r in rows]  # hrv
    r_corr = _pearson(xs, ys)
    if r_corr is None:
        return LabFinding(q["id"], len(rows), None, "r", None, "inconclusive",
                          "Variance too low for correlation.", [])
    evidence = [{"date": str(r[0]), "hrv": float(r[1]), "energy": int(r[2])} for r in rows]
    p = _pearson_p(r_corr, len(rows))
    threshold = float(q["threshold"])
    sig = p is not None and p < _ALPHA
    if r_corr >= threshold and sig:
        verdict = "confirmed"
    elif r_corr <= -threshold:
        verdict = "refuted"
    elif abs(r_corr) >= 0.15:
        verdict = "inconclusive"
    else:
        verdict = "refuted"
    p_str = f", p={p:.3f}" if p is not None else ""
    return LabFinding(
        q["id"], len(rows), round(r_corr, 3), "r", p, verdict,
        f"Energy check-in correlates with same-morning HRV at r={r_corr:+.3f}{p_str} across {len(rows)} days.",
        evidence[-60:],
    )


def _run_lift_volume_hrv_drop(conn, q: dict) -> LabFinding:
    """Higher strength-training tonnage on a day → lower next-morning HRV deviation."""
    since = (date.today() - timedelta(days=q["window_days"])).isoformat()
    hrv_rows = conn.execute(
        "SELECT date, hrv FROM recovery WHERE date >= $s AND hrv IS NOT NULL ORDER BY date",
        {"s": since},
    ).fetchall()
    if len(hrv_rows) < q["min_n"]:
        return LabFinding(q["id"], len(hrv_rows), None, "r", None, "insufficient",
                          f"Only {len(hrv_rows)} HRV days.", [])
    baselines = _hrv_baseline_28d(hrv_rows)
    tonnage = {
        r[0]: float(r[1])
        for r in conn.execute(
            """
            SELECT day_d, SUM(weight_kg * reps) AS tonnage_kg
            FROM workout_sets_dedup
            WHERE day_d >= $s AND is_warmup = FALSE AND weight_kg > 0 AND reps > 0
            GROUP BY day_d
            """,
            {"s": since},
        ).fetchall()
        if r[1] is not None
    }
    xs, ys, evidence = [], [], []
    for d, hrv in hrv_rows:
        if d not in baselines or hrv is None:
            continue
        prev = d - timedelta(days=1)
        if prev not in tonnage:
            continue
        dev = float(hrv) - baselines[d]
        xs.append(tonnage[prev])
        ys.append(dev)
        evidence.append({"date": str(d), "prev_day_tonnage_kg": round(tonnage[prev], 1),
                         "hrv": float(hrv), "deviation": round(dev, 1)})
    if len(xs) < q["min_n"]:
        return LabFinding(q["id"], len(xs), None, "r", None, "insufficient",
                          f"Only {len(xs)} mornings following a logged lift.", evidence)
    r_corr = _pearson(xs, ys)
    if r_corr is None:
        return LabFinding(q["id"], len(xs), None, "r", None, "inconclusive",
                          "Variance too low for correlation.", evidence)
    p = _pearson_p(r_corr, len(xs))
    threshold = float(q["threshold"])
    sig = p is not None and p < _ALPHA
    if r_corr <= -threshold and sig:
        verdict = "confirmed"  # heavier tonnage → lower next-AM HRV
    elif r_corr >= threshold:
        verdict = "refuted"
    elif abs(r_corr) >= threshold * 0.5:
        verdict = "inconclusive"
    else:
        verdict = "refuted"
    p_str = f", p={p:.3f}" if p is not None else ""
    return LabFinding(
        q["id"], len(xs), round(r_corr, 3), "r", p, verdict,
        f"Across {len(xs)} mornings after a lift, prior-day tonnage vs next-AM HRV deviation r={r_corr:+.3f}{p_str}.",
        evidence[-60:],
    )


def _run_rhr_trend_hrv_drop(conn, q: dict) -> LabFinding:
    """Rising 7d RHR trend (≥2 bpm) predicts HRV below 28d mean within 3 days."""
    since = (date.today() - timedelta(days=q["window_days"])).isoformat()
    rows = conn.execute(
        "SELECT date, hrv, rhr FROM recovery WHERE date >= $s AND hrv IS NOT NULL AND rhr IS NOT NULL ORDER BY date",
        {"s": since},
    ).fetchall()
    if len(rows) < q["min_n"]:
        return LabFinding(q["id"], len(rows), None, "rate", None, "insufficient",
                          f"Only {len(rows)} days with both HRV and RHR.", [])
    baselines = _hrv_baseline_28d(rows)
    rhr_by_day = {r[0]: int(r[2]) for r in rows}
    # rows are (date, hrv, rhr) 3-tuples — dict(rows) would raise. Key date→hrv
    # explicitly, and hoist out of the inner loop.
    hrv_by_day = {r[0]: r[1] for r in rows}
    days_sorted = [r[0] for r in rows]
    triggers, trigger_hits, total_triggers, evidence = 0, 0, 0, []
    for i, d in enumerate(days_sorted):
        if i < 7:
            continue
        prior_7 = [rhr_by_day[days_sorted[i - j - 1]] for j in range(7) if days_sorted[i - j - 1] in rhr_by_day]
        if len(prior_7) < 5:
            continue
        avg_prior_7 = sum(prior_7) / len(prior_7)
        current_rhr = rhr_by_day.get(d)
        if current_rhr is None:
            continue
        # Look back 7 days' average for prior week
        prior_14_7 = [rhr_by_day[days_sorted[i - j - 8]] for j in range(7)
                      if i - j - 8 >= 0 and days_sorted[i - j - 8] in rhr_by_day]
        if len(prior_14_7) < 5:
            continue
        avg_prior_14_7 = sum(prior_14_7) / len(prior_14_7)
        rhr_trend = avg_prior_7 - avg_prior_14_7
        if rhr_trend < 2.0:
            continue
        # Rising trend — check HRV over next 3 days
        total_triggers += 1
        hit = False
        for j in range(1, 4):
            if i + j >= len(days_sorted):
                break
            future_day = days_sorted[i + j]
            future_hrv = hrv_by_day.get(future_day)
            future_baseline = baselines.get(future_day)
            if future_hrv and future_baseline and float(future_hrv) < future_baseline:
                hit = True
                break
        evidence.append({"trigger_date": str(d), "rhr_trend": round(rhr_trend, 1), "hrv_drop_within_3d": hit})
        if hit:
            trigger_hits += 1
    if total_triggers < q["min_n"]:
        return LabFinding(q["id"], total_triggers, None, "rate", None, "insufficient",
                          f"Only {total_triggers} rising-RHR-trend events.", evidence)
    rate = trigger_hits / total_triggers if total_triggers > 0 else 0.0
    threshold = float(q["threshold"])
    if rate >= threshold:
        verdict = "confirmed"
    elif rate < 0.2:
        verdict = "refuted"
    else:
        verdict = "inconclusive"
    return LabFinding(
        q["id"], total_triggers, round(rate, 3), "rate", None, verdict,
        f"{trigger_hits}/{total_triggers} rising-RHR events were followed by HRV below baseline within 3 days "
        f"({rate:.0%} hit rate).",
        evidence[-60:],
    )


def _run_sleep_quality_checkin_hrv(conn, q: dict) -> LabFinding:
    """Self-reported sleep quality ≤5/10 → next-morning HRV below 28d mean."""
    since = (date.today() - timedelta(days=q["window_days"])).isoformat()
    rows = conn.execute(
        """
        SELECT r.date, r.hrv, c.sleep_quality_1_10
        FROM recovery r
        JOIN daily_checkin c ON c.date = r.date
        WHERE r.date >= $s AND r.hrv IS NOT NULL AND c.sleep_quality_1_10 IS NOT NULL
        ORDER BY r.date
        """,
        {"s": since},
    ).fetchall()
    if len(rows) < q["min_n"]:
        return LabFinding(q["id"], len(rows), None, "ms", None, "insufficient",
                          f"Only {len(rows)} days with both HRV and sleep quality check-in.", [])
    baselines = _hrv_baseline_28d(rows)
    low_qual, high_qual, evidence = [], [], []
    for d, hrv, sq in rows:
        if d not in baselines or hrv is None:
            continue
        deviation = float(hrv) - baselines[d]
        entry = {"date": str(d), "sleep_quality": int(sq), "hrv_deviation": round(deviation, 1)}
        evidence.append(entry)
        if int(sq) <= 5:
            low_qual.append(deviation)
        else:
            high_qual.append(deviation)
    if len(low_qual) < 6 or len(high_qual) < 6:
        return LabFinding(q["id"], len(low_qual) + len(high_qual), None, "ms", None, "insufficient",
                          f"Too few low ({len(low_qual)}) or high ({len(high_qual)}) quality nights.", evidence)
    delta = sum(low_qual) / len(low_qual) - sum(high_qual) / len(high_qual)
    ttest = _welch_t(low_qual, high_qual)
    p = ttest[1] if ttest else None
    threshold = float(q["threshold"])
    if delta <= -threshold and (p is None or p < 0.1):
        verdict = "confirmed"
    elif delta >= threshold:
        verdict = "refuted"
    elif abs(delta) >= threshold * 0.5:
        verdict = "inconclusive"
    else:
        verdict = "refuted"
    return LabFinding(
        q["id"], len(low_qual) + len(high_qual), round(delta, 2), "ms", p, verdict,
        f"Low sleep quality nights ≤5 ({len(low_qual)} obs): HRV deviation {delta:+.1f}ms vs higher quality nights.",
        evidence[-60:],
    )


# ── Rotation ──────────────────────────────────────────────────────────────────

_STABLE_RUNS_REQUIRED = 3   # consecutive identical verdict to retire
_STABLE_N_MULTIPLIER = 1.5  # n must be >= min_n * this


def rotate_if_stable(conn) -> list[str]:
    """Retire questions with stable definitive verdicts; promote next queued.

    Returns list of question IDs that were retired this call.
    """
    enabled = conn.execute(
        "SELECT id, min_n FROM lab_questions WHERE enabled = TRUE AND retired_at IS NULL"
    ).fetchall()
    retired_ids: list[str] = []
    for qid, min_n in enabled:
        recent = conn.execute(
            """
            SELECT verdict, n FROM lab_findings
            WHERE question_id = $qid
            ORDER BY run_at DESC
            LIMIT $k
            """,
            {"qid": qid, "k": _STABLE_RUNS_REQUIRED},
        ).fetchall()
        if len(recent) < _STABLE_RUNS_REQUIRED:
            continue
        verdicts = [r[0] for r in recent]
        latest_n = recent[0][1] or 0
        definitive = all(v in ("confirmed", "refuted") for v in verdicts)
        all_same = len(set(verdicts)) == 1
        enough_n = latest_n >= int(min_n or 0) * _STABLE_N_MULTIPLIER
        if definitive and all_same and enough_n:
            conn.execute(
                "UPDATE lab_questions SET enabled = FALSE, retired_at = now() WHERE id = $qid",
                {"qid": qid},
            )
            log.info("lab: retired question %s (verdict=%s, n=%d)", qid, verdicts[0], latest_n)
            retired_ids.append(qid)
            _promote_next(conn)
    return retired_ids


def _promote_next(conn) -> None:
    """Enable the lowest-queued_order bank question that has a registered runner."""
    row = conn.execute(
        """
        SELECT id FROM lab_questions
        WHERE enabled = FALSE AND retired_at IS NULL AND queued_order IS NOT NULL
        ORDER BY queued_order ASC
        LIMIT 1
        """
    ).fetchone()
    if row is None:
        log.warning("lab: bank exhausted — no queued questions left to promote")
        return
    next_id = row[0]
    if next_id not in _RUNNERS:
        log.warning("lab: queued question %s has no runner — skipping", next_id)
        return
    conn.execute(
        "UPDATE lab_questions SET enabled = TRUE, queued_order = NULL WHERE id = $qid",
        {"qid": next_id},
    )
    log.info("lab: promoted question %s from bank", next_id)


_RUNNERS = {
    # Original six
    "sleep_short_hrv_drop": _run_sleep_short_hrv_drop,
    "long_sleep_hrv_lift": _run_long_sleep_hrv_lift,
    "pickleball_next_morning_hrv": _run_pickleball_next_morning,
    "skin_temp_illness_alarm": _run_skin_temp_illness_alarm,
    "strain_high_rhr_next": _run_strain_high_rhr_next,
    "push_pull_imbalance_recovery": _run_push_pull_imbalance,
    # Bank (runners registered now; questions activate on promotion)
    "yoga_hrv_lift": _run_yoga_hrv_lift,
    "consecutive_training_recovery_drop": _run_consecutive_training_recovery_drop,
    "two_pb_3d_hrv_drop": _run_two_pb_3d_hrv_drop,
    "weekly_volume_spike_recovery": _run_weekly_volume_spike_recovery,
    "rest_day_hrv_rebound": _run_rest_day_hrv_rebound,
    "energy_checkin_hrv_correlation": _run_energy_checkin_hrv_correlation,
    "rhr_trend_hrv_drop": _run_rhr_trend_hrv_drop,
    "sleep_quality_checkin_hrv": _run_sleep_quality_checkin_hrv,
    "lift_volume_hrv_drop": _run_lift_volume_hrv_drop,
}


def _apply_fdr(findings: list[LabFinding], alpha: float = _ALPHA) -> None:
    """Benjamini–Hochberg correction across the whole catalogue, in place.

    The catalogue runs ~15 hypotheses against one noisy dataset every cycle.
    Without correction, at α=0.10 we'd expect false positives by chance alone.
    BH controls the false-discovery rate: a finding can only stay CONFIRMED if
    its p-value clears the step-up critical value p_(k) ≤ (k/m)·α. Confirmed
    findings that don't survive are downgraded to INCONCLUSIVE so the user isn't
    told a chance correlation is real.
    """
    indexed = [(i, f.p_value) for i, f in enumerate(findings) if f.p_value is not None]
    m = len(indexed)
    if m == 0:
        return
    ordered = sorted(indexed, key=lambda t: t[1])
    max_k = 0
    for rank, (_, p) in enumerate(ordered, start=1):
        if p <= (rank / m) * alpha:
            max_k = rank
    crit_p = ordered[max_k - 1][1] if max_k > 0 else -1.0
    for f in findings:
        if f.verdict == "confirmed" and f.p_value is not None and f.p_value > crit_p:
            f.verdict = "inconclusive"
            f.summary += (
                " · did not survive Benjamini–Hochberg correction across "
                f"{m} simultaneous hypotheses — treat as suggestive, not confirmed."
            )


def run_all(conn) -> list[LabFinding]:
    qrows = conn.execute(
        "SELECT id, title, hypothesis, exposure, outcome, test_type, window_days, "
        "       min_n, threshold, direction, vault_ref "
        "FROM lab_questions WHERE enabled = TRUE"
    ).fetchall()
    findings: list[LabFinding] = []
    for q in qrows:
        qd = {
            "id": q[0], "title": q[1], "hypothesis": q[2], "exposure": q[3],
            "outcome": q[4], "test_type": q[5], "window_days": int(q[6]),
            "min_n": int(q[7]), "threshold": q[8], "direction": q[9],
            "vault_ref": q[10],
        }
        runner = _RUNNERS.get(qd["id"])
        if runner is None:
            continue
        try:
            findings.append(runner(conn, qd))
        except Exception as exc:  # noqa: BLE001
            log.exception("lab runner failed: %s", qd["id"])
            findings.append(LabFinding(
                qd["id"], 0, None, "", None, "error",
                f"runner raised {type(exc).__name__}: {exc} — hypothesis NOT tested.", [],
            ))
    _apply_fdr(findings)
    return findings


def persist(conn, findings: list[LabFinding]) -> None:
    for f in findings:
        conn.execute(
            """
            INSERT INTO lab_findings
                (id, question_id, run_at, n, effect_size, effect_unit, p_value, verdict, summary, evidence)
            VALUES ($id, $qid, now(), $n, $es, $eu, $p, $v, $s, $ev)
            """,
            {
                "id": str(uuid.uuid4()),
                "qid": f.question_id,
                "n": f.n,
                "es": f.effect_size,
                "eu": f.effect_unit,
                "p": f.p_value,
                "v": f.verdict,
                "s": f.summary,
                "ev": json.dumps(f.evidence),
            },
        )
