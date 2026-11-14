"""Aligned silhouette overlay + change heatmap for two dates.

Two photos are registered using a similarity transform derived from the
shoulder-midpoint and ankle-midpoint landmarks, then their silhouettes are
differenced. The result makes change *visible* (where the outline moved in/out)
rather than asserted. See METHODOLOGY.md §4.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np

from shc.vision.pipeline import (
    _L_HIP,
    _L_SHOULDER,
    _R_HIP,
    _R_SHOULDER,
    _silhouette_mask,
    detect_landmarks,
    load_rgb,
)

log = logging.getLogger(__name__)


def _anchors_and_mask(path: str | Path) -> tuple[np.ndarray, np.ndarray, tuple[int, int]]:
    """Return (mask, anchor_points, (h, w)) for one image.

    Anchor points are the shoulder-midpoint and hip-midpoint in pixel coords.

    Raises:
        ValueError: If no pose is detected.
    """
    return _anchors_and_mask_at(str(path), Path(path).stat().st_mtime_ns)


@lru_cache(maxsize=8)  # keyed on mtime, so a retake of the same date is re-read
def _anchors_and_mask_at(
    path: str, _mtime_ns: int
) -> tuple[np.ndarray, np.ndarray, tuple[int, int]]:
    rgb = load_rgb(path)
    h, w = rgb.shape[:2]
    mask = _silhouette_mask(rgb)
    lm = detect_landmarks(rgb, mask)
    if lm is None:
        raise ValueError("no pose detected in image")

    def px(i: int) -> np.ndarray:
        return np.array([lm[i].x * w, lm[i].y * h], dtype=np.float32)

    sh_mid = (px(_L_SHOULDER) + px(_R_SHOULDER)) / 2
    hip_mid = (px(_L_HIP) + px(_R_HIP)) / 2
    return mask, np.stack([sh_mid, hip_mid]), (h, w)


def render_jpeg(path: str | Path, *, align_to: str | Path | None = None, width: int) -> bytes:
    """Encode a stored photo as a JPEG, optionally registered onto another photo's frame.

    Args:
        path: Photo to show.
        align_to: Reference photo. When given, ``path`` is warped by the same
            shoulder/hip similarity transform the heatmap uses and drawn on the
            reference's canvas, so the two overlay exactly under a slider.
        width: Output width in pixels (never upscaled).

    Returns:
        JPEG bytes.

    Raises:
        ValueError: If a pose cannot be detected for alignment, or encoding fails.
    """
    rgb = load_rgb(path)
    if align_to is not None:
        _, anchors, _ = _anchors_and_mask(path)
        _, ref_anchors, (h, w) = _anchors_and_mask(align_to)
        transform = cv2.estimateAffinePartial2D(anchors, ref_anchors)[0]
        if transform is None:
            raise ValueError("could not align photos (degenerate anchors)")
        rgb = cv2.warpAffine(rgb, transform, (w, h))
    if width < rgb.shape[1]:
        height = round(rgb.shape[0] * width / rgb.shape[1])
        rgb = cv2.resize(rgb, (width, height), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(
        ".jpg", cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 85]
    )
    if not ok:
        raise ValueError("failed to encode JPEG")
    return buf.tobytes()


def change_heatmap(path_before: str | Path, path_after: str | Path) -> bytes:
    """Render a PNG heatmap of silhouette change between two dates.

    The ``after`` photo is aligned onto the ``before`` frame. Red marks area the
    body lost (present before, absent after); green marks area gained.

    Args:
        path_before: Earlier photo.
        path_after: Later photo.

    Returns:
        PNG-encoded RGB image bytes.

    Raises:
        ValueError: If a pose cannot be detected, or PNG encoding fails.
    """
    mask_a, anch_a, (h, w) = _anchors_and_mask(path_before)
    mask_b, anch_b, _ = _anchors_and_mask(path_after)

    transform = cv2.estimateAffinePartial2D(anch_b, anch_a)[0]
    if transform is None:
        raise ValueError("could not align photos (degenerate anchors)")
    aligned_b = cv2.warpAffine(mask_b.astype(np.uint8), transform, (w, h)) > 0

    canvas = np.zeros((h, w, 3), dtype=np.uint8)
    canvas[mask_a & aligned_b] = (90, 90, 90)  # unchanged body
    canvas[mask_a & ~aligned_b] = (220, 60, 60)  # lost (receded)
    canvas[~mask_a & aligned_b] = (60, 200, 90)  # gained

    ok, buf = cv2.imencode(".png", cv2.cvtColor(canvas, cv2.COLOR_RGB2BGR))
    if not ok:
        raise ValueError("failed to encode heatmap PNG")
    return buf.tobytes()
