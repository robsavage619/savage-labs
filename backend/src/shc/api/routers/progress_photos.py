"""Progress-photo body tracking — upload, trends, and grounded comparison.

Measurement is deterministic (shc.vision); change is gated by the ISAK-derived
noise floor; comparisons are corroborated against body weight. No language model
and no external calls are involved. See shc/vision/METHODOLOGY.md.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import date

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response

from shc.config import settings
from shc.db.schema import get_read_conn, write_ctx
from shc.vision.noise import classify_change
from shc.vision.overlay import change_heatmap
from shc.vision.pipeline import analyze_photo

router = APIRouter(tags=["progress-photos"])
log = logging.getLogger(__name__)

_ANGLES = {"front", "side"}
_ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".webp", ".heic"}


def _photo_dir():
    d = settings.uploads_dir / "progress"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _baseline_scale(angle: str) -> float | None:
    """Most recent passing-quality reference length for this angle, if any."""
    conn = get_read_conn()
    row = conn.execute(
        "SELECT scale_px FROM progress_photos "
        "WHERE angle = $a AND quality_pass ORDER BY photo_date DESC LIMIT 1",
        {"a": angle},
    ).fetchone()
    return float(row[0]) if row and row[0] is not None else None


@router.post("/progress-photos")
async def upload_photo(
    file: UploadFile = File(...),
    photo_date: str = Form(...),
    angle: str = Form(...),
):
    """Store a progress photo and extract scale-normalized body geometry.

    Args:
        file: Image upload.
        photo_date: ISO date the photo represents.
        angle: 'front' or 'side'.

    Returns:
        The capture-quality result and extracted measurements.
    """
    if angle not in _ANGLES:
        raise HTTPException(422, f"angle must be one of {sorted(_ANGLES)}")
    try:
        pdate = date.fromisoformat(photo_date)
    except ValueError as exc:
        raise HTTPException(422, "photo_date must be ISO format") from exc

    ext = "." + (file.filename or "x").rsplit(".", 1)[-1].lower()
    if ext not in _ALLOWED_EXT:
        raise HTTPException(422, f"unsupported file type {ext}")

    dest = _photo_dir() / f"{pdate.isoformat()}_{angle}{ext}"
    dest.write_bytes(await file.read())

    try:
        analysis = analyze_photo(dest, baseline_scale_px=_baseline_scale(angle))
    except ValueError as exc:
        dest.unlink(missing_ok=True)
        raise HTTPException(422, str(exc)) from exc
    except OSError as exc:  # includes PIL.UnidentifiedImageError
        dest.unlink(missing_ok=True)
        log.warning("could not decode uploaded image %s: %s", dest.name, exc)
        raise HTTPException(422, "could not read this image — try a JPG or PNG") from exc

    assert analysis.quality is not None
    photo_id = str(uuid.uuid4())
    rel_path = str(dest.relative_to(settings.uploads_dir))

    async with write_ctx() as conn:
        conn.execute(
            "DELETE FROM photo_measurements WHERE photo_id IN "
            "(SELECT id FROM progress_photos WHERE photo_date = $d AND angle = $a)",
            {"d": pdate, "a": angle},
        )
        conn.execute(
            "DELETE FROM progress_photos WHERE photo_date = $d AND angle = $a",
            {"d": pdate, "a": angle},
        )
        conn.execute(
            "INSERT INTO progress_photos "
            "(id, photo_date, angle, file_path, quality_pass, quality_flags, pose_conf, scale_px) "
            "VALUES ($id, $d, $a, $f, $qp, $qf, $pc, $sp)",
            {
                "id": photo_id,
                "d": pdate,
                "a": angle,
                "f": rel_path,
                "qp": analysis.quality.passed,
                "qf": json.dumps(analysis.quality.flags),
                "pc": analysis.pose_conf,
                "sp": analysis.scale_px,
            },
        )
        for metric, (value_px, value_norm) in analysis.measurements.items():
            conn.execute(
                "INSERT INTO photo_measurements (photo_id, metric, value_px, value_norm) "
                "VALUES ($id, $m, $px, $n)",
                {"id": photo_id, "m": metric, "px": value_px, "n": value_norm},
            )

    return {
        "id": photo_id,
        "photo_date": pdate.isoformat(),
        "angle": angle,
        "quality_pass": analysis.quality.passed,
        "quality_flags": analysis.quality.flags,
        "advisories": analysis.quality.advisories,
        "pose_conf": round(analysis.pose_conf, 3),
        "measurements": {k: round(v[1], 4) for k, v in analysis.measurements.items()},
    }


@router.get("/progress-photos")
async def list_photos(angle: str | None = Query(None)):
    """List stored photos with their normalized measurements (for trend charts)."""
    conn = get_read_conn()
    where = "WHERE p.angle = $a" if angle else ""
    params = {"a": angle} if angle else {}
    rows = conn.execute(
        f"SELECT p.photo_date, p.angle, p.quality_pass, p.quality_flags, "
        f"       m.metric, m.value_norm "
        f"FROM progress_photos p JOIN photo_measurements m ON m.photo_id = p.id "
        f"{where} ORDER BY p.photo_date",
        params,
    ).fetchall()

    out: dict[str, dict] = {}
    for pdate, ang, qpass, qflags, metric, val in rows:
        key = f"{pdate.isoformat()}|{ang}"
        entry = out.setdefault(
            key,
            {
                "photo_date": pdate.isoformat(),
                "angle": ang,
                "quality_pass": bool(qpass),
                "quality_flags": json.loads(qflags) if qflags else [],
                "measurements": {},
            },
        )
        entry["measurements"][metric] = round(val, 4)
    return list(out.values())


def _measurements_on(angle: str, d: date) -> dict[str, float]:
    conn = get_read_conn()
    rows = conn.execute(
        "SELECT m.metric, m.value_norm FROM photo_measurements m "
        "JOIN progress_photos p ON p.id = m.photo_id "
        "WHERE p.photo_date = $d AND p.angle = $a",
        {"d": d, "a": angle},
    ).fetchall()
    return {metric: float(v) for metric, v in rows}


def _weight_near(d: date) -> float | None:
    conn = get_read_conn()
    row = conn.execute(
        "SELECT body_weight_kg FROM daily_checkin "
        "WHERE body_weight_kg IS NOT NULL ORDER BY abs(date - $d) LIMIT 1",
        {"d": d},
    ).fetchone()
    return float(row[0]) if row and row[0] is not None else None


@router.get("/progress-photos/compare")
async def compare(
    angle: str = Query(...),
    before: str = Query(...),
    after: str = Query(...),
):
    """Compare two dates, gating every change by the ISAK noise floor.

    Metrics whose change sits inside the measurement-error band are reported as
    'no detectable change'. A direction conflict between the waist signal and
    body-weight trend is surfaced, never averaged.
    """
    try:
        d0, d1 = date.fromisoformat(before), date.fromisoformat(after)
    except ValueError as exc:
        raise HTTPException(422, "before/after must be ISO dates") from exc

    m0, m1 = _measurements_on(angle, d0), _measurements_on(angle, d1)
    if not m0 or not m1:
        raise HTTPException(404, "measurements missing for one or both dates")

    verdicts = []
    for metric in sorted(set(m0) & set(m1)):
        v = classify_change(metric, m0[metric], m1[metric])
        verdicts.append(
            {
                "metric": metric,
                "detectable": v.detectable,
                "direction": v.direction,
                "pct_change": round(v.pct * 100, 2) if v.detectable else None,
            }
        )

    # Corroboration: waist down ("leaner") while weight up is a conflict.
    w0, w1 = _weight_near(d0), _weight_near(d1)
    conflict = None
    waist = next((x for x in verdicts if x["metric"] == "waist_to_shoulder"), None)
    if waist and waist["detectable"] and w0 is not None and w1 is not None:
        weight_delta = w1 - w0
        if waist["direction"] == "down" and weight_delta > 0.5:
            conflict = (
                f"Waist-to-shoulder fell but body weight rose {weight_delta:.1f} kg — "
                "signals disagree; do not interpret as fat loss without more data."
            )
        elif waist["direction"] == "up" and weight_delta < -0.5:
            conflict = (
                f"Waist-to-shoulder rose but body weight fell {abs(weight_delta):.1f} kg — "
                "signals disagree."
            )

    return {
        "angle": angle,
        "before": before,
        "after": after,
        "verdicts": verdicts,
        "any_detectable": any(x["detectable"] for x in verdicts),
        "weight_kg": {"before": w0, "after": w1},
        "conflict": conflict,
    }


@router.get("/progress-photos/heatmap")
async def heatmap(
    angle: str = Query(...),
    before: str = Query(...),
    after: str = Query(...),
):
    """Return a PNG silhouette-change heatmap aligning two dates."""
    conn = get_read_conn()
    paths: list[str] = []
    for d in (before, after):
        row = conn.execute(
            "SELECT file_path FROM progress_photos WHERE photo_date = $d AND angle = $a",
            {"d": date.fromisoformat(d), "a": angle},
        ).fetchone()
        if not row:
            raise HTTPException(404, f"no {angle} photo on {d}")
        paths.append(str(settings.uploads_dir / row[0]))

    try:
        png = change_heatmap(paths[0], paths[1])
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return Response(content=png, media_type="image/png")
