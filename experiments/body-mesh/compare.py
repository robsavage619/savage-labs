"""Score photo-derived girths against tape: absolute error, and whether changes agree."""

from __future__ import annotations

from collections import defaultdict
from datetime import date

SITES = ("waist", "chest", "thigh", "hip")


def compare(tape: list[dict], photos: list[dict], window_days: int = 3) -> list[dict]:
    """Pair each photo session with the nearest tape reading per site and score each model.

    Args:
        tape: Rows of {"date", "site", "cm"}.
        photos: Rows of {"date", "model", <site>: cm, ...}, one per session and model.
        window_days: Largest gap between a photo session and the tape reading it is
            scored against.

    Returns:
        One row per (model, site) with ``pairs``, ``bias_cm`` (photo minus tape, mean),
        ``mae_cm``, and, from two pairs on, ``change_mae_cm`` (how far the photo's
        session-to-session change is from the tape's) and ``same_direction``
        (count of changes where both moved the same way, out of ``changes``).
    """
    by_site: dict[str, list[tuple[date, float]]] = defaultdict(list)
    for r in tape:
        by_site[r["site"]].append((date.fromisoformat(r["date"]), r["cm"]))

    pairs: dict[tuple[str, str], list[tuple[date, float, float]]] = defaultdict(list)
    for p in photos:
        d = date.fromisoformat(p["date"])
        for site in SITES:
            if p.get(site) is None or not by_site[site]:
                continue
            td, cm = min(by_site[site], key=lambda t: abs((t[0] - d).days))
            if abs((td - d).days) <= window_days:
                pairs[(p["model"], site)].append((d, p[site], cm))

    out = []
    for (model, site), rows in sorted(pairs.items()):
        rows.sort()
        errs = [ph - tp for _, ph, tp in rows]
        row = {
            "model": model,
            "site": site,
            "pairs": len(rows),
            "bias_cm": round(sum(errs) / len(errs), 1),
            "mae_cm": round(sum(abs(e) for e in errs) / len(errs), 1),
        }
        steps = list(zip(rows, rows[1:], strict=False))
        if steps:
            dp = [b[1] - a[1] for a, b in steps]
            dt = [b[2] - a[2] for a, b in steps]
            row["changes"] = len(steps)
            row["change_mae_cm"] = round(
                sum(abs(p - t) for p, t in zip(dp, dt, strict=True)) / len(steps), 1
            )
            row["same_direction"] = sum((p > 0) == (t > 0) for p, t in zip(dp, dt, strict=True))
        out.append(row)
    return out


if __name__ == "__main__":
    tape_rows = [
        {"date": "2026-12-01", "site": "waist", "cm": 110.0},
        {"date": "2027-01-01", "site": "waist", "cm": 108.0},
        {"date": "2027-02-01", "site": "waist", "cm": 107.0},
        {"date": "2027-02-01", "site": "chest", "cm": 120.0},
    ]
    photo_rows = [
        {"date": "2026-12-02", "model": "m", "waist": 112.0, "chest": None},
        {"date": "2027-01-03", "model": "m", "waist": 111.0},
        {"date": "2027-02-01", "model": "m", "waist": 111.5, "chest": 118.0},
        {"date": "2027-03-15", "model": "m", "waist": 99.0},  # no tape within 3 days: unscored
    ]
    got = {(r["model"], r["site"]): r for r in compare(tape_rows, photo_rows)}
    waist = got[("m", "waist")]
    assert waist["pairs"] == 3 and waist["bias_cm"] == 3.2 and waist["mae_cm"] == 3.2, waist
    # Tape fell 2 then 1; photo fell 1 then rose 0.5: change errors 1.0 and 1.5.
    assert (
        waist["changes"] == 2 and waist["change_mae_cm"] == 1.2 and waist["same_direction"] == 1
    ), waist
    assert got[("m", "chest")] == {
        "model": "m",
        "site": "chest",
        "pairs": 1,
        "bias_cm": -2.0,
        "mae_cm": 2.0,
    }
    print("ok")
