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

    @staticmethod
    def from_dict(d: dict) -> "Measurement":
        return Measurement(value=d["value"], ci=d["ci"], method=d["method"])


@dataclass
class Opening:
    wall_index: int
    start_m: float  # offset along the wall from its first endpoint, meters
    width: Measurement
    height: Measurement
    kind: str  # "door" | "window" | "unknown"
    sill_height_m: float  # height of the gap's lower edge above the floor

    def as_dict(self) -> dict:
        return {
            "wall_index": self.wall_index,
            "start_m": round(self.start_m, 4),
            "width": self.width.as_dict(),
            "height": self.height.as_dict(),
            "kind": self.kind,
            "sill_height_m": round(self.sill_height_m, 4),
        }

    @staticmethod
    def from_dict(d: dict) -> "Opening":
        return Opening(
            wall_index=d["wall_index"],
            start_m=d["start_m"],
            width=Measurement.from_dict(d["width"]),
            height=Measurement.from_dict(d["height"]),
            kind=d["kind"],
            sill_height_m=d["sill_height_m"],
        )


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

    def as_dict(self) -> dict:
        return {
            "index": self.index,
            "p1": [round(float(v), 4) for v in self.p1],
            "p2": [round(float(v), 4) for v in self.p2],
            "length": self.length.as_dict(),
            "openings": [o.as_dict() for o in self.openings],
            "surface_id": self.surface_id,
        }

    @staticmethod
    def from_dict(d: dict) -> "Wall":
        return Wall(
            index=d["index"],
            p1=np.array(d["p1"], dtype=np.float64),
            p2=np.array(d["p2"], dtype=np.float64),
            length=Measurement.from_dict(d["length"]),
            openings=[Opening.from_dict(o) for o in d["openings"]],
            surface_id=d["surface_id"],
        )


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

    def as_dict(self) -> dict:
        return {
            "room_id": self.room_id,
            "tier": self.tier,
            "walls": [w.as_dict() for w in self.walls],
            "floor_polygon": [[round(float(x), 4), round(float(y), 4)] for x, y in self.floor_polygon],
            "ceiling_height": self.ceiling_height.as_dict() if self.ceiling_height is not None else None,
            "floor_area": self.floor_area.as_dict(),
            "transform_to_global": [[round(float(v), 6) for v in row] for row in self.transform_to_global],
            "point_count": self.point_count,
            "notes": self.notes,
            "meta": self.meta,
        }

    @staticmethod
    def from_dict(d: dict) -> "RoomModel":
        ch = d["ceiling_height"]
        return RoomModel(
            room_id=d["room_id"],
            tier=d["tier"],
            walls=[Wall.from_dict(w) for w in d["walls"]],
            floor_polygon=np.array(d["floor_polygon"], dtype=np.float64),
            ceiling_height=Measurement.from_dict(ch) if ch is not None else None,
            floor_area=Measurement.from_dict(d["floor_area"]),
            transform_to_global=np.array(d["transform_to_global"], dtype=np.float64),
            point_count=d["point_count"],
            notes=d.get("notes", []),
            meta=d.get("meta", {}),
        )


@dataclass
class DamageRegion:
    """One detected area of damage on one surface, in that surface's own 2D (u=along-surface,
    v=height) meters frame -- scale/placement is resolved by the caller (pipeline.py), the
    detector itself only sees pixels (cozmoscan.damage.detector.DamageDetection).
    """

    damage_class: str  # "moisture_stain" | "structural_crack" | "mold"
    surface_id: str
    polygon_xy: np.ndarray  # (K,2) meters, surface-local
    area_m2: float
    confidence: float
    extent_m: Optional[float] = None  # characteristic length, e.g. crack length (meters)
    concealed_risk: Optional[str] = None
    concealed_rule: Optional[str] = None

    def as_dict(self) -> dict:
        return {
            "damage_class": self.damage_class,
            "surface_id": self.surface_id,
            "polygon_xy": np.round(self.polygon_xy, 4).tolist(),
            "area_m2": round(self.area_m2, 4),
            "confidence": round(self.confidence, 3),
            "extent_m": round(self.extent_m, 4) if self.extent_m is not None else None,
            "concealed_risk": self.concealed_risk,
            "concealed_rule": self.concealed_rule,
        }

    @staticmethod
    def from_dict(d: dict) -> "DamageRegion":
        return DamageRegion(
            damage_class=d["damage_class"],
            surface_id=d["surface_id"],
            polygon_xy=np.array(d["polygon_xy"], dtype=np.float64),
            area_m2=d["area_m2"],
            confidence=d["confidence"],
            extent_m=d.get("extent_m"),
            concealed_risk=d.get("concealed_risk"),
            concealed_rule=d.get("concealed_rule"),
        )


@dataclass
class ScopeLineItem:
    """One repair line item produced by the deterministic scope rules engine."""

    surface_id: str
    damage_class: str
    description: str
    quantity: float
    unit: str
    rule: str

    def as_dict(self) -> dict:
        return {
            "surface_id": self.surface_id,
            "damage_class": self.damage_class,
            "description": self.description,
            "quantity": round(self.quantity, 2),
            "unit": self.unit,
            "rule": self.rule,
        }
