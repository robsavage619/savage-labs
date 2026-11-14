"""Fit one MHR body to a front and a side photo at a known stature; read girths off it.

No renderer: a solid's projection lies inside its silhouette, so every projected
surface point is pulled into the mask (distance-transform term) and every silhouette
contour point is pulled onto the nearest projected surface point (coverage term).
Shape and skeleton proportions are shared by both views; pose and camera are per view.
Absolute size comes only from the stature: shape fixes proportions, height fixes scale.

Called by run.py; `fit.py PREP.npz FRONT SIDE STATURE_CM` fits one prepared pair.
"""

from __future__ import annotations

import argparse
import logging
import math
import time
from pathlib import Path

import numpy as np
import pooch
import torch
from mhr.mhr import MHR
from scipy.ndimage import distance_transform_edt

import tape

log = logging.getLogger("body-mesh")

# MHR v1.0.1 assets (Apache-2.0), pinned by hash. Only the LOD-3 files are kept.
_ASSETS_URL = "https://github.com/facebookresearch/MHR/releases/download/v1.0.1/assets.zip"
_ASSETS_SHA256 = "e4f4f205cd87c0fa106577ba1de4fc763e4eb197c924461d2ef7e6944e9d6b94"
_LOD3_FILES = [
    "assets/compact_v6_1.model",
    "assets/lod3.fbx",
    "assets/corrective_blendshapes_lod3.npz",
    "assets/corrective_activation.npz",
    "assets/LICENSE.txt",
]


def assets_dir() -> Path:
    """Folder holding the MHR LOD-3 files, downloading the 199 MB archive once if needed."""
    root = Path(__file__).parent / "assets"
    if not (root / "assets" / "lod3.fbx").exists():
        zipped = pooch.retrieve(
            _ASSETS_URL,
            known_hash=f"sha256:{_ASSETS_SHA256}",
            path=root,
            fname="assets.zip",
            processor=pooch.Unzip(members=_LOD3_FILES, extract_dir=str(root)),
        )
        del zipped
        (root / "assets.zip").unlink(missing_ok=True)
    return root / "assets"


NAVEL_VERTEX = 1436  # front-midline vertex at 60% of stature on the MHR template (LOD 3)
N_SHAPE = 20  # MHR's body identity coefficients; the other 25 are face and hands
FOCAL_35MM = 30.0  # EXIF FocalLengthIn35mmFilm of the iPhone front camera

# BlazePose landmark -> MHR joint.
KP_TO_JOINT = {
    11: "l_uparm",
    12: "r_uparm",
    13: "l_lowarm",
    14: "r_lowarm",
    15: "l_wrist",
    16: "r_wrist",
    23: "l_upleg",
    24: "r_upleg",
    25: "l_lowleg",
    26: "r_lowleg",
    27: "l_talocrural",
    28: "r_talocrural",
}
SCALE_PARAMS = [
    "scale_spine_length",
    "scale_neck_length",
    "scale_shoulder_width",
    "scale_uparms",
    "scale_lowarms",
    "scale_hip_width",
    "scale_hip_height",
    "scale_hip_depth",
    "scale_uplegs",
    "scale_lowlegs",
]
POSE_PREFIXES = (
    "root_r",
    "spine",
    "neck",
    "head",
    "r_clavicle",
    "l_clavicle",
    "r_uparm",
    "l_uparm",
    "r_elbow",
    "l_elbow",
    "r_lowarm",
    "l_lowarm",
    "r_upleg",
    "l_upleg",
    "r_knee",
    "l_knee",
)


