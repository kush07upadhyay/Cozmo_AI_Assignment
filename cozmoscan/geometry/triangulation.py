"""Multi-view linear triangulation (DLT) -- shared by the video tier (and reusable for any
future posed-but-depthless source). Kept tier-agnostic on purpose.
"""
from __future__ import annotations

import numpy as np

from cozmoscan.types import Intrinsics, Pose


def projection_matrix(pose: Pose, intr: Intrinsics) -> np.ndarray:
    """World-point -> pixel projection matrix P = K [R_wc | t_wc], 3x4."""
    k = np.array([[intr.fx, 0, intr.cx], [0, intr.fy, intr.cy], [0, 0, 1]])
    r_cw = pose.rotation_matrix()  # camera-to-world
    r_wc = r_cw.T
    t_wc = -r_wc @ pose.position
    extrinsic = np.concatenate([r_wc, t_wc.reshape(3, 1)], axis=1)
    return k @ extrinsic


def triangulate_dlt(observations: list[tuple[np.ndarray, float, float]]) -> np.ndarray:
    """observations: list of (3x4 projection matrix, pixel_u, pixel_v). Returns world XYZ (3,)."""
    rows = []
    for p, u, v in observations:
        rows.append(u * p[2] - p[0])
        rows.append(v * p[2] - p[1])
    a = np.stack(rows, axis=0)
    _, _, vt = np.linalg.svd(a)
    x = vt[-1]
    return x[:3] / x[3]


def reprojection_error(point_world: np.ndarray, p: np.ndarray, u: float, v: float) -> float:
    homog = np.append(point_world, 1.0)
    proj = p @ homog
    if abs(proj[2]) < 1e-9:
        return float("inf")
    pred = proj[:2] / proj[2]
    return float(np.hypot(pred[0] - u, pred[1] - v))


def is_in_front(point_world: np.ndarray, pose: Pose) -> bool:
    r_cw = pose.rotation_matrix()
    cam_pt = r_cw.T @ (point_world - pose.position)
    return cam_pt[2] > 0.05
