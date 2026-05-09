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


@dataclass
class LabFinding:
    question_id: str
    n: int
    effect_size: float | None
    effect_unit: str
    p_value: float | None
    verdict: str  # 'confirmed' | 'refuted' | 'insufficient' | 'inconclusive'
    summary: str
    evidence: list[dict]


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
    # Welch–Satterthwaite df + survival function via erf approximation
    df = (va / len(a) + vb / len(b)) ** 2 / (
        (va / len(a)) ** 2 / (len(a) - 1) + (vb / len(b)) ** 2 / (len(b) - 1)
    )
    # Two-tailed p via t→z approximation (df > ~10 is fine)
    z = abs(t) * math.sqrt(df / (df + (t * t)))  # crude
    # Use erf-based normal cdf for the simple approximation
    p = 2 * (1 - 0.5 * (1 + math.erf(abs(t) / math.sqrt(2))))
    return t, max(min(p, 1.0), 0.0)


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


def _hrv_baseline_28d(rows: list[tuple]) -> dict[str, float]:
    """Return {date_iso: trailing_28d_mean_hrv}."""
    out: dict[str, float] = {}
    for i, r in enumerate(rows):
        prev = [float(x[2]) for x in rows[max(0, i - 28):i] if x[2] is not None]
        if len(prev) >= 7:
            out[str(r[0])] = sum(prev) / len(prev)
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
    threshold = float(q["threshold"])
    if r_corr <= -threshold:
        verdict = "confirmed"
    elif r_corr >= threshold:
        verdict = "confirmed"  # either direction was 'either'
    elif abs(r_corr) >= 0.15:
        verdict = "inconclusive"
    else:
        verdict = "refuted"
    return LabFinding(
        q["id"], len(ratios), round(r_corr, 3), "r", None, verdict,
        f"Across {len(ratios)} rolling 7d windows, |log push:pull| correlates with avg recovery at r={r_corr:+.3f}.",
        evidence[-60:],
    )


_RUNNERS = {
    "sleep_short_hrv_drop": _run_sleep_short_hrv_drop,
    "long_sleep_hrv_lift": _run_long_sleep_hrv_lift,
    "pickleball_next_morning_hrv": _run_pickleball_next_morning,
    "skin_temp_illness_alarm": _run_skin_temp_illness_alarm,
    "strain_high_rhr_next": _run_strain_high_rhr_next,
    "push_pull_imbalance_recovery": _run_push_pull_imbalance,
}


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
                qd["id"], 0, None, "", None, "inconclusive",
                f"runner error: {exc}", [],
            ))
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
