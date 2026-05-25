"""Blind-control eval — proves the pipeline does not invent change.

The core hallucination guard is the ISAK-derived noise gate plus deterministic
measurement. These tests assert:

1. Identical input yields *no detectable change* (the same-photo-twice control).
2. A real, supra-threshold change is detected with the correct direction.
3. A sub-threshold change is reported as no change (withheld).

Pose detection and background removal are replaced with deterministic stand-ins so
the geometry + gate are tested without a human fixture photo. A real-photo
integration control activates automatically if a fixture is dropped in
``tests/fixtures/vision/front.jpg`` (and ``front2.jpg`` for a same-shoot pair).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from shc.vision import pipeline
from shc.vision.noise import classify_change

_H, _W = 200, 100
_FIXTURES = Path(__file__).parent / "fixtures" / "vision"


class _Landmark:
    def __init__(self, x: float, y: float, vis: float) -> None:
        self.x, self.y, self.visibility = x, y, vis


def _fake_landmarks() -> list[_Landmark]:
    lm = [_Landmark(0.5, 0.5, 0.0) for _ in range(33)]
    # shoulders (px y=40), hips (y=110), ankles (y=190); mid-x = 50.
    lm[11], lm[12] = _Landmark(0.30, 0.20, 0.95), _Landmark(0.70, 0.20, 0.95)
    lm[23], lm[24] = _Landmark(0.35, 0.55, 0.95), _Landmark(0.65, 0.55, 0.95)
    lm[27], lm[28] = _Landmark(0.45, 0.95, 0.95), _Landmark(0.55, 0.95, 0.95)
    # Elbows/wrists left at visibility 0 so arm-exclusion skips them and the
    # synthetic torso geometry is measured intact.
    return lm


def _trapezoid_mask(waist_w: float) -> np.ndarray:
    """Silhouette: shoulder row width 60, hip row 50, waist (row 75) = ``waist_w``."""
    mask = np.zeros((_H, _W), dtype=bool)
    cx = 50
    for y in range(40, 111):
        if y <= 75:
            w = 60 + (waist_w - 60) * (y - 40) / 35
        else:
            w = waist_w + (50 - waist_w) * (y - 75) / 35
        half = int(round(w / 2))
        mask[y, cx - half : cx + half] = True
    return mask


def _rgba_from_mask(mask: np.ndarray) -> np.ndarray:
    rgba = np.zeros((_H, _W, 4), dtype=np.uint8)
    rgba[..., :3] = 128  # uniform gray → symmetric lighting
    rgba[..., 3] = mask.astype(np.uint8) * 255
    return rgba


@pytest.fixture
def fake_cv(monkeypatch):
    """Patch pose + background removal with deterministic stand-ins.

    Returns a setter so each test can choose the silhouette's waist width.
    """
    state: dict[str, np.ndarray] = {"mask": _trapezoid_mask(40)}

    monkeypatch.setattr(pipeline, "detect_landmarks", lambda _rgb: _fake_landmarks())
    monkeypatch.setattr(
        pipeline, "remove", lambda _rgb, session=None: _rgba_from_mask(state["mask"])
    )

    def _set_waist(waist_w: float) -> None:
        state["mask"] = _trapezoid_mask(waist_w)

    return _set_waist


def _analyze(tmp_path: Path, waist_w: float, set_waist) -> dict[str, float]:
    set_waist(waist_w)
    img = tmp_path / "p.png"
    from PIL import Image

    Image.fromarray(np.full((_H, _W, 3), 128, dtype=np.uint8)).save(img)
    result = pipeline.analyze_photo(img)
    return {k: v[1] for k, v in result.measurements.items()}


def test_identical_input_yields_no_change(tmp_path, fake_cv):
    """Same silhouette twice → every metric is below the noise floor."""
    a = _analyze(tmp_path, 40, fake_cv)
    b = _analyze(tmp_path, 40, fake_cv)
    assert a == b  # deterministic
    for metric in a:
        v = classify_change(metric, a[metric], b[metric])
        assert not v.detectable
        assert v.direction == "none"


def test_quality_gate_passes_clean_capture(tmp_path, fake_cv):
    fake_cv(40)
    from PIL import Image

    img = tmp_path / "p.png"
    Image.fromarray(np.full((_H, _W, 3), 128, dtype=np.uint8)).save(img)
    result = pipeline.analyze_photo(img)
    assert result.quality is not None
    assert result.quality.passed, result.quality.flags


def test_supra_threshold_change_detected_with_direction(tmp_path, fake_cv):
    """Waist 40 → 30 px is a real reduction → detectable 'down'."""
    before = _analyze(tmp_path, 40, fake_cv)
    after = _analyze(tmp_path, 30, fake_cv)
    v = classify_change(
        "waist_to_shoulder", before["waist_to_shoulder"], after["waist_to_shoulder"]
    )
    assert v.detectable
    assert v.direction == "down"
    # Shoulder/hip unchanged → must read as no change.
    assert not classify_change(
        "shoulder_width", before["shoulder_width"], after["shoulder_width"]
    ).detectable


def test_sub_threshold_change_withheld(tmp_path, fake_cv):
    """A ~1% waist change sits inside the 2% error band → no change."""
    before = _analyze(tmp_path, 40.0, fake_cv)
    after = _analyze(tmp_path, 40.4, fake_cv)
    v = classify_change(
        "waist_to_shoulder", before["waist_to_shoulder"], after["waist_to_shoulder"]
    )
    assert not v.detectable
    assert v.direction == "none"


@pytest.mark.skipif(
    not (_FIXTURES / "front.jpg").exists(),
    reason="drop a real photo at tests/fixtures/vision/front.jpg to enable",
)
def test_real_photo_same_image_no_change():
    """Real-photo control: the same photo analyzed twice yields no change."""
    a = {k: v[1] for k, v in pipeline.analyze_photo(_FIXTURES / "front.jpg").measurements.items()}
    b = {k: v[1] for k, v in pipeline.analyze_photo(_FIXTURES / "front.jpg").measurements.items()}
    for metric in a:
        assert not classify_change(metric, a[metric], b[metric]).detectable
