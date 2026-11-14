"""Read tape-style girths, stature and implied mass off a closed body mesh.

Model-agnostic: takes vertices (metres, +Y up) and faces from any body model. A girth
is the convex-hull perimeter of the torso cross-section, which is what a tape pulled
snug around the body measures: it bridges concavities (the spine groove, the gap
between the glutes) instead of following them.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import trimesh
from scipy.spatial import ConvexHull

# SMPL-family literature converts mesh volume to mass at ~985 kg/m^3 (whole-body
# density including lung air). Real density runs ~1.01-1.07 by body fat, so treat
# implied mass as a sanity check good to roughly ±5%, not a weight estimate.
BODY_DENSITY_KG_M3 = 985.0

# Search bands as fractions of stature from the floor, wide enough to hold each site
# on an adult: chest at its widest across the nipple line, hip at the widest gluteal
# point. The waist is not searched: SHC's tape protocol says "at the navel, relaxed",
# so it is read at a navel height the caller supplies.
_BANDS = {"chest": (0.68, 0.76, max), "hip": (0.46, 0.54, max)}


@dataclass(frozen=True)
class Girths:
    """Tape-style measurements of one mesh, in centimetres and kilograms."""

    stature_cm: float
    chest_cm: float
    waist_cm: float
    hip_cm: float
    thigh_cm: float
    implied_mass_kg: float


def _torso_perimeter(mesh: trimesh.Trimesh, y: float, centre_xz: np.ndarray) -> float:
    """Convex-hull perimeter of the cross-section loop that encloses the trunk centre."""
    section = mesh.section(plane_origin=[0, y, 0], plane_normal=[0, 1, 0])
    if section is None:
        return float("nan")
    best = float("nan")
    best_dist = np.inf
    for loop in section.discrete:
        xz = loop[:, [0, 2]]
        if len(xz) < 3:
            continue
        # The trunk loop is the one whose centroid sits nearest the trunk axis;
        # arm loops at the same height sit off to the sides.
        dist = float(np.linalg.norm(xz.mean(axis=0) - centre_xz))
        if dist < best_dist:
            hull = ConvexHull(xz)
            best, best_dist = float(hull.area), dist  # 2-D hull "area" is its perimeter
    return best


def _leg_perimeter(mesh: trimesh.Trimesh, y: float) -> float:
    """Mean convex-hull perimeter of the two largest loops at height ``y`` (the thighs)."""
    section = mesh.section(plane_origin=[0, y, 0], plane_normal=[0, 1, 0])
    if section is None:
        return float("nan")
    perims = sorted(
        (float(ConvexHull(loop[:, [0, 2]]).area) for loop in section.discrete if len(loop) >= 3),
        reverse=True,
    )
    return float(np.mean(perims[:2])) if len(perims) >= 2 else float("nan")


def measure(vertices: np.ndarray, faces: np.ndarray, *, navel_y: float, thigh_y: float) -> Girths:
    """Measure stature, chest, waist, hip and mid-thigh girth and implied mass.

    Args:
        vertices: (N, 3) mesh vertices in metres, +Y up, arms raised clear of the trunk.
        faces: (F, 3) triangle indices.
        navel_y: Height of the navel, where the waist is taped.
        thigh_y: Height midway between hip joint and knee, where mid-thigh is taped.

    Returns:
        The measurements.

    Raises:
        ValueError: If the mesh is not watertight, so its volume is meaningless.
    """
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    if not mesh.is_watertight:
        raise ValueError("mesh is not watertight; volume and girths would be wrong")
    floor, top = vertices[:, 1].min(), vertices[:, 1].max()
    stature = top - floor
    # Median over the whole surface: the trunk holds most of it, so arms and legs
    # can't drag it off-axis.
    centre_xz = np.median(mesh.triangles_center[:, [0, 2]], axis=0)

    out: dict[str, float] = {}
    for site, (lo, hi, pick) in _BANDS.items():
        heights = floor + stature * np.linspace(lo, hi, 41)
        perims = [p for p in (_torso_perimeter(mesh, y, centre_xz) for y in heights) if p == p]
        out[site] = pick(perims) * 100 if perims else float("nan")

    return Girths(
        stature_cm=stature * 100,
        chest_cm=out["chest"],
        waist_cm=_torso_perimeter(mesh, navel_y, centre_xz) * 100,
        hip_cm=out["hip"],
        thigh_cm=_leg_perimeter(mesh, thigh_y) * 100,
        implied_mass_kg=abs(mesh.volume) * BODY_DENSITY_KG_M3,
    )


if __name__ == "__main__":
    # Check on shapes with known answers: an upright elliptic cylinder "torso".
    a, b, h = 0.18, 0.12, 1.8  # semi-axes and height, metres
    cyl = trimesh.creation.cylinder(radius=1.0, height=h, sections=720)
    cyl.apply_scale([a, b, 1.0])
    cyl.apply_transform(trimesh.transformations.rotation_matrix(-np.pi / 2, [1, 0, 0]))
    cyl.apply_translation([0, h / 2, 0])
    g = measure(np.asarray(cyl.vertices), np.asarray(cyl.faces), navel_y=0.9, thigh_y=0.5)
    ramanujan = np.pi * (3 * (a + b) - np.sqrt((3 * a + b) * (a + 3 * b))) * 100
    volume_mass = np.pi * a * b * h * BODY_DENSITY_KG_M3
    assert abs(g.stature_cm - h * 100) < 0.01, g
    for girth in (g.chest_cm, g.waist_cm, g.hip_cm):
        assert abs(girth - ramanujan) < 0.05, (girth, ramanujan)
    assert abs(g.implied_mass_kg - volume_mass) / volume_mass < 1e-3, (g, volume_mass)

    # A concave trunk (two overlapping lobes, like the glutes) must read as the tape
    # would, the hull: two circles of radius r, centres 2d apart, hull = 2*pi*r + 4d.
    from shapely.geometry import Point

    r, d = 0.10, 0.07
    lobes = Point(-d, 0).buffer(r, 256).union(Point(d, 0).buffer(r, 256))
    body = trimesh.creation.extrude_polygon(lobes, height=h)
    body.apply_transform(trimesh.transformations.rotation_matrix(-np.pi / 2, [1, 0, 0]))
    g2 = measure(np.asarray(body.vertices), np.asarray(body.faces), navel_y=0.9, thigh_y=0.5)
    hull = (2 * np.pi * r + 4 * d) * 100
    assert abs(g2.waist_cm - hull) < 0.05, (g2.waist_cm, hull)
    assert g2.waist_cm < lobes.length * 100, "tape must bridge the concavity"
    # Two separate legs: thigh girth is each leg's own perimeter, not their joint hull.
    legs = trimesh.util.concatenate(
        [
            trimesh.creation.cylinder(radius=0.09, height=h, sections=360).apply_translation(
                [x, 0, 0]
            )
            for x in (-0.12, 0.12)
        ]
    )
    legs.apply_transform(trimesh.transformations.rotation_matrix(-np.pi / 2, [1, 0, 0]))
    legs.apply_translation([0, h / 2, 0])
    assert abs(_leg_perimeter(legs, 0.5) * 100 - 2 * np.pi * 9) < 0.05
    print("ok", g, g2)
