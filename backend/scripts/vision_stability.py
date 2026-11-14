"""Measure the photo pipeline's own noise: re-measure one photo under capture-like changes.

Usage: uv run python scripts/vision_stability.py data/uploads/progress/<photo>.jpg [...]

Each photo is mirrored, rescaled, re-framed, tilted, relit and re-compressed, then
measured again. The spread per metric is the floor below which a change between two
sessions cannot be told from capture variation. It is a lower bound: the subject is
not re-posed. METHODOLOGY.md §7 records the numbers this produced.
"""

from __future__ import annotations

import statistics
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path

from PIL import Image, ImageEnhance, ImageOps

from shc.vision import pipeline

METRICS = ("waist_to_shoulder", "waist_to_hip", "shoulder_width", "waist_width", "hip_width")


def perturbations(img: Image.Image) -> Iterator[tuple[str, Image.Image]]:
    """Yield (name, image) variants a repeat capture could plausibly produce."""
    w, h = img.size
    yield "identity", img
    yield "mirror", ImageOps.mirror(img)
    for s in (0.75, 0.5, 0.33):
        yield f"scale {s}", img.resize((int(w * s), int(h * s)), Image.Resampling.LANCZOS)
    box = (int(w * 0.04), int(h * 0.04), int(w * 0.96), int(h * 0.96))
    yield "crop 4%", img.crop(box)
    for deg in (-2, -1, 1, 2):
        yield f"tilt {deg:+d}", img.rotate(deg, Image.Resampling.BICUBIC).crop(box)
    for b in (0.75, 1.25):
        yield f"light x{b}", ImageEnhance.Brightness(img).enhance(b)
    yield "contrast x0.8", ImageEnhance.Contrast(img).enhance(0.8)
    yield "jpeg q50", img


def main() -> None:
    tmp = Path(tempfile.mkdtemp())
    for photo in map(Path, sys.argv[1:]):
        base = ImageOps.exif_transpose(Image.open(photo)).convert("RGB")
        rows: dict[str, dict[str, float]] = {}
        for name, im in perturbations(base):
            path = tmp / "p.jpg"
            im.save(path, quality=50 if name == "jpeg q50" else 95)
            try:
                found = pipeline.analyze_photo(path).measurements
            except ValueError as exc:
                sys.stdout.write(f"  {name:14s} FAILED: {exc}\n")
                continue
            rows[name] = {m: found[m][1] for m in METRICS}
        ref = rows.pop("identity")
        out = [f"\n{photo.name}", f"  {'':14s}" + "".join(f"{m:>19s}" for m in METRICS)]
        out.append(f"  {'reading':14s}" + "".join(f"{ref[m]:19.4f}" for m in METRICS))
        devs = {m: [(r[m] / ref[m] - 1) * 100 for r in rows.values()] for m in METRICS}
        for i, name in enumerate(rows):
            out.append(f"  {name:14s}" + "".join(f"{devs[m][i]:+18.2f}%" for m in METRICS))
        worst = "".join(f"{max(map(abs, devs[m])):18.2f}%" for m in METRICS)
        sd = "".join(f"{statistics.pstdev(devs[m]):18.2f}%" for m in METRICS)
        out += [f"  {'worst':14s}{worst}", f"  {'sd':14s}{sd}"]
        sys.stdout.write("\n".join(out) + "\n")


if __name__ == "__main__":
    main()
