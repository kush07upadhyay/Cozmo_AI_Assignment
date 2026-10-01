"""Parser for Stray Scanner (strayrobots/scanner, free iOS App Store LiDAR logger) exports.

This is the exact on-disk format of the three real sample captures shipped in
``Sample_data_to_run_code/`` -- confirmed by direct inspection:

    <capture>/
        camera_matrix.csv      3x3 RGB intrinsics (fx,0,cx / 0,fy,cy / 0,0,1)
        odometry.csv           per-frame ARKit pose (x,y,z,qx,qy,qz,qw) + per-frame intrinsics
        imu.csv                raw accelerometer/gyro (unused by reconstruction, kept for provenance)
        rgb.mp4                color video, 1920x1440 @ ~45fps
        depth/000123.png       16-bit depth in millimeters, 256x192 (ARKit sceneDepth resolution)
        confidence/000123.png  8-bit confidence, values {0,1,2} = {low,medium,high} (ARConfidenceLevel)

This is also the app named in the Route 2 stock-capture protocol (docs/04_capture_protocol.md).
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from cozmoscan.types import CaptureBundle, Intrinsics, Pose, WeightedPointCloud

MIN_CONFIDENCE_DEFAULT = 1  # keep medium (1) + high (2) ARKit confidence samples


@dataclass
class StrayScannerConfig:
    frame_stride: int | None = None  # None -> auto, targets ~TARGET_FRAMES processed frames
    pixel_stride: int = 6
    min_confidence: int = MIN_CONFIDENCE_DEFAULT
    voxel_size_m: float = 0.01
    target_frames: int = 220


def find_capture_root(path: Path) -> Path:
    """Stray Scanner zips contain one hash-named subfolder; accept either level."""
    path = Path(path)
    if (path / "odometry.csv").exists():
        return path
    candidates = [p for p in path.iterdir() if p.is_dir() and (p / "odometry.csv").exists()]
    if not candidates:
        raise FileNotFoundError(f"No Stray Scanner capture (odometry.csv) found under {path}")
    return candidates[0]


def _read_camera_matrix(root: Path) -> np.ndarray:
    rows = []
    with open(root / "camera_matrix.csv", newline="") as f:
        for row in csv.reader(f):
            rows.append([float(v) for v in row if v.strip() != ""])
    return np.array(rows, dtype=np.float64)


def _read_odometry(root: Path) -> list[dict]:
    with open(root / "odometry.csv", newline="") as f:
        reader = csv.DictReader(f, skipinitialspace=True)
        return [row for row in reader]


def load_poses(root: Path) -> list[Pose]:
    rows = _read_odometry(root)
    poses = []
    for row in rows:
        pos = np.array([float(row["x"]), float(row["y"]), float(row["z"])])
        quat = np.array([float(row["qx"]), float(row["qy"]), float(row["qz"]), float(row["qw"])])
        poses.append(Pose(timestamp=float(row["timestamp"]), position=pos, quaternion_xyzw=quat))
    return poses


def load_rgb_intrinsics(root: Path) -> Intrinsics:
    """Intrinsics at RGB (video) resolution, from camera_matrix.csv + rgb.mp4 header."""
    import cv2

    m = _read_camera_matrix(root)
    cap = cv2.VideoCapture(str(root / "rgb.mp4"))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    return Intrinsics(fx=m[0, 0], fy=m[1, 1], cx=m[0, 2], cy=m[1, 2], width=width, height=height)


def _voxel_downsample(points: np.ndarray, weights: np.ndarray, voxel_size_m: float) -> tuple[np.ndarray, np.ndarray]:
    if len(points) == 0:
        return points, weights
    keys = np.floor(points / voxel_size_m).astype(np.int64)
    # pack 3 int keys into one hashable row via structured view for fast unique
    order = np.lexsort((keys[:, 2], keys[:, 1], keys[:, 0]))
    keys_sorted = keys[order]
    pts_sorted = points[order]
    w_sorted = weights[order]
    change = np.any(np.diff(keys_sorted, axis=0) != 0, axis=1)
    group_start = np.concatenate(([0], np.nonzero(change)[0] + 1))
    group_end = np.concatenate((group_start[1:], [len(keys_sorted)]))
    out_pts = np.empty((len(group_start), 3), dtype=points.dtype)
    out_w = np.empty((len(group_start),), dtype=weights.dtype)
    for i, (s, e) in enumerate(zip(group_start, group_end)):
        seg_w = w_sorted[s:e]
        out_pts[i] = np.average(pts_sorted[s:e], axis=0, weights=seg_w)
        out_w[i] = seg_w.max()
    return out_pts, out_w


def load_lidar_capture(capture_dir: Path, room_id: str, config: StrayScannerConfig | None = None) -> CaptureBundle:
    """Parse a Stray Scanner directory into a unified, room-local LiDAR CaptureBundle."""
    config = config or StrayScannerConfig()
    root = find_capture_root(Path(capture_dir))
    poses = load_poses(root)
    rgb_intr = load_rgb_intrinsics(root)

    depth_files = sorted((root / "depth").glob("*.png"))
    n_frames = len(depth_files)
    if n_frames == 0:
        raise FileNotFoundError(f"No depth frames under {root / 'depth'}")

    frame_stride = config.frame_stride or max(1, n_frames // config.target_frames)
    ps = config.pixel_stride

    sample0 = np.array(Image.open(depth_files[0]))
    depth_h, depth_w = sample0.shape
    depth_intr = rgb_intr.scaled_to(depth_w, depth_h)

    # pixel grid (constant across frames) for unprojection, strided for performance
    us = np.arange(0, depth_w, ps)
    vs = np.arange(0, depth_h, ps)
    grid_u, grid_v = np.meshgrid(us, vs)
    grid_u = grid_u.ravel()
    grid_v = grid_v.ravel()
    x_norm = (grid_u - depth_intr.cx) / depth_intr.fx
    y_norm = (grid_v - depth_intr.cy) / depth_intr.fy

    all_points = []
    all_weights = []
    conf_dir = root / "confidence"
    used_frames = 0
    for idx in range(0, n_frames, frame_stride):
        depth_png = depth_files[idx]
        frame_num = depth_png.stem
        conf_png = conf_dir / f"{frame_num}.png"
        depth_mm = np.array(Image.open(depth_png))[grid_v, grid_u].astype(np.float32)
        conf = (
            np.array(Image.open(conf_png))[grid_v, grid_u]
            if conf_png.exists()
            else np.full_like(depth_mm, 2, dtype=np.uint8)
        )
        valid = (depth_mm > 0) & (conf >= config.min_confidence)
        if not np.any(valid):
            continue
        z = depth_mm[valid] / 1000.0  # mm -> m
        x_cam = x_norm[valid] * z
        y_cam = y_norm[valid] * z
        points_cam = np.stack([x_cam, y_cam, z], axis=1)
        pose = poses[int(frame_num)] if int(frame_num) < len(poses) else poses[-1]
        points_world = pose.camera_to_world(points_cam)
        weight = np.where(conf[valid] >= 2, 1.0, 0.5).astype(np.float32)
        all_points.append(points_world)
        all_weights.append(weight)
        used_frames += 1

    points = np.concatenate(all_points, axis=0).astype(np.float32)
    weights = np.concatenate(all_weights, axis=0).astype(np.float32)
    points, weights = _voxel_downsample(points, weights, config.voxel_size_m)

    cloud = WeightedPointCloud(points=points, weights=weights, source_tier="lidar")
    return CaptureBundle(
        capture_id=root.name,
        room_id=room_id,
        tier="lidar",
        source_dir=root,
        point_cloud=cloud,
        poses=poses,
        meta={
            "n_frames_total": n_frames,
            "n_frames_used": used_frames,
            "frame_stride": frame_stride,
            "pixel_stride": ps,
            "depth_resolution": [depth_w, depth_h],
            "rgb_resolution": [rgb_intr.width, rgb_intr.height],
            "point_count": int(points.shape[0]),
        },
    )
