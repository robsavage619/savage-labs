"""Deterministic measurement pipeline — pose, silhouette, geometry.

No language model is involved. MediaPipe's PoseLandmarker (Tasks API) locates
anatomical landmarks; rembg (U²-Net) extracts the body silhouette; geometry is read
off the silhouette at the landmark heights and normalized to a scale-invariant
reference length (shoulder→ankle). See METHODOLOGY.md §1, §4.

The pose model bundle and the rembg weights are fetched once to a local cache on
first use (model assets, not photo data — photos never leave the machine).
"""

from __future__ import annotations

import logging
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision as mp_vision
from PIL import Image, ImageOps
from pillow_heif import register_heif_opener
from rembg import new_session, remove

from shc.config import settings
from shc.vision.quality_gate import (
    LOWER_BODY_MIN_VISIBILITY,
    QualityResult,
    evaluate_quality,
)

log = logging.getLogger(__name__)

# Let PIL decode iPhone HEIC/HEIF photos.
register_heif_opener()

# MediaPipe Pose landmark indices.
_L_SHOULDER, _R_SHOULDER = 11, 12
_L_ELBOW, _R_ELBOW = 13, 14
_L_WRIST, _R_WRIST = 15, 16
_L_HIP, _R_HIP = 23, 24
_L_ANKLE, _R_ANKLE = 27, 28
# Arm chains used to subtract arms from the silhouette before measuring widths.
_ARM_CHAINS = ((_L_SHOULDER, _L_ELBOW, _L_WRIST), (_R_SHOULDER, _R_ELBOW, _R_WRIST))
# Measurement needs only the torso (shoulders + hips); the waist sits between
# them. The scale reference is the shoulder→hip trunk span — skeletally stable
# and present in any shot framed shoulders-to-hips, so feet are never required.
_MEASURE_LANDMARKS = (_L_SHOULDER, _R_SHOULDER, _L_HIP, _R_HIP)

_MASK_THRESHOLD = 128  # alpha cutoff for foreground

_POSE_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
    "pose_landmarker_lite/float16/latest/pose_landmarker_lite.task"
)

_rembg_session = None
_pose_landmarker = None


def _get_rembg_session():
    """Lazily build and cache the rembg (U²-Net) session."""
    global _rembg_session
    if _rembg_session is None:
        _rembg_session = new_session("u2net")
    return _rembg_session


def _pose_model_path() -> Path:
    """Path to the cached pose model bundle, downloading it once if absent."""
    models_dir = settings.data_dir / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    path = models_dir / "pose_landmarker_lite.task"
    if not path.exists():
        log.info("downloading pose landmarker model bundle (one-time)")
        urllib.request.urlretrieve(_POSE_MODEL_URL, path)  # noqa: S310 (fixed https URL)
    return path


def _get_pose_landmarker():
    """Lazily build and cache the PoseLandmarker (single-image mode)."""
    global _pose_landmarker
    if _pose_landmarker is None:
        options = mp_vision.PoseLandmarkerOptions(
            base_options=mp_python.BaseOptions(model_asset_path=str(_pose_model_path())),
            running_mode=mp_vision.RunningMode.IMAGE,
        )
        _pose_landmarker = mp_vision.PoseLandmarker.create_from_options(options)
    return _pose_landmarker


def load_rgb(path: str | Path) -> np.ndarray:
    """Load an image as an HxWx3 uint8 RGB array, honoring EXIF orientation.

    iPhone photos record rotation in EXIF rather than rotating pixels; without
    applying it the body would be measured sideways. ``exif_transpose`` bakes the
    orientation into the pixels.
    """
    img = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    return np.asarray(img)


def detect_landmarks(rgb: np.ndarray) -> list | None:
    """Return the first detected person's pose landmarks, or None.

    Args:
        rgb: HxWx3 uint8 RGB image.

    Returns:
        A list of normalized landmarks (each with ``.x``, ``.y``, ``.visibility``),
        or None if no pose was detected.
    """
    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))
    result = _get_pose_landmarker().detect(mp_image)
    if not result.pose_landmarks:
        return None
    return result.pose_landmarks[0]


@dataclass
class PhotoAnalysis:
    """Measurements and quality signals extracted from one photo.

    Attributes:
        measurements: metric name → (value_px or None, normalized value).
        pose_conf: Minimum landmark visibility used.
        scale_px: Shoulder→ankle reference length, in pixels.
        brightness_asymmetry: Left/right luminance imbalance over the body box.
        quality: Capture-quality gate result.
    """

    measurements: dict[str, tuple[float | None, float]] = field(default_factory=dict)
    pose_conf: float = 0.0
    scale_px: float = 0.0
    brightness_asymmetry: float = 0.0
    quality: QualityResult | None = None


def _silhouette_mask(rgb: np.ndarray) -> np.ndarray:
    """Return a boolean foreground mask via rembg background removal."""
    cutout = remove(rgb, session=_get_rembg_session())  # RGBA
    alpha = np.asarray(cutout)[:, :, 3]
    return alpha >= _MASK_THRESHOLD


