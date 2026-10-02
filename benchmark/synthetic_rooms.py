"""Procedural synthetic room point-cloud generator.

Real sample captures have no ground truth (no laser/tape measurements exist for them), so they
can only be used as integration smoke tests. Quantitative gates, confidence calibration, and
the fix-loop all need *known* ground truth -- this module manufactures it directly rather than
going through a full photorealistic 3D renderer (far outside this project's scope): rooms are
specified as simple boxes with openings and rendered straight to a noisy, LiDAR-like
``WeightedPointCloud`` with known dimensions.

This is honestly disclosed as synthetic throughout the docs/benchmark report -- it is not
claimed to be real captured data.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from cozmoscan.types import WeightedPointCloud


@dataclass
class OpeningSpec:
    wall_index: int  # 0/1 = depth-walls (u=0/u=width), 2/3 = width-walls (v=0/v=depth)
    start_m: float
    width_m: float
    height_m: float
    sill_height_m: float
    kind: str = "door"  # "door" | "window"


@dataclass
class RoomSpec:
    room_id: str
    width_m: float
    depth_m: float
    height_m: float
    openings: list[OpeningSpec] = field(default_factory=list)


@dataclass
class SyntheticCaptureConfig:
    points_per_sqm: float = 900.0
    noise_std_m: float = 0.004
    outlier_frac: float = 0.01
    outlier_range_m: float = 3.0
    furniture_clusters: int = 0
    occlusion_patches_per_wall: int = 0
    occlusion_patch_size_m: float = 0.5
    rng_seed: int = 0


def _sample_plane(n: int, u_range: tuple[float, float], v_range: tuple[float, float], rng: np.random.Generator) -> np.ndarray:
    u = rng.uniform(*u_range, size=n)
    v = rng.uniform(*v_range, size=n)
    return np.stack([u, v], axis=1)


def _wall_points(spec: RoomSpec, wall_index: int, cfg: SyntheticCaptureConfig, rng: np.random.Generator) -> np.ndarray:
    """Points on one wall (x,z position-along-wall mapped to global-ish xz, y = height), with
    opening rectangles carved out.
    """
    if wall_index in (0, 1):
        length, const = spec.depth_m, (0.0 if wall_index == 0 else spec.width_m)
    else:
        length, const = spec.width_m, (0.0 if wall_index == 2 else spec.depth_m)

    area = length * spec.height_m
    n = max(200, int(area * cfg.points_per_sqm))
    pos = rng.uniform(0, length, size=n)
    h = rng.uniform(0, spec.height_m, size=n)

    keep = np.ones(n, dtype=bool)
    for o in spec.openings:
        if o.wall_index != wall_index:
            continue
        in_pos = (pos >= o.start_m) & (pos <= o.start_m + o.width_m)
        in_h = (h >= o.sill_height_m) & (h <= o.sill_height_m + o.height_m)
        keep &= ~(in_pos & in_h)

    for _ in range(cfg.occlusion_patches_per_wall):
        patch_pos = rng.uniform(0, max(length - cfg.occlusion_patch_size_m, 0.01))
        patch_h = rng.uniform(0, max(spec.height_m - cfg.occlusion_patch_size_m, 0.01))
        in_pos = (pos >= patch_pos) & (pos <= patch_pos + cfg.occlusion_patch_size_m)
        in_h = (h >= patch_h) & (h <= patch_h + cfg.occlusion_patch_size_m)
        keep &= ~(in_pos & in_h)

    pos, h = pos[keep], h[keep]

    if wall_index == 0:
        x, z = np.full_like(pos, const), pos
    elif wall_index == 1:
        x, z = np.full_like(pos, const), pos
    elif wall_index == 2:
        x, z = pos, np.full_like(pos, const)
    else:
        x, z = pos, np.full_like(pos, const)
    return np.stack([x, h, z], axis=1)


def generate_room_point_cloud(
    spec: RoomSpec,
    config: SyntheticCaptureConfig | None = None,
    global_offset_xz: tuple[float, float] = (0.0, 0.0),
    global_rotation_rad: float = 0.0,
) -> WeightedPointCloud:
    cfg = config or SyntheticCaptureConfig()
    rng = np.random.default_rng(cfg.rng_seed)

    parts = [_wall_points(spec, i, cfg, rng) for i in range(4)]

    n_floor = max(400, int(spec.width_m * spec.depth_m * cfg.points_per_sqm))
    floor_xz = _sample_plane(n_floor, (0, spec.width_m), (0, spec.depth_m), rng)
    parts.append(np.stack([floor_xz[:, 0], np.zeros(n_floor), floor_xz[:, 1]], axis=1))

    n_ceil = max(400, int(spec.width_m * spec.depth_m * cfg.points_per_sqm))
    ceil_xz = _sample_plane(n_ceil, (0, spec.width_m), (0, spec.depth_m), rng)
    parts.append(np.stack([ceil_xz[:, 0], np.full(n_ceil, spec.height_m), ceil_xz[:, 1]], axis=1))

    for _ in range(cfg.furniture_clusters):
        cx, cz = rng.uniform(0.3, spec.width_m - 0.3), rng.uniform(0.3, spec.depth_m - 0.3)
        box_w, box_d, box_h = rng.uniform(0.3, 0.8, size=3)
        n_box = 300
        bx = cx + rng.uniform(-box_w / 2, box_w / 2, n_box)
        bz = cz + rng.uniform(-box_d / 2, box_d / 2, n_box)
        by = rng.uniform(0, box_h, n_box)
        parts.append(np.stack([bx, by, bz], axis=1))

    points = np.concatenate(parts, axis=0).astype(np.float64)
    points += rng.normal(0, cfg.noise_std_m, size=points.shape)

    n_outliers = int(len(points) * cfg.outlier_frac)
    if n_outliers > 0:
        outliers = rng.uniform(-cfg.outlier_range_m, cfg.outlier_range_m, size=(n_outliers, 3))
        outliers[:, 0] += spec.width_m / 2
        outliers[:, 1] = np.abs(outliers[:, 1])
        outliers[:, 2] += spec.depth_m / 2
        points = np.concatenate([points, outliers], axis=0)

    c, s = np.cos(global_rotation_rad), np.sin(global_rotation_rad)
    rot = np.array([[c, -s], [s, c]])
    xz = points[:, [0, 2]] @ rot.T
    xz += np.array(global_offset_xz)
    points[:, 0], points[:, 2] = xz[:, 0], xz[:, 1]

    weights = np.ones(len(points), dtype=np.float32)
    return WeightedPointCloud(points=points.astype(np.float32), weights=weights, source_tier="lidar")
