"""Capture-quality gate — block only what makes measurement impossible.

Thresholds are grounded in METHODOLOGY.md §3. Two severities:

* **Blocking** (``flags``): the body can't be measured reliably — incomplete frame
  or low pose confidence. These set ``quality_pass = False`` and the photo is
  excluded from trends.
* **Advisory** (``advisories``): real-world variation that does *not* corrupt the
  silhouette geometry — uneven lighting (segmentation is lighting-robust) and
  camera-distance drift (the headline ratios are distance-invariant). Surfaced as
  notes; the photo still passes and counts.

This keeps the gate flexible: you don't need a perfect studio shot, only one where
your torso is clearly in frame.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# METHODOLOGY.md §3.
MIN_POSE_CONFIDENCE = 0.7
MAX_SCALE_DRIFT_FRACTION = 0.10
MAX_BRIGHTNESS_ASYMMETRY = 0.15
# A landmark below this visibility (or outside the frame) is treated as not
# captured — the torso (shoulders through hips) must be in shot to measure.
LOWER_BODY_MIN_VISIBILITY = 0.5


@dataclass(frozen=True)
class QualityResult:
    """Outcome of the capture-quality gate.

    Attributes:
        passed: True when there are no blocking flags.
        flags: Blocking issues that prevent measurement (empty when ``passed``).
        advisories: Non-blocking notes that don't affect the measurement.
        pose_conf: Minimum landmark visibility observed.
    """

    passed: bool
    flags: list[str]
    advisories: list[str] = field(default_factory=list)
    pose_conf: float = 0.0


def evaluate_quality(
    *,
    pose_conf: float,
    torso_visible: bool,
    scale_px: float,
    baseline_scale_px: float | None,
    brightness_asymmetry: float,
) -> QualityResult:
    """Evaluate a photo against the standardized-capture requirements.

    Args:
        pose_conf: Minimum visibility across the landmarks used for measurement.
        torso_visible: Whether shoulders and hips are in-frame and confident.
        scale_px: This photo's shoulder→hip reference length, in pixels.
        baseline_scale_px: The user's established reference length, or None if this
            is the first photo (no drift check possible yet).
        brightness_asymmetry: Left/right mean-luminance imbalance over the body box,
            as a fraction of the mean.

    Returns:
        A :class:`QualityResult` listing any failed checks.
    """
    flags: list[str] = []  # blocking
    advisories: list[str] = []  # non-blocking notes

    # Blocking — incomplete framing is the root cause of low confidence, so report
    # it specifically rather than the vague low-confidence flag.
    if not torso_visible:
        flags.append("incomplete_frame")
    elif pose_conf < MIN_POSE_CONFIDENCE:
        flags.append("low_pose_confidence")

    # Advisory — these vary in the real world but don't corrupt silhouette geometry.
    if baseline_scale_px:
        drift = abs(scale_px - baseline_scale_px) / baseline_scale_px
        if drift > MAX_SCALE_DRIFT_FRACTION:
            advisories.append("scale_drift")

    if brightness_asymmetry > MAX_BRIGHTNESS_ASYMMETRY:
        advisories.append("uneven_lighting")

    return QualityResult(
        passed=not flags, flags=flags, advisories=advisories, pose_conf=pose_conf
    )
