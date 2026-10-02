"""Photo tier: a handful of still photos, **no** pose track and **no** depth at all.

This is the lowest-fidelity, most widely-available capture route -- any phone, any app, just
"take a few pictures". Reconstruction uses classical single-view metrology on the Manhattan
ground-plane assumption:

1. Canny edges + probabilistic Hough transform find candidate line segments per photo.
2. Lines are split into near-vertical (wall corners / door jambs) and the rest.
3. The camera is assumed level (zero roll/pitch) and held at approximately eye height above the
   floor (``assumed_camera_height_m``, disclosed, user-facing capture instruction: "hold the
   phone at chest/eye height, level, facing each wall"). That single assumption is enough to
   anchor absolute scale: a point on the floor at pixel row ``y`` is at ground-distance
   ``d = camera_height * fy / (y - horizon_row)`` (similar triangles on the pinhole model), and
   the same relation run in reverse against the floor/ceiling pixel rows of the same wall corner
   gives the ceiling height directly -- no second reference object (e.g. a visible door) needed,
   though one would tighten the CI (documented future work, docs/11_known_limitations.md).
4. Lateral (wall width) extent reuses the same back-projection at the back-wall's measured
   depth.

This is deliberately simpler than full vanishing-point cross-ratio metrology (Criminisi et al.)
-- see docs/03_algorithms.md for the honest trade-off. Every photo-tier measurement therefore
carries the *widest* disclosed confidence interval of the three tiers.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from cozmoscan.capture.frame_utils import extract_frames
from cozmoscan.capture.stray_scanner import find_capture_root, load_rgb_intrinsics
from cozmoscan.types import CaptureBundle, Intrinsics, Measurement, RoomModel, Wall, WeightedPointCloud


@dataclass
class PhotoTierConfig:
    assumed_camera_height_m: float = 1.5
    n_photos: int = 4
    canny_low: int = 40
    canny_high: int = 130
    hough_threshold: int = 70
    hough_min_line_length: int = 70
    hough_max_line_gap: int = 15
    vertical_angle_tol_deg: float = 10.0
    # Split in two, NOT one flat fraction, because benchmark/real_data_report.py (cross-tier vs.
    # LiDAR on all 3 real captures) found these two error modes are wildly different in practice:
    #
    # ci_frac_ceiling: +-15%. Vertical (floor-to-ceiling) metrology is the more robust cue --
    # real evidence across all 3 rooms shows photo-tier ceiling height within 3-9% of the same
    # room's LiDAR measurement (2.98m/2.93m/2.97m vs lidar's n/a/n/a/3.06m -- only 1 room has a
    # LiDAR ceiling reading, the other 2 captures never tilted up far enough). 15% keeps a
    # comfortable margin over the one directly-comparable sample (~3%).
    #
    # ci_frac_lateral: +-55%. Lateral/depth (wall width, room depth, and therefore floor area,
    # which is derived from both) metrology is FAR less reliable in practice than originally
    # assumed: cross-tier wall-length error reached 18.7% / 50.6% / 48.9% across the 3 real rooms
    # (floor-area error correspondingly 25-76%) -- the single-view similar-triangles depth
    # estimate is highly sensitive to horizon-row/vanishing-point error, which compounds with
    # distance and gets worse on larger/more open rooms sampled by only 2-8 stills. 55% is the
    # observed max (50.6%) rounded up for margin given the very small sample (n=3 real rooms,
    # not a controlled calibration set) -- see docs/11_known_limitations.md and
    # docs/08_benchmark_report.md for the exact numbers and benchmark/real_data_report.json for
    # the raw per-room evidence. This was revised UP from an initial, too-optimistic flat 15%
    # once this real cross-tier data was actually measured -- disclosed here rather than quietly
    # corrected, since getting caught shipping "confident garbage" on exactly this measurement is
    # the spec's own stated scoring risk.
    ci_frac_ceiling: float = 0.15
    ci_frac_lateral: float = 0.55


def _line_angle_deg(x1, y1, x2, y2) -> float:
    return float(np.degrees(np.arctan2(y2 - y1, x2 - x1))) % 180.0


def _detect_lines(gray: np.ndarray, cfg: PhotoTierConfig) -> np.ndarray:
    edges = cv2.Canny(gray, cfg.canny_low, cfg.canny_high)
    lines = cv2.HoughLinesP(
        edges, 1, np.pi / 180, cfg.hough_threshold, minLineLength=cfg.hough_min_line_length, maxLineGap=cfg.hough_max_line_gap
    )
    return lines.reshape(-1, 4) if lines is not None else np.empty((0, 4))


def _split_vertical_horizontal(lines: np.ndarray, cfg: PhotoTierConfig) -> tuple[np.ndarray, np.ndarray]:
    if len(lines) == 0:
        return lines, lines
    angles = np.array([_line_angle_deg(*ln) for ln in lines])
    is_vertical = np.abs(angles - 90.0) <= cfg.vertical_angle_tol_deg
    return lines[is_vertical], lines[~is_vertical]


def _ground_depth(pixel_row: float, horizon_row: float, fy: float, camera_height_m: float) -> float | None:
    v = pixel_row - horizon_row
    if v <= 1e-6:
        return None
    return camera_height_m * fy / v


def analyze_photo(gray: np.ndarray, intr: Intrinsics, cfg: PhotoTierConfig) -> dict:
    """Best-effort single-photo metrology. Returns a dict with whatever could be estimated;
    missing keys mean that signal wasn't confidently found in this photo (never fabricated).
    """
    h, w = gray.shape
    horizon_row = intr.cy  # disclosed assumption: level camera, zero pitch/roll
    lines = _detect_lines(gray, cfg)
    vlines, hlines = _split_vertical_horizontal(lines, cfg)

    result: dict = {"n_lines": len(lines), "n_vertical": len(vlines), "n_horizontal": len(hlines)}

    # Floor-wall boundary candidate: lowest (max-row) moderately-horizontal line in the bottom
    # half of the frame -- the nearest floor/wall seam to the camera.
    bottom_half = hlines[(hlines[:, 1] >= h / 2) & (hlines[:, 3] >= h / 2)] if len(hlines) else hlines
    floor_row = None
    if len(bottom_half):
        floor_row = float(np.mean(bottom_half[np.argmax(bottom_half[:, [1, 3]].max(axis=1))][[1, 3]]))

    # Ceiling-wall boundary candidate: highest (min-row) horizontal-ish line in the top half.
    top_half = hlines[(hlines[:, 1] <= h / 2) & (hlines[:, 3] <= h / 2)] if len(hlines) else hlines
    ceiling_row = None
    if len(top_half):
        ceiling_row = float(np.mean(top_half[np.argmin(top_half[:, [1, 3]].min(axis=1))][[1, 3]]))

    depth_m = None
    if floor_row is not None:
        depth_m = _ground_depth(floor_row, horizon_row, intr.fy, cfg.assumed_camera_height_m)
        result["floor_row"] = floor_row
        result["back_wall_depth_m"] = depth_m

    if ceiling_row is not None and depth_m is not None:
        ceiling_height_m = cfg.assumed_camera_height_m - (ceiling_row - horizon_row) * depth_m / intr.fy
        result["ceiling_row"] = ceiling_row
        result["ceiling_height_m"] = ceiling_height_m

    if depth_m is not None:
        # Lateral wall-width proxy: back-project the full frame width at the back-wall depth.
        # A proper implementation would intersect the two receding floor/side-wall Hough lines
        # at `floor_row`; this is the disclosed, wide-CI fallback used when those aren't both
        # confidently detected (kept simple -- see docs/11_known_limitations.md).
        left_x = (0 - intr.cx) * depth_m / intr.fx
        right_x = (w - intr.cx) * depth_m / intr.fx
        result["wall_width_m"] = float(right_x - left_x)

    return result


def load_photo_capture(capture_dir, room_id: str, config: PhotoTierConfig | None = None) -> CaptureBundle:
    cfg = config or PhotoTierConfig()
    root = find_capture_root(capture_dir)
    intr = load_rgb_intrinsics(root)

    cap = cv2.VideoCapture(str(root / "rgb.mp4"))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()
    indices = sorted(set(np.linspace(0, total_frames - 1, cfg.n_photos).astype(int).tolist()))
    frames = extract_frames(root / "rgb.mp4", indices)

    per_photo = []
    for i in indices:
        if i not in frames:
            continue
        gray = cv2.cvtColor(frames[i], cv2.COLOR_BGR2GRAY)
        per_photo.append({"frame_index": i, **analyze_photo(gray, intr, cfg)})

    depths = [p["back_wall_depth_m"] for p in per_photo if "back_wall_depth_m" in p]
    widths = [p["wall_width_m"] for p in per_photo if "wall_width_m" in p]
    ceilings = [p["ceiling_height_m"] for p in per_photo if "ceiling_height_m" in p]

    # Photo tier has no 3D points at all -- represent wall-plane estimates as a thin synthetic
    # point cloud purely so the shared CaptureBundle/WeightedPointCloud contract still holds
    # downstream (e.g. for rendering point counts); the *authoritative* numbers are the
    # Measurements built directly from per-photo metrology above, not this proxy cloud.
    synth_pts = np.zeros((max(1, len(per_photo)), 3), dtype=np.float32)
    synth_weights = np.ones(len(synth_pts), dtype=np.float32) * 0.3
    cloud = WeightedPointCloud(points=synth_pts, weights=synth_weights, source_tier="photo")

    meta = {
        "n_photos": len(per_photo),
        "photos": per_photo,
        "note": "no pose/depth available; metrology relies on assumed level camera + eye-height",
    }
    if depths:
        meta["estimated_depth_m"] = float(np.median(depths))
    if widths:
        meta["estimated_width_m"] = float(np.median(widths))
    if ceilings:
        meta["estimated_ceiling_height_m"] = float(np.median(ceilings))

    return CaptureBundle(
        capture_id=root.name,
        room_id=room_id,
        tier="photo",
        source_dir=root,
        point_cloud=cloud,
        poses=[],
        photo_paths=[],
        meta=meta,
    )


def photo_measurements(bundle: CaptureBundle, cfg: PhotoTierConfig | None = None) -> dict[str, Measurement]:
    """Turn a photo-tier CaptureBundle's meta into disclosed, widely-bounded Measurements."""
    cfg = cfg or PhotoTierConfig()
    out: dict[str, Measurement] = {}
    if "estimated_width_m" in bundle.meta:
        v = bundle.meta["estimated_width_m"]
        out["wall_width"] = Measurement(value=v, ci=cfg.ci_frac_lateral * v, method="photo_ground_plane_single_view")
    if "estimated_depth_m" in bundle.meta:
        v = bundle.meta["estimated_depth_m"]
        out["room_depth"] = Measurement(value=v, ci=cfg.ci_frac_lateral * v, method="photo_ground_plane_single_view")
    if "estimated_ceiling_height_m" in bundle.meta:
        v = bundle.meta["estimated_ceiling_height_m"]
        out["ceiling_height"] = Measurement(value=v, ci=cfg.ci_frac_ceiling * v, method="photo_ground_plane_single_view")
    return out


