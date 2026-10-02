"""Manhattan-world room-box reconstruction: point cloud -> walls, ceiling height, floor area, openings.

Algorithm (see docs/03_algorithms.md for the full write-up and rationale):

1. Assume gravity-aligned "up" = world +Y (true for ARKit's default .gravity world alignment,
   which Stray Scanner and plain ARKit video/photo captures all use).
2. Floor/ceiling are found as the lowest/highest significant peaks in a 1D histogram of Y --
   real floors and ceilings are flat, so they show up as sharp density spikes.
3. A single dominant wall direction is found via 2D RANSAC line fitting on a mid-height "wall
   band" slice (avoids furniture near the floor and soffits/fixtures near the ceiling). Every
   wall in a rectangular room is assumed parallel or perpendicular to it (Manhattan-world).
4. Points are rotated into that frame; wall positions become 1D histogram peaks again (this
   time along each of the two rotated axes), reusing the exact same peak-finder.
5. Per-wall point profiles (position-along-wall x height) are turned into a 2D occupancy grid;
   columns with low vertical coverage are openings, classified door/window by sill height.

Disclosed scope limits: rectangular (box) rooms only; an L-shaped or curved room will report
fewer than 4 walls with a note rather than a wrong polygon -- see docs/11_known_limitations.md.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from cozmoscan.geometry.histogram import Peak, find_peaks
from cozmoscan.types import Measurement, Opening, RoomModel, Tier, Wall, WeightedPointCloud

UP_AXIS = 1  # world +Y


class ReconstructionError(RuntimeError):
    """Raised when a capture has too little signal to fit a room box at all."""


@dataclass
class ManhattanConfig:
    ransac_iterations: int = 400
    ransac_inlier_threshold_m: float = 0.035
    floor_ceiling_bin_m: float = 0.02
    wall_bin_m: float = 0.02
    min_peak_support_frac: float = 0.01
    peak_merge_radius_m: float = 0.06
    min_room_dim_m: float = 1.2
    wall_band_low_m: float = 0.6
    wall_band_high_m: float = 1.8
    min_band_points: int = 600
    opening_bin_m: float = 0.05
    opening_coverage_threshold: float = 0.35
    opening_min_width_m: float = 0.3
    corner_margin_m: float = 0.10
    door_sill_threshold_m: float = 0.15
    ci_k: float = 2.0  # calibrated against synthetic benchmark repeatability, see docs/07
    rng_seed: int = 7


def _ransac_line(points2d: np.ndarray, iters: int, threshold: float, rng: np.random.Generator):
    n = len(points2d)
    best_inliers = None
    best_count = -1
    best_p0 = best_d = None
    for _ in range(iters):
        i, j = rng.integers(0, n, size=2)
        if i == j:
            continue
        p0, p1 = points2d[i], points2d[j]
        d = p1 - p0
        norm = np.linalg.norm(d)
        if norm < 1e-6:
            continue
        d = d / norm
        normal = np.array([-d[1], d[0]])
        dist = np.abs((points2d - p0) @ normal)
        inliers = dist <= threshold
        count = int(inliers.sum())
        if count > best_count:
            best_count, best_inliers, best_p0, best_d = count, inliers, p0, d
    if best_d is None:
        raise ReconstructionError("RANSAC line fit found no valid sample pair")
    return best_p0, best_d, best_inliers


def _dominant_manhattan_angle(points2d: np.ndarray, cfg: ManhattanConfig, rng: np.random.Generator) -> float:
    _, d, _ = _ransac_line(points2d, cfg.ransac_iterations, cfg.ransac_inlier_threshold_m, rng)
    theta = np.arctan2(d[1], d[0])
    return float(theta % (np.pi / 2))


def _rotate(points2d: np.ndarray, theta: float) -> np.ndarray:
    c, s = np.cos(-theta), np.sin(-theta)
    rot = np.array([[c, -s], [s, c]])
    return points2d @ rot.T


def _axis_peaks(values: np.ndarray, cfg: ManhattanConfig) -> list[Peak]:
    min_support = max(5, int(cfg.min_peak_support_frac * len(values)))
    return find_peaks(values, cfg.wall_bin_m, min_support, cfg.peak_merge_radius_m)


def _pick_bounding_pair(peaks: list[Peak], min_dim: float, fallback_lo: float, fallback_hi: float) -> tuple[Peak, Peak, list[str]]:
    notes: list[str] = []
    by_center = sorted(peaks, key=lambda p: p.center)
    if len(by_center) >= 2 and (by_center[-1].center - by_center[0].center) >= min_dim:
        return by_center[0], by_center[-1], notes
    # degraded case: wall(s) not clearly observed on this axis -- fall back to raw point extent
    notes.append(
        "Fewer than two separated wall peaks found on one axis; used raw point-cloud extent as a "
        "lower-bound estimate with widened confidence interval (wall likely outside capture coverage)."
    )
    lo_peak = by_center[0] if by_center else Peak(center=fallback_lo, support=1, spread=cfg_default_spread())
    hi_peak = by_center[-1] if by_center else Peak(center=fallback_hi, support=1, spread=cfg_default_spread())
    if lo_peak is hi_peak:
        hi_peak = Peak(center=fallback_hi, support=1, spread=cfg_default_spread())
    return lo_peak, hi_peak, notes


def cfg_default_spread() -> float:
    return 0.05  # 5cm: "we did not actually see this wall" default uncertainty seed


def _adaptive_wall_band(points: np.ndarray, floor_y: float, ceiling_y: float | None, cfg: ManhattanConfig) -> np.ndarray:
    lo, hi = floor_y + cfg.wall_band_low_m, floor_y + cfg.wall_band_high_m
    band_mask = (points[:, UP_AXIS] >= lo) & (points[:, UP_AXIS] <= hi)
    expand = 0.0
    while band_mask.sum() < cfg.min_band_points and expand < 2.0:
        expand += 0.3
        top = ceiling_y - 0.1 if ceiling_y is not None else floor_y + cfg.wall_band_high_m + expand
        lo = floor_y + max(0.1, cfg.wall_band_low_m - expand)
        hi = min(top, floor_y + cfg.wall_band_high_m + expand)
        band_mask = (points[:, UP_AXIS] >= lo) & (points[:, UP_AXIS] <= hi)
    return band_mask


def fit_room_box(
    cloud: WeightedPointCloud,
    tier: Tier,
    room_id: str,
    config: ManhattanConfig | None = None,
    trajectory_xz: np.ndarray | None = None,
) -> RoomModel:
    """Fit a Manhattan room box to ``cloud``.

    ``trajectory_xz`` is an optional (N,2) array of camera-position (x,z) samples. When given,
    it is used purely as a *physical sanity floor*: a room can never be smaller than the area the
    camera actually walked through (plus a standoff margin for not walking flush against a wall).
    This matters most for the video tier, where sparse feature triangulation without depth can
    under-cover distant/textureless walls -- see docs/11_known_limitations.md. It is a no-op
    safety net (never shrinks a confident fit) so it is harmless to pass for any tier.
    """
    cfg = config or ManhattanConfig()
    rng = np.random.default_rng(cfg.rng_seed)
    pts = cloud.points
    if len(pts) < 200:
        raise ReconstructionError(f"Only {len(pts)} points -- too few to fit a room box for {room_id!r}")

    notes: list[str] = []

    # --- floor / ceiling from a Y histogram ---
    y_peaks = _axis_peaks(pts[:, UP_AXIS], cfg)
    if not y_peaks:
        raise ReconstructionError("No horizontal-plane peaks found (floor not detected)")
    significant = [p for p in y_peaks if p.support >= 0.2 * y_peaks[0].support]
    significant.sort(key=lambda p: p.center)
    floor_peak = significant[0]
    ceiling_peak = None
    if len(significant) > 1 and (significant[-1].center - floor_peak.center) >= 1.8:
        ceiling_peak = significant[-1]
    else:
        notes.append(
            "No ceiling plane observed (capture likely did not tilt up far enough); "
            "ceiling_height is omitted rather than guessed."
        )

    # --- dominant wall direction + wall band ---
    band_mask = _adaptive_wall_band(pts, floor_peak.center, ceiling_peak.center if ceiling_peak else None, cfg)
    band_xz = pts[band_mask][:, [0, 2]]
    if len(band_xz) < 50:
        raise ReconstructionError("Not enough mid-height points to establish wall orientation")
    theta0 = _dominant_manhattan_angle(band_xz, cfg, rng)

    all_xz_rot = _rotate(pts[:, [0, 2]], theta0)
    band_rot = _rotate(band_xz, theta0)
    u, v = band_rot[:, 0], band_rot[:, 1]

    u_peaks = _axis_peaks(u, cfg)
    v_peaks = _axis_peaks(v, cfg)
    u_lo, u_hi, n1 = _pick_bounding_pair(u_peaks, cfg.min_room_dim_m, all_xz_rot[:, 0].min(), all_xz_rot[:, 0].max())
    v_lo, v_hi, n2 = _pick_bounding_pair(v_peaks, cfg.min_room_dim_m, all_xz_rot[:, 1].min(), all_xz_rot[:, 1].max())
    notes.extend(n1 + n2)

    if trajectory_xz is not None and len(trajectory_xz) > 0:
        standoff_m = 0.3
        traj_rot = _rotate(np.asarray(trajectory_xz, dtype=np.float64), theta0)
        traj_u_lo, traj_u_hi = float(traj_rot[:, 0].min()) - standoff_m, float(traj_rot[:, 0].max()) + standoff_m
        traj_v_lo, traj_v_hi = float(traj_rot[:, 1].min()) - standoff_m, float(traj_rot[:, 1].max()) + standoff_m
        widened = False
        wide_spread = cfg_default_spread() * 3
        if traj_u_lo < u_lo.center:
            u_lo, widened = Peak(center=traj_u_lo, support=0, spread=wide_spread), True
        if traj_u_hi > u_hi.center:
            u_hi, widened = Peak(center=traj_u_hi, support=0, spread=wide_spread), True
        if traj_v_lo < v_lo.center:
            v_lo, widened = Peak(center=traj_v_lo, support=0, spread=wide_spread), True
        if traj_v_hi > v_hi.center:
            v_hi, widened = Peak(center=traj_v_hi, support=0, spread=wide_spread), True
        if widened:
            notes.append(
                "Footprint widened to encompass the camera trajectory (+0.3m standoff): wall-point "
                "signal was below confidence threshold for the full walked area, so reported "
                "width/depth are a physically-grounded lower bound with a widened uncertainty band "
                "rather than a direct wall-surface measurement."
            )

    width = u_hi.center - u_lo.center
    depth = v_hi.center - v_lo.center
    width_ci = cfg.ci_k * float(np.hypot(u_lo.spread, u_hi.spread))
    depth_ci = cfg.ci_k * float(np.hypot(v_lo.spread, v_hi.spread))

    # room-local frame: origin at (u_lo, v_lo), axes = rotated (u, v)
    corners_local = np.array([[0, 0], [width, 0], [width, depth], [0, depth]])
    c, s = np.cos(theta0), np.sin(theta0)
    rot_fwd = np.array([[c, -s], [s, c]])
    t = rot_fwd @ np.array([u_lo.center, v_lo.center])
    transform = np.eye(3)
    transform[:2, :2] = rot_fwd
    transform[:2, 2] = t

    walls = _build_walls(pts, u_lo, u_hi, v_lo, v_hi, theta0, floor_peak, ceiling_peak, width, depth, cfg)

    ceiling_measurement = None
    if ceiling_peak is not None:
        ceiling_measurement = Measurement(
            value=ceiling_peak.center - floor_peak.center,
            ci=cfg.ci_k * float(np.hypot(floor_peak.spread, ceiling_peak.spread)),
            method=f"{tier}_histogram_peak_k{cfg.ci_k}",
        )

    area_value = width * depth
    area_ci = float(np.hypot(depth * width_ci, width * depth_ci))
    floor_area = Measurement(value=area_value, ci=area_ci, method=f"{tier}_propagated_from_wall_ci")

    return RoomModel(
        room_id=room_id,
        tier=tier,
        walls=walls,
        floor_polygon=corners_local,
        ceiling_height=ceiling_measurement,
        floor_area=floor_area,
        transform_to_global=transform,
        point_count=len(pts),
        notes=notes,
        meta={"manhattan_angle_rad": theta0, "floor_y": floor_peak.center, "ceiling_y": ceiling_peak.center if ceiling_peak else None},
    )


def _build_walls(
    pts: np.ndarray,
    u_lo: Peak,
    u_hi: Peak,
    v_lo: Peak,
    v_hi: Peak,
    theta0: float,
    floor_peak: Peak,
    ceiling_peak: Peak | None,
    width: float,
    depth: float,
    cfg: ManhattanConfig,
) -> list[Wall]:
    """Four walls of the rectangle, each with Measurement length + detected openings."""
    all_uv = _rotate(pts[:, [0, 2]], theta0)
    u, v = all_uv[:, 0], all_uv[:, 1]
    y = pts[:, UP_AXIS]
    floor_y = floor_peak.center
    ceiling_y = ceiling_peak.center if ceiling_peak else floor_y + 2.2

    # (p1_local, p2_local, const_axis, const_peak, pos_axis_values, pos_origin, spread)
    specs = [
        (np.array([0, 0]), np.array([0, depth]), "u", u_lo, v, v_lo.center, u_lo.spread),
        (np.array([width, 0]), np.array([width, depth]), "u", u_hi, v, v_lo.center, u_hi.spread),
        (np.array([0, 0]), np.array([width, 0]), "v", v_lo, u, u_lo.center, v_lo.spread),
        (np.array([0, depth]), np.array([width, depth]), "v", v_hi, u, u_lo.center, v_hi.spread),
    ]

    walls: list[Wall] = []
    for idx, (p1, p2, axis, const_peak, pos_values, pos_origin, spread) in enumerate(specs):
        wall_len = np.linalg.norm(p2 - p1)
        length = Measurement(value=float(wall_len), ci=cfg.ci_k * spread, method=f"histogram_peak_k{cfg.ci_k}")
        const_values = u if axis == "u" else v
        near_wall = np.abs(const_values - const_peak.center) <= max(cfg.ransac_inlier_threshold_m * 2, 0.08)
        w_pos = pos_values[near_wall] - pos_origin
        h_pos = y[near_wall] - floor_y
        in_extent = (w_pos >= -0.05) & (w_pos <= wall_len + 0.05)
        openings = _detect_openings(w_pos[in_extent], h_pos[in_extent], wall_len, ceiling_y - floor_y, idx, cfg)
        walls.append(Wall(index=idx, p1=p1.astype(float), p2=p2.astype(float), length=length, openings=openings))
    return walls


def _detect_openings(w: np.ndarray, h: np.ndarray, wall_len: float, room_height: float, wall_index: int, cfg: ManhattanConfig) -> list[Opening]:
    if wall_len < 2 * cfg.corner_margin_m or len(w) < 20:
        return []
    bin_m = cfg.opening_bin_m
    n_w_bins = max(1, int(np.ceil(wall_len / bin_m)))
    n_h_bins = max(1, int(np.ceil(room_height / bin_m)))
    occ = np.zeros((n_w_bins, n_h_bins), dtype=bool)
    wi = np.clip((w / bin_m).astype(int), 0, n_w_bins - 1)
    hi = np.clip((h / bin_m).astype(int), 0, n_h_bins - 1)
    # occupied if a cell has at least one hit (coarse but sufficient after >= 2cm voxel downsample)
    np.add.at(occ, (wi, hi), True)

    valid_h_lo = max(0, int(0.05 / bin_m))
    valid_h_hi = min(n_h_bins, int((room_height - 0.05) / bin_m))
    coverage = occ[:, valid_h_lo:valid_h_hi].mean(axis=1) if valid_h_hi > valid_h_lo else np.ones(n_w_bins)

    margin_bins = max(1, int(cfg.corner_margin_m / bin_m))
    is_open = coverage < cfg.opening_coverage_threshold
    is_open[:margin_bins] = False
    is_open[-margin_bins:] = False

    openings: list[Opening] = []
    i = 0
    while i < n_w_bins:
        if not is_open[i]:
            i += 1
            continue
        j = i
        while j < n_w_bins and is_open[j]:
            j += 1
        width_m = (j - i) * bin_m
        if width_m >= cfg.opening_min_width_m:
            col_occ = occ[i:j, :]
            missing_h = ~col_occ.any(axis=0)
            if missing_h.any():
                h_idx = np.nonzero(missing_h)[0]
                gap_lo, gap_hi = h_idx.min() * bin_m, (h_idx.max() + 1) * bin_m
            else:
                gap_lo, gap_hi = 0.0, room_height
            kind = "door" if gap_lo <= cfg.door_sill_threshold_m else "window"
            openings.append(
                Opening(
                    wall_index=wall_index,
                    start_m=float(i * bin_m),
                    width=Measurement(value=float(width_m), ci=float(bin_m), method="opening_gap_bin_width"),
                    height=Measurement(value=float(gap_hi - gap_lo), ci=float(bin_m), method="opening_gap_bin_height"),
                    kind=kind,
                    sill_height_m=float(gap_lo),
                )
            )
        i = j
    return openings
