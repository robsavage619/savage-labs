"""Prediction layer: a ridge regression over every evening-before feature.

Two targets (next-morning recovery, next-session quality). Each is scored by
rolling origin: refit on days up to the origin, predict the next days, which
the fit never saw. The yardstick is the better of the zero baseline (the
training mean) and shrunk persistence (the previous value, shrunk toward that
mean). A model that does not beat that is reported as such and feeds nothing.
Each feature's contribution is its ablation: the score lost when it is dropped.

A literal neural network would memorize about a thousand days; a ridge with a
chronologically selected penalty cannot, and says so when it has no skill.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta
from statistics import mean

import duckdb
import numpy as np

from shc import research

_LAMBDAS = (1.0, 10.0, 100.0, 1000.0)
_MIN_TRAIN = 60
_MIN_COVERAGE = 0.5
_VALID_FRACTION = 0.25
_PERSIST_PAIRS = 20


@dataclass(frozen=True)
class PredictTarget:
    metric: str
    label: str
    min_scored: int


PREDICT_TARGETS: dict[str, PredictTarget] = {
    t.metric: t
    for t in [
        PredictTarget("recovery_score", "Next-morning recovery", 30),
        PredictTarget("session_quality", "Next-session quality", 15),
    ]
}


def _eligible() -> list[str]:
    """Every feature-store feature that exists by the evening before the target day.

    A calendar feature is read on the target day itself; everything else on the
    day before, whatever its timing, so no value from the target day is used.
    """
    return sorted(research.FEATURES)


def _col(feats: dict[str, dict[date, float]], name: str, days: list[date]) -> np.ndarray:
    lag = 0 if name in research._CALENDAR else 1
    s = feats[name]
    return np.array([s.get(d - timedelta(days=lag), np.nan) for d in days])


def _fit_predict(xtr: np.ndarray, ytr: np.ndarray, xte: np.ndarray, cols: list[int]) -> np.ndarray:
    """Ridge on standardized columns; the penalty is picked on the training
    window's own last quarter, so the test days never choose it."""
    if not cols:
        return np.zeros(len(xte))
    a, b = xtr[:, cols], xte[:, cols]

    def solve(x: np.ndarray, y: np.ndarray, lam: float) -> np.ndarray:
        return np.linalg.solve(x.T @ x + lam * np.eye(x.shape[1]), x.T @ y)

    cut = int(len(a) * (1 - _VALID_FRACTION))
    errs = [
        float(np.mean((ytr[cut:] - a[cut:] @ solve(a[:cut], ytr[:cut], lam)) ** 2))
        for lam in _LAMBDAS
    ]
    return b @ solve(a, ytr, _LAMBDAS[int(np.argmin(errs))])


def _persist_coef(dev: dict[date, float], origin: date) -> float:
    """Through-origin slope of each value on the previous one, up to `origin`, held to [0, 1]."""
    days = sorted(d for d in dev if d <= origin)
    xs = [dev[p] for p, _ in zip(days, days[1:], strict=False)]
    ys = [dev[n] for _, n in zip(days, days[1:], strict=False)]
    den = sum(x * x for x in xs)
    if len(xs) < _PERSIST_PAIRS or den == 0:
        return 0.0
    return min(1.0, max(0.0, sum(x * y for x, y in zip(xs, ys, strict=True)) / den))