class View:
    """One photo: silhouette, its distance transform, contour points and keypoints."""

    def __init__(self, mask: np.ndarray, kp: np.ndarray) -> None:
        h, w = mask.shape
        self.h, self.w = h, w
        self.dt = torch.tensor(distance_transform_edt(~mask), dtype=torch.float32)[None, None]
        edge = mask & ~np.pad(mask, 1)[2:, 1:-1] | mask & ~np.pad(mask, 1)[:-2, 1:-1]
        edge |= mask & ~np.pad(mask, 1)[1:-1, 2:] | mask & ~np.pad(mask, 1)[1:-1, :-2]
        ys, xs = np.where(edge)
        keep = (ys > 2) & (ys < h - 3) & (xs > 2) & (xs < w - 3)  # frame cuts are not body edges
        pts = np.stack([xs[keep], ys[keep]], 1).astype(np.float32)
        step = max(1, len(pts) // 1500)
        self.contour = torch.tensor(pts[::step])
        self.kp = torch.tensor(kp)
        self.last_uv = torch.empty(0, 2)  # last projected surface points, for the overlay
        # 30 mm equivalent: long side of a 36x24 frame's 43.3 mm diagonal at 4:3 is 34.6 mm.
        self.f = (max(h, w) / 2) / ((34.6 / 2) / FOCAL_35MM)

    def project(self, pts: torch.Tensor, yaw, pitch, t, log_d) -> torch.Tensor:
        cy, sy = torch.cos(yaw), torch.sin(yaw)
        cp, sp = torch.cos(pitch), torch.sin(pitch)
        x = cy * pts[:, 0] + sy * pts[:, 2]
        z = -sy * pts[:, 0] + cy * pts[:, 2]
        y = cp * pts[:, 1] - sp * z
        z = sp * pts[:, 1] + cp * z
        depth = torch.exp(log_d) - z
        u = self.f * (x + t[0]) / depth + self.w / 2
        v = self.h / 2 - self.f * (y + t[1]) / depth
        return torch.stack([u, v], 1)

    def silhouette_loss(self, uv: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        inside = (
            (uv[:, 0] >= 0) & (uv[:, 0] <= self.w - 1) & (uv[:, 1] >= 0) & (uv[:, 1] <= self.h - 1)
        )
        q = uv[inside]
        grid = torch.stack([q[:, 0] / (self.w - 1) * 2 - 1, q[:, 1] / (self.h - 1) * 2 - 1], 1)
        out = torch.nn.functional.grid_sample(self.dt, grid[None, None], align_corners=True)
        l_in = (out**2).mean()
        d = torch.cdist(self.contour, uv)
        l_cov = (d.min(1).values ** 2).mean()
        return l_in, l_cov


def fit(
    npz: Path,
    front: str,
    side: str,
    stature_cm: float,
    iters: int = 500,
    quiet: bool = False,
    overlay: Path | None = None,
):
    """Fit and return (girths, mean-shape girths, final losses)."""
    torch.manual_seed(0)
    data = np.load(npz)
    views = [View(data[f"{s}_mask"], data[f"{s}_kp"]) for s in (front, side)]
    model = MHR.from_files(folder=assets_dir(), device=torch.device("cpu"), lod=3)
    names = list(model.character.parameter_transform.names)[:204]
    joints = list(model.character.skeleton.joint_names)
    faces = torch.tensor(np.asarray(model.character.mesh.faces), dtype=torch.long)
    kp_idx = torch.tensor(list(KP_TO_JOINT))
    joint_idx = torch.tensor([joints.index(j) for j in KP_TO_JOINT.values()])
    pose_idx = [
        i for i, n in enumerate(names) if n.startswith(POSE_PREFIXES) and "flexible" not in n
    ]
    scale_idx = [names.index(n) for n in SCALE_PARAMS]
    zero_face = torch.zeros(1, 72)

    beta = torch.zeros(N_SHAPE, requires_grad=True)
    scales = torch.zeros(len(scale_idx), requires_grad=True)
    poses = [torch.zeros(len(pose_idx), requires_grad=True) for _ in views]
    cams = []
    for yaw0 in (0.0, None):
        cams.append(
            {
                "yaw": torch.tensor(yaw0 if yaw0 is not None else 0.0, requires_grad=True),
                "pitch": torch.tensor(0.0, requires_grad=True),
                "t": torch.zeros(2, requires_grad=True),
                "log_d": torch.tensor(math.log(300.0), requires_grad=True),
            }
        )

    def bodies():
        """Neutral body plus one posed body per view, in a single batched forward.

        One call, not three: separate calls inside one autograd graph fail backward
        with an in-place modification error from MHR's forward.
        """
        n = 1 + len(views)
        ident = torch.zeros(n, 45)
        ident[:, :N_SHAPE] = beta
        params = torch.zeros(n, 204)
        params[:, scale_idx] = scales
        for i, pose in enumerate(poses, start=1):
            params[i, pose_idx] = pose
        verts, sk = model(ident, params, torch.zeros(n, 72))
        return verts, sk[:, :, :3]

    def scaled(verts: torch.Tensor, joints_pos: torch.Tensor, k: torch.Tensor):
        floor = verts[:, 1].min()
        shift = torch.tensor([0.0, 1.0, 0.0]) * floor
        return (verts - shift) * k, (joints_pos - shift) * k

    def samples(verts: torch.Tensor) -> torch.Tensor:
        return torch.cat([verts, verts[faces].mean(1)], 0)

    def losses(stage: int):
        all_verts, all_joints = bodies()
        neutral = all_verts[0]
        k = stature_cm / (neutral[:, 1].max() - neutral[:, 1].min())
        total = torch.tensor(0.0)
        parts = []
        for i, (view, pose, cam) in enumerate(zip(views, poses, cams, strict=True), start=1):
            verts, jpos = scaled(all_verts[i], all_joints[i], k)
            # Centre the body on its own pelvis so camera translation starts near zero.
            centre = jpos[joints.index("root")]
            uv_j = view.project(
                jpos[joint_idx] - centre, cam["yaw"], cam["pitch"], cam["t"], cam["log_d"]
            )
            vis = view.kp[kp_idx, 2]
            ok = (vis > 0.5) & (view.kp[kp_idx, 1] < view.h)
            l_kp = (((uv_j - view.kp[kp_idx, :2]) ** 2).sum(1) * ok).sum() / ok.sum().clamp(min=1)
            total = total + l_kp / view.h**2 * (1.0 if stage == 1 else 0.05)
            if stage == 2:
                uv = view.project(
                    samples(verts) - centre, cam["yaw"], cam["pitch"], cam["t"], cam["log_d"]
                )
                l_in, l_cov = view.silhouette_loss(uv)
                view.last_uv = uv.detach()
                total = total + (l_in + l_cov) / view.h**2
                parts.append((float(l_in) ** 0.5, float(l_cov) ** 0.5))
            total = total + 1e-3 * (pose**2).sum()
        total = total + 1e-4 * (beta**2).sum() + 1e-3 * (scales**2).sum()
        return total, parts, k

    def reset(yaw_side: float) -> None:
        with torch.no_grad():
            beta.zero_()
            scales.zero_()
            for p in poses:
                p.zero_()
            for c, yaw in zip(cams, (0.0, yaw_side), strict=True):
                c["yaw"].fill_(yaw)
                c["pitch"].fill_(0.0)
                c["t"].zero_()
                c["log_d"].fill_(math.log(300.0))

    def fit_pose_to_keypoints() -> float:
        cam_params = [x for c in cams for x in c.values()]
        opt = torch.optim.Adam([{"params": poses + cam_params, "lr": 0.03}])
        for _ in range(150):
            opt.zero_grad()
            loss, _, _ = losses(1)
            loss.backward()
            opt.step()
        return float(loss.detach())

    # Side view: the body faces left or right in the photo; try both, keep the better.
    side_yaw = min(
        (math.pi / 2, -math.pi / 2), key=lambda y: (reset(y), fit_pose_to_keypoints())[1]
    )
    reset(side_yaw)
    fit_pose_to_keypoints()

    cam_params = [x for c in cams for x in c.values()]
    opt = torch.optim.Adam(
        [
            {"params": [beta], "lr": 0.05},
            {"params": [scales], "lr": 0.01},
            {"params": poses + cam_params, "lr": 0.01},
        ]
    )
    t0 = time.time()
    for i in range(iters):
        opt.zero_grad()
        loss, parts, k = losses(2)
        loss.backward()
        opt.step()
        if not quiet and (i % 100 == 0 or i == iters - 1):
            px = " ".join(f"in={a:.1f}px cov={b:.1f}px" for a, b in parts)
            log.info("  it %4d loss %.5f  %s  (%.0fs)", i, float(loss), px, time.time() - t0)

    # Measure with arms raised (T-pose) so no slice cuts through an arm.
    def measure_mesh(b: torch.Tensor, sc: torch.Tensor) -> tape.Girths:
        with torch.no_grad():
            ident = torch.zeros(1, 45)
            ident[0, :N_SHAPE] = b
            params = torch.zeros(1, 204)
            params[0, scale_idx] = sc
            neutral, _ = model(ident, params, zero_face)
            k_ = stature_cm / (neutral[0, :, 1].max() - neutral[0, :, 1].min())
            for side in ("l", "r"):
                best_val = None
                for sign in (1.0, -1.0):
                    params[0, names.index(f"{side}_uparm_ry")] = sign * 0.8
                    _, sk = model(ident, params, zero_face)
                    x = abs(float(sk[0, joints.index(f"{side}_wrist"), 0]))
                    if best_val is None or x > best_val[0]:
                        best_val = (x, sign)
                params[0, names.index(f"{side}_uparm_ry")] = best_val[1] * 0.8
            verts, sk = model(ident, params, zero_face)
            v, floor = verts[0], verts[0][:, 1].min()
            v = (v - torch.tensor([0.0, 1.0, 0.0]) * floor) * k_ / 100.0  # metres
            hip_y = float(sk[0, joints.index("l_upleg"), 1] - floor) * float(k_) / 100
            knee_y = float(sk[0, joints.index("l_lowleg"), 1] - floor) * float(k_) / 100
        return tape.measure(
            v.numpy().astype(np.float64),
            faces.numpy(),
            navel_y=float(v[NAVEL_VERTEX, 1]),
            thigh_y=(hip_y + knee_y) / 2,
        )

    if overlay is not None:
        from PIL import Image

        tiles = []
        for view in views:
            img = np.zeros((view.h, view.w, 3), np.uint8)
            img[np.asarray(view.dt[0, 0]) == 0] = (70, 70, 70)
            uv = view.last_uv.numpy().round().astype(int)
            ok = (uv[:, 0] >= 0) & (uv[:, 0] < view.w) & (uv[:, 1] >= 0) & (uv[:, 1] < view.h)
            img[uv[ok, 1], uv[ok, 0]] = (230, 80, 60)
            c = view.contour.numpy().astype(int)
            img[c[:, 1], c[:, 0]] = (120, 220, 255)
            tiles.append(img)
        Image.fromarray(np.concatenate(tiles, 1)).save(overlay)

    fit.measure_mesh = measure_mesh  # re-measure saved fits without refitting
    fitted = measure_mesh(beta.detach(), scales.detach())
    mean = measure_mesh(torch.zeros(N_SHAPE), torch.zeros(len(scale_idx)))
    return fitted, mean, parts, side_yaw, beta.detach().numpy(), scales.detach().numpy()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("npz", type=Path)
    ap.add_argument("front")
    ap.add_argument("side")
    ap.add_argument("stature_cm", type=float)
    ap.add_argument("--iters", type=int, default=500)
    ap.add_argument("--overlay", type=Path)
    a = ap.parse_args()
    fitted, mean, _, yaw, beta, _ = fit(
        a.npz, a.front, a.side, a.stature_cm, a.iters, overlay=a.overlay
    )
    log.info("side yaw %+.0f deg; shape %s", math.degrees(yaw), np.round(beta[:6], 2))
    for label, g in (("fitted", fitted), ("mean-shape", mean)):
        log.info(
            "%-11s waist %.1f  chest %.1f  hip %.1f  mid-thigh %.1f cm  implied mass %.1f kg",
            label,
            g.waist_cm,
            g.chest_cm,
            g.hip_cm,
            g.thigh_cm,
            g.implied_mass_kg,
        )


if __name__ == "__main__":
    main()
