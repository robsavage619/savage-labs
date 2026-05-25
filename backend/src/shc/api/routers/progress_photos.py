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
from pydantic import BaseModel

from shc.config import settings
from shc.db.schema import get_read_conn, write_ctx
from shc.metrics import compute_daily_state
from shc.vision.noise import GIRTH_NOISE_FRACTION, classify_change
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


# ── Physique critique (copy-prompt → CC → POST-back) ─────────────────────────
#
# Guardrails against lighting-driven inconsistency:
#  1. The change verdict is the deterministic 2%-gated measurement, passed in —
#     the model must not contradict it.
#  2. Shape/change claims are anchored to the silhouette-derived numbers, not the
#     photo's pixels (lighting-invariant).
#  3. The critique is anchored to the measurement basis; the UI only offers a
#     refresh once the median clears the 2% noise floor, so daily lighting
#     variation shows the same critique.
#  4. No body-fat % claims; visible detail is explicitly flagged lighting-dependent.


def _latest_body_comp() -> dict:
    """Current gated body-composition block from the canonical DailyState."""
    return compute_daily_state(get_read_conn()).get("body_composition", {})


def _photo_path(angle: str, d: date) -> str | None:
    row = get_read_conn().execute(
        "SELECT file_path FROM progress_photos WHERE photo_date = $d AND angle = $a AND quality_pass",
        {"d": d, "a": angle},
    ).fetchone()
    return str(settings.uploads_dir / row[0]) if row else None


def _build_critique_prompt(bc: dict) -> str:
    w2s, w2h = bc.get("waist_to_shoulder"), bc.get("waist_to_hip")
    verdict = bc.get("trend_direction") or "baseline"
    trend = (
        f"{bc['trend_28d_pct']:+.1f}% over ~28d" if bc.get("trend_28d_pct") is not None else "no trend yet (single session)"
    )
    return (
        "You are giving Rob a physique critique from his progress photos. Follow these "
        "guardrails exactly — they keep the critique consistent shot-to-shot.\n\n"
        "## Authoritative measured state (silhouette-derived, lighting-invariant)\n"
        f"- waist:shoulder ratio = {w2s}\n"
        f"- waist:hip ratio = {w2h}\n"
        f"- measured change verdict = **{verdict}** ({trend})\n"
        f"- noise floor = {GIRTH_NOISE_FRACTION * 100:.0f}% (changes smaller than this are not real)\n"
        "- goal: lean out while KEEPING strength and size (not generic recomp; he wants to "
        "stay the heavy, strong athlete)\n\n"
        "## Rules\n"
        "1. SECTION 1 — Shape & change (authoritative): base ONLY on the numbers and verdict "
        "above. You MUST NOT contradict the verdict — if it says 'stable' or 'baseline', do "
        "not claim he got leaner or softer. Describe proportions and where mass sits. Do NOT "
        "estimate body-fat %.\n"
        "2. SECTION 2 — Visible detail (advisory, lighting-dependent): from the attached "
        "photos, note visible muscle detail/definition. Begin it with 'Lighting-dependent:' "
        "and make NO change claims here (lighting/pump/angle vary day to day).\n"
        "3. Be direct and useful, not flattering. Tie advice to the keep-size/lean-out goal.\n\n"
        "## Return\n"
        "POST your result to /api/progress-photos/critique as JSON: "
        '{"verdict": "<leaner|stable|softer|baseline>", "shape_change_md": "<section 1 '
        'markdown>", "visible_detail_md": "<section 2 markdown>"}\n'
        "Attach Rob's latest front and side photos to your session before writing section 2."
    )


@router.get("/progress-photos/critique-prompt")
async def critique_prompt():
    """Return the grounded critique prompt + the photos to attach + staleness."""
    bc = _latest_body_comp()
    if bc.get("waist_to_shoulder") is None:
        raise HTTPException(404, "no passing front photo yet")
    latest = date.fromisoformat(bc["as_of"])
    return {
        "prompt": _build_critique_prompt(bc),
        "attach_photos": {
            "front": _photo_path("front", latest),
            "side": _photo_path("side", latest),
        },
        "basis": {"w2s": bc["waist_to_shoulder"], "w2h": bc["waist_to_hip"]},
    }


class CritiqueSubmission(BaseModel):
    verdict: str
    shape_change_md: str
    visible_detail_md: str | None = None


@router.post("/progress-photos/critique")
async def submit_critique(body: CritiqueSubmission):
    """Persist a Claude-generated critique, anchored to the current gated state."""
    bc = _latest_body_comp()
    async with write_ctx() as conn:
        conn.execute(
            "INSERT INTO physique_critiques "
            "(id, basis_w2s, basis_w2h, verdict, shape_change_md, visible_detail_md) "
            "VALUES ($id, $w2s, $w2h, $v, $sc, $vd)",
            {
                "id": str(uuid.uuid4()),
                "w2s": bc.get("waist_to_shoulder"),
                "w2h": bc.get("waist_to_hip"),
                "v": body.verdict,
                "sc": body.shape_change_md,
                "vd": body.visible_detail_md,
            },
        )
    return {"status": "ok"}


@router.get("/progress-photos/critique")
async def latest_critique():
    """Return the latest critique and whether measurements have moved past noise."""
    row = get_read_conn().execute(
        "SELECT created_at, verdict, shape_change_md, visible_detail_md, basis_w2s, basis_w2h "
        "FROM physique_critiques ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    if not row:
        return {"critique": None, "stale": True, "reason": "no critique yet"}

    bc = _latest_body_comp()
    cur_w2s, cur_w2h = bc.get("waist_to_shoulder"), bc.get("waist_to_hip")
    stale, reason = False, "up to date — no measured change since last critique"
    if cur_w2s and row[4]:
        moved = abs(cur_w2s - row[4]) / row[4] >= GIRTH_NOISE_FRACTION or (
            cur_w2h and row[5] and abs(cur_w2h - row[5]) / row[5] >= GIRTH_NOISE_FRACTION
        )
        if moved:
            stale, reason = True, "measurements moved beyond the 2% floor — refresh recommended"

    return {
        "critique": {
            "created_at": str(row[0]),
            "verdict": row[1],
            "shape_change_md": row[2],
            "visible_detail_md": row[3],
        },
        "stale": stale,
        "reason": reason,
    }