def backtest_series(
    feats: dict[str, dict[date, float]],
    target: dict[date, float],
    today: date,
    min_scored: int,
    origins: int = 6,
    horizon: int = 30,
) -> dict:
    """Rolling-origin ridge backtest on plain series, with per-feature ablation.

    Args:
        feats: Every candidate feature as {date: value}.
        target: The target as {date: value}; may be sparse (sessions).
        today: Last day that may be scored.
        min_scored: Fewer unseen points than this and no skill is reported.
        origins: Number of cut-offs.
        horizon: Days scored after each cut-off.

    Returns:
        Skill against zero and against the better baseline, a verdict, a
        `feeds` flag that is true only when the model beats that baseline,
        per-feature ablation gains and the scored series.
    """
    names = sorted(feats)
    days_all = sorted(target)
    # per origin: (test days, actual dev, persistence dev, ridge preds for a column set)
    folds: list[dict] = []
    for k in range(origins, 0, -1):
        origin = today - timedelta(days=k * horizon)
        tr_days = [d for d in days_all if d <= origin]
        te_days = [
            d for d in days_all if origin < d <= min(today, origin + timedelta(days=horizon))
        ]
        if len(tr_days) < _MIN_TRAIN or not te_days:
            continue
        mu = mean(target[d] for d in tr_days)
        dev = {d: v - mu for d, v in target.items()}
        raw_tr = np.column_stack([_col(feats, n, tr_days) for n in names])
        raw_te = np.column_stack([_col(feats, n, te_days) for n in names])
        seen = ~np.isnan(raw_tr)
        m = np.where(seen, raw_tr, 0.0).sum(axis=0) / np.maximum(seen.sum(axis=0), 1)
        sd = np.sqrt(
            (np.where(seen, raw_tr - m, 0.0) ** 2).sum(axis=0) / np.maximum(seen.sum(axis=0), 1)
        )
        ok = (np.mean(~np.isnan(raw_tr), axis=0) >= _MIN_COVERAGE) & (sd > 0)
        z_tr = np.nan_to_num((raw_tr - m) / np.where(sd > 0, sd, 1.0))
        z_te = np.nan_to_num((raw_te - m) / np.where(sd > 0, sd, 1.0))
        phi = _persist_coef(dev, origin)
        prior = {d: i for i, d in enumerate(days_all)}
        folds.append(
            {
                "te": te_days,
                "ytr": np.array([dev[d] for d in tr_days]),
                "ztr": z_tr,
                "zte": z_te,
                "ok": [i for i in range(len(names)) if ok[i]],
                "a": [dev[d] for d in te_days],
                "q": [phi * dev[days_all[prior[d] - 1]] for d in te_days],
            }
        )

    def run(drop: str | None) -> list[float]:
        out: list[float] = []
        for f in folds:
            cols = [i for i in f["ok"] if names[i] != drop]
            out += _fit_predict(f["ztr"], f["ytr"], f["zte"], cols).tolist()
        return out

    scored_n = sum(len(f["te"]) for f in folds)
    empty = {
        "skill": None,
        "skill_best": None,
        "baseline": None,
        "call_best": None,
        "verdict": "no skill measured",
        "feeds": False,
        "n": scored_n,
        "gains": {},
        "series": [],
    }
    if scored_n < min_scored:
        return {**empty, "reason": f"Only {scored_n} scorable points; need {min_scored}."}
    a = [v for f in folds for v in f["a"]]
    q = [v for f in folds for v in f["q"]]
    full = run(None)
    mse_zero = mean(v * v for v in a)
    rows = [
        {
            "date": str(d),
            "actual": round(av, 2),
            "predicted": round(p, 2),
            "persist": round(qv, 2),
        }
        for d, av, p, qv in zip((d for f in folds for d in f["te"]), a, full, q, strict=True)
    ]
    best = research._best_baseline(rows)
    base_mse = mean((x - y) ** 2 for x, y in zip(a, q, strict=True))
    if best["baseline"] == "zero":
        base_mse = mse_zero
    mse_full = mean((x - y) ** 2 for x, y in zip(a, full, strict=True))
    gains: dict[str, float] = {}
    for n in names:
        w = run(n)
        gains[n] = (mean((x - y) ** 2 for x, y in zip(a, w, strict=True)) - mse_full) / base_mse
    call = best["call_best"]
    verdict = {
        "better": "skill",
        "tie": "no skill (a tie with the baseline)",
        "worse": "no skill (worse than the baseline)",
    }.get(call or "", "no skill measured")
    return {
        "skill": None if mse_zero == 0 else 1 - mse_full / mse_zero,
        **best,
        "verdict": verdict,
        "feeds": call == "better" and (best["skill_best"] or 0) > 0,
        "n": scored_n,
        "rmse_lab": math.sqrt(mse_full),
        "rmse_base": math.sqrt(base_mse),
        "gains": gains,
        "series": rows,
        "reason": None,
    }


def backtest(conn: duckdb.DuckDBPyConnection, metric: str, today: date | None = None) -> dict:
    """Ridge backtest of one target over the feature store, with ablation by feature.

    Args:
        conn: Open DuckDB connection.
        metric: A key of PREDICT_TARGETS.
        today: Last day that may be scored; defaults to today.

    Returns:
        :func:`backtest_series` fields plus the target label and, per feature,
        its label and ablation gain, strongest first.

    Raises:
        research.SpecError: If the metric is not a prediction target.
    """
    t = PREDICT_TARGETS.get(metric)
    if t is None:
        raise research.SpecError(
            f"no prediction target {metric!r}; one of {sorted(PREDICT_TARGETS)}"
        )
    today = today or date.today()
    target = {d: v for d, v in research.series(conn, metric).items() if d <= today}
    if not target:
        feats: dict[str, dict[date, float]] = {}
    else:
        span = (min(target) - timedelta(days=1), today)
        feats = {n: research._fill_zero(n, research.series(conn, n), span) for n in _eligible()}
    res = backtest_series(feats, target, today, t.min_scored)
    contrib = sorted(res["gains"].items(), key=lambda kv: kv[1], reverse=True)
    f = research.feature
    return {
        "metric": metric,
        "label": t.label,
        **{k: v for k, v in res.items() if k != "gains"},
        "n_features": len(feats),
        "features": [
            {"name": n, "label": getattr(f(n), "label", n), "gain": g} for n, g in contrib
        ],
    }
