"""Fit every front+side photo session, then score the girths against your tape.

Usage (from this folder, on the Apple Silicon laptop):
    uv run python run.py --stature-cm HEIGHT                  # photos and tape via the API
    uv run python run.py --stature-cm HEIGHT --from-dir DIR   # photos named DATE_front.jpg

Fits are cached in results/fits.json by session date, so a rerun only fits new sessions.
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import tempfile
from dataclasses import asdict
from datetime import date
from pathlib import Path

import cv2
import numpy as np
import requests
from PIL import Image
from shc.vision import pipeline

from compare import compare
from fit import fit

log = logging.getLogger("body-mesh")
RESULTS = Path(__file__).parent / "results" / "fits.json"
PREP_HEIGHT = 640


def _prep(rgb: np.ndarray) -> dict[str, np.ndarray]:
    mask = pipeline._silhouette_mask(rgb)
    lm = pipeline.detect_landmarks(rgb, mask)
    if lm is None:
        raise ValueError("no pose found")
    h, w = mask.shape
    k = PREP_HEIGHT / h
    small = cv2.resize(
        mask.astype(np.uint8), (round(w * k), PREP_HEIGHT), interpolation=cv2.INTER_AREA
    )
    kp = np.array([[p.x * w * k, p.y * h * k, p.visibility] for p in lm[:33]], dtype=np.float32)
    return {"mask": small > 0, "kp": kp}


def _sessions(api: str, from_dir: Path | None) -> dict[str, dict[str, np.ndarray]]:
    """Session date -> {"front": rgb, "side": rgb}, for dates that have both."""
    out: dict[str, dict[str, np.ndarray]] = {}
    if from_dir:
        for p in sorted(from_dir.glob("*_front.*")):
            day = p.name.split("_")[0]
            side = next(from_dir.glob(f"{day}_side.*"), None)
            if side:
                out[day] = {"front": pipeline.load_rgb(p), "side": pipeline.load_rgb(side)}
        return out
    photos = requests.get(f"{api}/api/progress-photos", timeout=30).json()
    days = {p["photo_date"] for p in photos if p["angle"] == "front"} & {
        p["photo_date"] for p in photos if p["angle"] == "side"
    }
    for day in sorted(days):
        out[day] = {}
        for angle in ("front", "side"):
            r = requests.get(
                f"{api}/api/progress-photos/image",
                params={"angle": angle, "date": day, "width": 2400},
                timeout=120,
            )
            r.raise_for_status()
            out[day][angle] = np.asarray(Image.open(io.BytesIO(r.content)).convert("RGB"))
    return out


def _weight_near(api: str, day: str) -> float | None:
    rows = requests.get(f"{api}/api/body/trend", timeout=30).json()
    if not rows:
        return None
    d = date.fromisoformat(day)
    best = min(rows, key=lambda r: abs((date.fromisoformat(r["date"]) - d).days))
    return best["kg"] if abs((date.fromisoformat(best["date"]) - d).days) <= 3 else None


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--stature-cm", type=float, required=True)
    ap.add_argument("--api", default="http://127.0.0.1:8000")
    ap.add_argument("--from-dir", type=Path)
    ap.add_argument("--iters", type=int, default=1200)
    a = ap.parse_args()

    fits: list[dict] = json.loads(RESULTS.read_text()) if RESULTS.exists() else []
    done = {f["date"] for f in fits}
    for day, views in _sessions(a.api, a.from_dir).items():
        if day in done:
            continue
        log.info("fitting %s", day)
        arrays = {}
        for angle, rgb in views.items():
            prepped = _prep(rgb)
            arrays[f"{angle}_mask"], arrays[f"{angle}_kp"] = prepped["mask"], prepped["kp"]
        with tempfile.TemporaryDirectory() as tmp:
            npz = Path(tmp) / "prep.npz"
            np.savez(npz, **arrays)
            fitted, mean, parts, *_ = fit(npz, "front", "side", a.stature_cm, a.iters, quiet=True)
        for model, g in (("mhr-silhouette", fitted), ("mhr-mean-shape", mean)):
            row = {"date": day, "model": model, **asdict(g)}
            fits.append({k.removesuffix("_cm"): v for k, v in row.items()})
        fits[-2]["residual_px"] = [[round(x, 1) for x in p] for p in parts]
        RESULTS.parent.mkdir(exist_ok=True)
        RESULTS.write_text(json.dumps(fits, indent=1))

    for f in fits:
        kg = _weight_near(a.api, f["date"])
        miss = f" ({(f['implied_mass_kg'] / kg - 1) * 100:+.1f}% vs scale {kg:.1f})" if kg else ""
        log.info(
            "%s %-15s waist %5.1f  chest %5.1f  hip %5.1f  thigh %5.1f cm  mass %5.1f kg%s",
            f["date"],
            f["model"],
            f["waist"],
            f["chest"],
            f["hip"],
            f["thigh"],
            f["implied_mass_kg"],
            miss,
        )

    tape = requests.get(f"{a.api}/api/body/tape/history", timeout=30)
    if tape.status_code == 404:
        log.info("this API has no /body/tape/history yet; deploy the SHC commit that adds it")
        return
    scored = compare(tape.json(), fits)
    if not scored:
        log.info("no tape reading within 3 days of a photo session; nothing to score yet")
    for row in scored:
        log.info("%s", row)


if __name__ == "__main__":
    main()