def _arm_mask(lm: list, h: int, w: int, scale_px: float) -> np.ndarray:
    """Boolean mask of the arms, drawn as thick capsules along the arm chains.

    Subtracting this from the silhouette removes arms so the measured waist/
    shoulder/hip widths reflect the torso regardless of arm position — the main
    real-world pose variable. A side is skipped if its joints aren't confident.
    """
    arm = np.zeros((h, w), dtype=np.uint8)
    thickness = max(int(0.11 * scale_px), 12)
    for chain in _ARM_CHAINS:
        pts = [
            (int(lm[i].x * w), int(lm[i].y * h))
            for i in chain
            if lm[i].visibility >= 0.4 and 0.0 <= lm[i].y <= 1.0
        ]
        for a, b in zip(pts, pts[1:], strict=False):
            cv2.line(arm, a, b, 255, thickness)
    return arm > 0


def _row_width(mask: np.ndarray, y: int) -> float:
    """Horizontal foreground extent (px) of the silhouette at row ``y``."""
    y = int(np.clip(y, 0, mask.shape[0] - 1))
    cols = np.where(mask[y])[0]
    if cols.size == 0:
        return 0.0
    return float(cols.max() - cols.min() + 1)


def _brightness_asymmetry(rgb: np.ndarray, mask: np.ndarray) -> float:
    """Left/right mean-luminance imbalance within the body bounding box.

    Returns the absolute difference of left- and right-half mean luminance,
    expressed as a fraction of the overall body-pixel mean (0 = symmetric).
    """
    ys, xs = np.where(mask)
    if xs.size == 0:
        return 1.0
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY).astype(np.float64)
    mid_x = int((xs.min() + xs.max()) / 2)
    left = gray[ys[xs < mid_x], xs[xs < mid_x]] if np.any(xs < mid_x) else np.array([0.0])
    right = gray[ys[xs >= mid_x], xs[xs >= mid_x]] if np.any(xs >= mid_x) else np.array([0.0])
    overall = gray[ys, xs].mean()
    if overall <= 0:
        return 1.0
    return float(abs(left.mean() - right.mean()) / overall)


def analyze_photo(path: str | Path, baseline_scale_px: float | None = None) -> PhotoAnalysis:
    """Extract scale-normalized body geometry from a single photo.

    Args:
        path: Image file path.
        baseline_scale_px: The user's established shoulder→ankle reference length,
            used only for the scale-drift quality check. None for the first photo.

    Returns:
        A populated :class:`PhotoAnalysis`.

    Raises:
        ValueError: If no person/pose can be detected in the image.
    """
    rgb = load_rgb(path)
    h, w = rgb.shape[:2]

    lm = detect_landmarks(rgb)
    if lm is None:
        raise ValueError("no pose detected in image")

    def px(i: int) -> tuple[float, float]:
        return lm[i].x * w, lm[i].y * h

    pose_conf = min(lm[i].visibility for i in _MEASURE_LANDMARKS)

    # Torso must be in frame: shoulders + hips confident and within [0, 1].
    torso_visible = all(
        lm[i].visibility >= LOWER_BODY_MIN_VISIBILITY and 0.0 <= lm[i].y <= 1.0
        for i in _MEASURE_LANDMARKS
    )

    sh_mid = np.array(px(_L_SHOULDER)) + np.array(px(_R_SHOULDER))
    sh_mid /= 2
    hip_mid = (np.array(px(_L_HIP)) + np.array(px(_R_HIP))) / 2
    # Scale = shoulder→hip trunk span (stable, present in any torso-framed shot).
    scale_px = float(np.linalg.norm(sh_mid - hip_mid)) or 1.0

    mask = _silhouette_mask(rgb)
    # Remove arms so widths reflect the torso, not arm position.
    torso = mask & ~_arm_mask(lm, h, w, scale_px)

    shoulder_y, hip_y = int(sh_mid[1]), int(hip_mid[1])
    top, bot = sorted((shoulder_y, hip_y))
    span = max(bot - top, 1)

    def _frac(a: float, b: float) -> list[float]:
        """Non-zero torso widths over [top+a·span, top+b·span]."""
        ws = [_row_width(torso, int(top + f * span)) for f in (a, b)] + [
            _row_width(torso, y) for y in range(int(top + a * span), int(top + b * span) + 1)
        ]
        return [x for x in ws if x > 0]

    # Shoulder = broadest point near the shoulder line (deltoid breadth).
    # Waist = narrowest point in the lower-middle trunk (the natural waist —
    # avoids the bony acromion at the very top). Hip = at the hip line.
    sh_band = _frac(0.0, 0.15)
    waist_band = _frac(0.45, 0.90)
    shoulder_width = max(sh_band) if sh_band else _row_width(torso, shoulder_y)
    waist_width = min(waist_band) if waist_band else _row_width(torso, (top + bot) // 2)
    hip_width = _row_width(torso, hip_y)

    area = float(mask.sum())

    measurements: dict[str, tuple[float | None, float]] = {
        "shoulder_width": (shoulder_width, shoulder_width / scale_px),
        "hip_width": (hip_width, hip_width / scale_px),
        "waist_width": (waist_width, waist_width / scale_px),
        "silhouette_area": (area, area / (scale_px**2)),
        "waist_to_shoulder": (None, waist_width / shoulder_width if shoulder_width else 0.0),
        "waist_to_hip": (None, waist_width / hip_width if hip_width else 0.0),
    }

    asym = _brightness_asymmetry(rgb, mask)
    quality = evaluate_quality(
        pose_conf=pose_conf,
        torso_visible=torso_visible,
        scale_px=scale_px,
        baseline_scale_px=baseline_scale_px,
        brightness_asymmetry=asym,
    )

    return PhotoAnalysis(
        measurements=measurements,
        pose_conf=pose_conf,
        scale_px=scale_px,
        brightness_asymmetry=asym,
        quality=quality,
    )
