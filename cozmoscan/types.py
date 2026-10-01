"""Core data types shared across all tiers and pipeline stages.

Design note: every tier (photo / video / lidar) converges on the same two
intermediate representations -- a weighted 3D point cloud plus an optional
camera trajectory -- before the shared geometry/reconstruction code ever runs.
This is what lets "the same output contract from each tier" (per the case
study brief) be an architectural property instead of a per-tier special case.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional

import numpy as np

Tier = Literal["photo", "video", "lidar"]


@dataclass
class Pose:
    """Camera-to-world rigid transform at one instant."""

    timestamp: float
    position: np.ndarray  # (3,) meters, world/ARKit frame
    quaternion_xyzw: np.ndarray  # (4,)

    def rotation_matrix(self) -> np.ndarray:
        x, y, z, w = self.quaternion_xyzw
        return np.array(
            [
                [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
            ]
        )

    def camera_to_world(self, points_cam: np.ndarray) -> np.ndarray:
        """points_cam: (N,3) in camera frame -> (N,3) in world frame."""
        return points_cam @ self.rotation_matrix().T + self.position


@dataclass
class Intrinsics:
    fx: float
    fy: float
    cx: float
    cy: float
    width: int
    height: int

    def scaled_to(self, width: int, height: int) -> "Intrinsics":
        sx, sy = width / self.width, height / self.height
        return Intrinsics(self.fx * sx, self.fy * sy, self.cx * sx, self.cy * sy, width, height)


@dataclass
class WeightedPointCloud:
    """Unified point representation consumed by the geometry/reconstruction layer."""

    points: np.ndarray  # (N,3) float32, meters, world/room-local frame
    weights: np.ndarray  # (N,) float32 in [0,1], higher = more trusted
    source_tier: Tier
    labels: Optional[np.ndarray] = None  # optional (N,) str/int surface labels (debug/eval only)

    def __len__(self) -> int:
        return int(self.points.shape[0])


@dataclass
class CaptureBundle:
    """Everything the reconstruction stage needs for one room, for one tier."""

    capture_id: str
    room_id: str
    tier: Tier
    source_dir: Path
    point_cloud: WeightedPointCloud
    poses: list[Pose] = field(default_factory=list)
    photo_paths: list[Path] = field(default_factory=list)
    meta: dict = field(default_factory=dict)


@dataclass
class Measurement:
    """A single scalar with a calibrated confidence interval and a traceable method tag."""

    value: float
    ci: float  # +/- half-width, same units as value
    method: str  # e.g. "lidar_plane_residual_x_k2.0" -- feeds docs/07_benchmark_methodology.md

    def as_dict(self) -> dict:
        return {"value": round(self.value, 4), "ci": round(self.ci, 4), "method": self.method}


@dataclass
class Opening:
    wall_index: int
    start_m: float  # offset along the wall from its first endpoint, meters
    width: Measurement
    height: Measurement
    kind: str  # "door" | "window" | "unknown"
    sill_height_m: float  # height of the gap's lower edge above the floor


@dataclass
class Wall:
    index: int
    p1: np.ndarray  # (2,) room-local xy, meters
    p2: np.ndarray
    length: Measurement
    openings: list[Opening] = field(default_factory=list)
    surface_id: str = ""

    def __post_init__(self) -> None:
        if not self.surface_id:
            self.surface_id = f"wall_{self.index}"

    def direction(self) -> np.ndarray:
        d = self.p2 - self.p1
        n = np.linalg.norm(d)
        return d / n if n > 1e-9 else d


@dataclass
class RoomModel:
    room_id: str
    tier: Tier
    walls: list[Wall]
    floor_polygon: np.ndarray  # (K,2) room-local xy, meters (closed order)
    ceiling_height: Optional[Measurement]
    floor_area: Measurement
    transform_to_global: np.ndarray  # (3,3) homogeneous 2D rigid transform, room-local -> global xy
    point_count: int
    notes: list[str] = field(default_factory=list)
    meta: dict = field(default_factory=dict)

    def to_global_xy(self, pts_local_xy: np.ndarray) -> np.ndarray:
        homog = np.concatenate([pts_local_xy, np.ones((len(pts_local_xy), 1))], axis=1)
        return (homog @ self.transform_to_global.T)[:, :2]
