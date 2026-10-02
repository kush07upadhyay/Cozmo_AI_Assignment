"""Video tier: RGB video + ARKit VIO poses, **no** depth channel.

This is what a non-Pro iPhone 15 (no LiDAR) genuinely produces during an ARKit session: a
color video plus a 6DoF camera trajectory from visual-inertial odometry. We derive this tier
directly from the *same* real Stray Scanner captures used for the LiDAR tier by deliberately
discarding depth/confidence -- the room is real, only the sensing modality is downgraded, which
is the fairest possible apples-to-apples tier comparison available without a second physical
device.

Reconstruction: since there is no scene depth, sparse 3D points are recovered by tracking
corner features across consecutive keyframes (Lucas-Kanade optical flow) and triangulating them
with the known poses (linear DLT, cozmoscan.geometry.triangulation). This is deliberately a
*pairwise consecutive-keyframe* triangulation rather than full multi-frame bundle adjustment --
simpler, fast, and already sufficient to feed the shared Manhattan room-box fitter. See
docs/03_algorithms.md and docs/11_known_limitations.md for the honest accuracy trade-off this
implies versus the LiDAR tier.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from cozmoscan.capture.frame_utils import extract_frames
from cozmoscan.capture.stray_scanner import find_capture_root, load_per_frame_intrinsics, load_poses
from cozmoscan.geometry.triangulation import is_in_front, projection_matrix, reprojection_error, triangulate_dlt
from cozmoscan.types import CaptureBundle, WeightedPointCloud


@dataclass
class VideoTierConfig:
    min_translation_m: float = 0.07
    min_rotation_deg: float = 6.0
    max_frame_gap: int = 40
    max_keyframes: int = 220
    max_corners: int = 250
    quality_level: float = 0.015
    min_distance_px: int = 14
    lk_win_size: int = 21
    min_baseline_m: float = 0.04
    max_reproj_error_px: float = 2.5
    min_parallax_deg: float = 1.5
    max_point_distance_m: float = 12.0


def _select_keyframes_by_motion(poses, cfg: VideoTierConfig) -> list[int]:
    """Classic SLAM-style keyframe insertion: new keyframe once enough translation/rotation has
    accumulated (bounds inter-keyframe baseline so optical flow tracking doesn't just fail on
    long/fast captures), with a max-gap safety net for near-static stretches of the walk.

    The translation threshold is scaled up for long walkthroughs so the selection always spans
    the *entire* trajectory within ``max_keyframes`` -- a fixed threshold would silently stop
    once the budget ran out partway through a long scan, covering only the first portion of the
    room instead of all of it (caught via a before/after trajectory-coverage comparison on real
    sample data).
    """
    n = len(poses)
    pos = np.array([p.position for p in poses])
    path_len = float(np.sum(np.linalg.norm(np.diff(pos, axis=0), axis=1)))
    min_translation_m = max(cfg.min_translation_m, path_len / cfg.max_keyframes) if path_len > 0 else cfg.min_translation_m

    indices = [0]
    last = poses[0]
    i = 1
    while i < n:
        dp = float(np.linalg.norm(poses[i].position - last.position))
        dot = min(1.0, abs(float(np.dot(poses[i].quaternion_xyzw, last.quaternion_xyzw))))
        dtheta_deg = float(np.degrees(2 * np.arccos(dot)))
        gap = i - indices[-1]
        if dp >= min_translation_m or dtheta_deg >= cfg.min_rotation_deg or gap >= cfg.max_frame_gap:
            indices.append(i)
            last = poses[i]
        i += 1
    if indices[-1] != n - 1:
        indices.append(n - 1)
    return indices


def _extract_frames_gray(video_path, frame_indices: list[int]) -> dict[int, np.ndarray]:
    return {i: cv2.cvtColor(f, cv2.COLOR_BGR2GRAY) for i, f in extract_frames(video_path, frame_indices).items()}


def load_video_capture(capture_dir, room_id: str, config: VideoTierConfig | None = None) -> CaptureBundle:
    cfg = config or VideoTierConfig()
    root = find_capture_root(capture_dir)
    poses = load_poses(root)
    intrinsics = load_per_frame_intrinsics(root)
    n = len(poses)

    indices = _select_keyframes_by_motion(poses, cfg)
    frames = _extract_frames_gray(root / "rgb.mp4", indices)
    indices = [i for i in indices if i in frames]

    all_points, all_weights = [], []
    for a, b in zip(indices[:-1], indices[1:]):
        baseline = np.linalg.norm(poses[b].position - poses[a].position)
        if baseline < cfg.min_baseline_m:
            continue
        corners = cv2.goodFeaturesToTrack(
            frames[a], maxCorners=cfg.max_corners, qualityLevel=cfg.quality_level, minDistance=cfg.min_distance_px
        )
        if corners is None or len(corners) == 0:
            continue
        tracked, status, _ = cv2.calcOpticalFlowPyrLK(
            frames[a], frames[b], corners, None, winSize=(cfg.lk_win_size, cfg.lk_win_size), maxLevel=3
        )
        status = status.reshape(-1).astype(bool)
        pts_a = corners.reshape(-1, 2)[status]
        pts_b = tracked.reshape(-1, 2)[status]
        if len(pts_a) == 0:
            continue

        p_a = projection_matrix(poses[a], intrinsics[a])
        p_b = projection_matrix(poses[b], intrinsics[b])
        for (ua, va), (ub, vb) in zip(pts_a, pts_b):
            try:
                x = triangulate_dlt([(p_a, ua, va), (p_b, ub, vb)])
            except np.linalg.LinAlgError:
                continue
            if not (is_in_front(x, poses[a]) and is_in_front(x, poses[b])):
                continue
            err_a = reprojection_error(x, p_a, ua, va)
            err_b = reprojection_error(x, p_b, ub, vb)
            max_err = max(err_a, err_b)
            if max_err > cfg.max_reproj_error_px:
                continue

            cam_a, cam_b = poses[a].position, poses[b].position
            dist_a = float(np.linalg.norm(x - cam_a))
            dist_b = float(np.linalg.norm(x - cam_b))
            if dist_a > cfg.max_point_distance_m or dist_b > cfg.max_point_distance_m:
                continue
            cos_parallax = np.clip(np.dot((x - cam_a) / dist_a, (x - cam_b) / dist_b), -1.0, 1.0)
            parallax_deg = float(np.degrees(np.arccos(cos_parallax)))
            if parallax_deg < cfg.min_parallax_deg:
                continue

            all_points.append(x)
            all_weights.append(1.0 / (1.0 + max_err))

    if not all_points:
        raise RuntimeError(f"Video-tier triangulation produced zero points for {room_id!r}")

    points = np.array(all_points, dtype=np.float32)
    weights = np.array(all_weights, dtype=np.float32)
    cloud = WeightedPointCloud(points=points, weights=weights, source_tier="video")
    return CaptureBundle(
        capture_id=root.name,
        room_id=room_id,
        tier="video",
        source_dir=root,
        point_cloud=cloud,
        poses=[poses[i] for i in indices],
        meta={
            "total_frames": n,
            "keyframes_used": len(indices),
            "triangulated_points": int(points.shape[0]),
            "note": "depth/confidence channels deliberately discarded to emulate a non-LiDAR iPhone",
        },
    )