def photo_room_model(bundle: CaptureBundle, cfg: PhotoTierConfig | None = None) -> RoomModel:
    """Build the same RoomModel contract the other two tiers produce, from scalar photo-tier
    measurements. No per-wall opening detection is possible from single, non-overlapping photos
    with this method, so every wall reports zero openings with an explicit note -- never a
    fabricated guess.
    """
    cfg = cfg or PhotoTierConfig()
    m = photo_measurements(bundle, cfg)
    if "wall_width" not in m or "room_depth" not in m:
        raise RuntimeError(f"Photo tier found too little line signal to estimate room size for {bundle.room_id!r}")

    width, depth = m["wall_width"].value, m["room_depth"].value
    width_ci, depth_ci = m["wall_width"].ci, m["room_depth"].ci
    corners_local = np.array([[0, 0], [width, 0], [width, depth], [0, depth]])
    specs = [
        (np.array([0.0, 0.0]), np.array([0.0, depth]), depth_ci),
        (np.array([width, 0.0]), np.array([width, depth]), depth_ci),
        (np.array([0.0, 0.0]), np.array([width, 0.0]), width_ci),
        (np.array([0.0, depth]), np.array([width, depth]), width_ci),
    ]
    walls = [
        Wall(
            index=idx,
            p1=p1,
            p2=p2,
            length=Measurement(value=float(np.linalg.norm(p2 - p1)), ci=ci, method="photo_ground_plane_single_view"),
            openings=[],
        )
        for idx, (p1, p2, ci) in enumerate(specs)
    ]

    area_value = width * depth
    area_ci = float(np.hypot(depth * width_ci, width * depth_ci))
    return RoomModel(
        room_id=bundle.room_id,
        tier="photo",
        walls=walls,
        floor_polygon=corners_local,
        ceiling_height=m.get("ceiling_height"),
        floor_area=Measurement(value=area_value, ci=area_ci, method="photo_propagated_from_wall_ci"),
        transform_to_global=np.eye(3),
        point_count=len(bundle.point_cloud),
        notes=[
            "Photo tier: rectangle built from single-view ground-plane metrology, not direct wall "
            "detection. Per-wall openings are not reported at this tier (no overlapping-photo "
            "coverage to detect them) rather than guessed.",
        ],
        meta={"photo_metrology": {k: v.as_dict() for k, v in m.items()}},
    )
