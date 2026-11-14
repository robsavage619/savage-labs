"""Deterministic measurement pipeline — pose, silhouette, geometry.

No language model is involved. rembg (U²-Net) extracts the body silhouette; MediaPipe
Pose (BlazePose, OpenCV Zoo's ONNX export run through cv2.dnn) locates anatomical
landmarks inside it; geometry is read off the silhouette at the landmark heights and
normalized to a scale-invariant reference length (shoulder→hip). See METHODOLOGY.md
§1, §4, §7.

The pose model bundle and the rembg weights are fetched once to a local cache on
first use (model assets, not photo data — photos never leave the machine).
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple

import cv2
import numpy as np
import pooch
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

# Pinned to a commit and checked by hash: the file is fetched once, then trusted.
_POSE_MODEL_URL = (
    "https://media.githubusercontent.com/media/opencv/opencv_zoo/"
    "48b10fa505aeb51fbd127fc60a5c660040e823b7/models/pose_estimation_mediapipe/"
    "pose_estimation_mediapipe_2023mar.onnx"
)
_POSE_MODEL_SHA256 = "9d89c599319a18fb7d2e28451a883476164543182bafca5f09eb2cf767ed2f3f"
# Per socket read, so a transfer that stalls mid-body fails instead of hanging the upload.
_DOWNLOAD_TIMEOUT_S = 30.0
_POSE_INPUT_PX = 256
_ROI_ENLARGE = 1.25  # MediaPipe's own enlargement of the person box
_MIN_PERSON_CONF = 0.5

_rembg_session = None
_pose_net: cv2.dnn.Net | None = None
_pose_lock = threading.Lock()  # cv2.dnn.Net is not safe to share across threads


class Landmark(NamedTuple):
    """One pose landmark, in image-normalized coordinates."""

    x: float
    y: float
    visibility: float


def _get_rembg_session():
    """Lazily build and cache the rembg (U²-Net) session."""
    global _rembg_session
    if _rembg_session is None:
        _rembg_session = new_session("u2net")
    return _rembg_session


def _pose_model_path() -> Path:
    """Path to the cached pose model, downloading and hash-checking it once if absent.

    Raises:
        RuntimeError: If the download fails or the file's hash is not the pinned one.
    """
    try:
        path = pooch.retrieve(
            _POSE_MODEL_URL,
            known_hash=f"sha256:{_POSE_MODEL_SHA256}",
            fname="pose_estimation_mediapipe_2023mar.onnx",
            path=settings.data_dir / "models",
            # pooch's Downloader protocol names its parameters differently from its own class.
            downloader=pooch.HTTPDownloader(  # pyright: ignore[reportArgumentType]
                timeout=_DOWNLOAD_TIMEOUT_S, progressbar=False
            ),
        )
    except (OSError, ValueError) as exc:  # network failure, or pooch's hash mismatch
        raise RuntimeError(f"pose model unavailable: {exc}") from exc
    return Path(path)


def _get_pose_net() -> cv2.dnn.Net:
    """Lazily load and cache the pose network."""
    global _pose_net
    if _pose_net is None:
        _pose_net = cv2.dnn.readNet(str(_pose_model_path()))
    return _pose_net


def load_rgb(path: str | Path) -> np.ndarray:
    """Load an image as an HxWx3 uint8 RGB array, honoring EXIF orientation.

    iPhone photos record rotation in EXIF rather than rotating pixels; without
    applying it the body would be measured sideways. ``exif_transpose`` bakes the
    orientation into the pixels.
    """
    img = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    return np.asarray(img)


def detect_landmarks(rgb: np.ndarray, mask: np.ndarray) -> list[Landmark] | None:
    """Return the pose landmarks of the person in ``mask``, or None.

    The network sees a square crop around the silhouette, the same framing MediaPipe's
    person detector would hand it, so no detector model is needed.

    Args:
        rgb: HxWx3 uint8 RGB image.
        mask: HxW boolean silhouette of the person.

    Returns:
        Landmarks in MediaPipe Pose order (33 body points, then 6 auxiliary), or None
        if the mask is empty or the network sees no person.
    """
    ys, xs = np.where(mask)
    if xs.size == 0:
        return None
    h, w = rgb.shape[:2]
    side = int(_ROI_ENLARGE * max(xs.max() - xs.min(), ys.max() - ys.min())) + 1
    x0 = int((xs.min() + xs.max()) / 2 - side / 2)
    y0 = int((ys.min() + ys.max()) / 2 - side / 2)
    x1, y1 = x0 + side, y0 + side
    roi = cv2.copyMakeBorder(
        rgb[max(y0, 0) : min(y1, h), max(x0, 0) : min(x1, w)],
        max(-y0, 0),
        max(y1 - h, 0),
        max(-x0, 0),
        max(x1 - w, 0),
        cv2.BORDER_CONSTANT,
        value=(0, 0, 0),
    )
    blob = cv2.resize(roi, (_POSE_INPUT_PX, _POSE_INPUT_PX), interpolation=cv2.INTER_AREA)
    with _pose_lock:
        net = _get_pose_net()
        net.setInput(blob.astype(np.float32)[np.newaxis] / 255.0)
        outs = net.forward(net.getUnconnectedOutLayersNames())

    conf = next(o for o in outs if o.size == 1)
    if float(conf.ravel()[0]) < _MIN_PERSON_CONF:
        return None
    # (39, 5): x, y, z in input pixels, then visibility and presence logits.
    raw = next(o for o in outs if o.size == 195).reshape(39, 5)
    k = side / _POSE_INPUT_PX
    return [
        Landmark(
            x=float(x0 + lx * k) / w,
            y=float(y0 + ly * k) / h,
            visibility=float(1.0 / (1.0 + np.exp(-vis))),
        )
        for lx, ly, _z, vis, _presence in raw
    ]


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

    mask = _silhouette_mask(rgb)
    lm = detect_landmarks(rgb, mask)
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
