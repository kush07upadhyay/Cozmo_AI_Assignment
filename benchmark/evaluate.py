"""Shared scoring helpers for the synthetic benchmark: matching a reconstructed RoomModel's
(arbitrarily-labeled) wall indices back to the ground-truth RoomSpec's wall indices, opening
matching, and placement/corner error -- reused by benchmark/gates.py and by any ad-hoc
validation script.

Why matching is needed at all: ``fit_room_box`` invents its own local frame from the data (via
RANSAC dominant-angle + histogram lo/hi peaks). For an axis-aligned synthetic room this frame
is a 0/90/180/270-degree rotation/reflection of the room's "generation-time" x/z axes, but
*which* of the 4 is not knowable in advance -- it must be resolved after the fact by nearest-
midpoint matching against the known geometry. This is purely a test-harness concern; it has no
bearing on whether the reconstruction itself is correct (a room is still geometrically right
regardless of which wall gets called "0").
"""
from __future__ import annotations

import numpy as np

from benchmark.synthetic_rooms import RoomSpec
from cozmoscan.types import RoomModel


def _gen_wall_midpoint_xz(spec: RoomSpec, wall_index: int) -> np.ndarray:
    if wall_index == 0:
        return np.array([0.0, spec.depth_m / 2])
    if wall_index == 1:
        return np.array([spec.width_m, spec.depth_m / 2])
    if wall_index == 2:
        return np.array([spec.width_m / 2, 0.0])
    return np.array([spec.width_m / 2, spec.depth_m])


def match_wall_indices(room: RoomModel, spec: RoomSpec) -> dict[int, int]:
    """Returns {generation_wall_index: reconstructed_wall_index}, matched by nearest wall
    midpoint once each reconstructed wall is mapped into the room's own input-cloud frame via
    its own (pre-stitch) ``transform_to_global`` -- valid because the synthetic cloud is
    generated directly in that same frame (identity global offset/rotation per room)."""
    recon_mids = []
    for w in room.walls:
        mid_local = (w.p1 + w.p2) / 2
        mid_global = (room.transform_to_global @ np.append(mid_local, 1.0))[:2]
        recon_mids.append(mid_global)

    mapping = {}
    used = set()
    for gen_idx in range(4):
        gen_mid = _gen_wall_midpoint_xz(spec, gen_idx)
        dists = [np.linalg.norm(gen_mid - rm) if i not in used else np.inf for i, rm in enumerate(recon_mids)]
        best = int(np.argmin(dists))
        used.add(best)
        mapping[gen_idx] = best
    return mapping


def opening_accuracy(room: RoomModel, spec: RoomSpec, mapping: dict[int, int], width_tol_m: float = 0.02) -> list[dict]:
    """For each ground-truth opening, finds the best-matching detected opening on the
    corresponding (matched) wall and records the width error. Returns one dict per ground-truth
    opening (``detected: False`` if nothing matched)."""
    results = []
    for o in spec.openings:
        recon_wall_idx = mapping[o.wall_index]
        wall = room.walls[recon_wall_idx]
        gen_wall_mid = _gen_wall_midpoint_xz(spec, o.wall_index)
        # does the matched reconstructed wall run in the same direction sense as generation
        # (p1->p2) or reversed? Determine by comparing wall length axis sign via global corner.
        p1_global = (room.transform_to_global @ np.append(wall.p1, 1.0))[:2]
        p2_global = (room.transform_to_global @ np.append(wall.p2, 1.0))[:2]
        # Generation-time opening center position along the wall, in meters from the
        # generation wall's own start (start_m measured from pos=0 as defined in _wall_points).
        gen_center = o.start_m + o.width_m / 2
        gen_len = o.width_m
        # Reconstructed wall may run start<->end in either direction; try both and keep best.
        best = None
        for candidate_opening in wall.openings:
            cand_center = candidate_opening.start_m + candidate_opening.width.value / 2
            cand_len_from_start = cand_center
            cand_len_from_end = wall.length.value - cand_center
            dist = min(abs(cand_len_from_start - gen_center), abs(cand_len_from_end - gen_center))
            if best is None or dist < best[0]:
                best = (dist, candidate_opening)
        if best is not None and best[0] <= 0.5:
            width_err = abs(best[1].width.value - o.width_m)
            results.append(
                {
                    "wall_index": o.wall_index,
                    "kind": o.kind,
                    "gt_width_m": o.width_m,
                    "detected_width_m": best[1].width.value,
                    "width_error_m": width_err,
                    "within_tol": width_err <= width_tol_m,
                    "detected": True,
                }
            )
        else:
            results.append({"wall_index": o.wall_index, "kind": o.kind, "gt_width_m": o.width_m, "detected": False, "within_tol": False})
    return results


def corner_error_m(stitched_room: RoomModel, true_transform: np.ndarray) -> float:
    """Mean corner distance between ``stitched_room``'s global floor polygon (via its own
    ``transform_to_global``, as set by stitch_rooms) and the *true* global floor polygon (via
    ``true_transform``, which must already be composed all the way from this room's own
    pre-stitch local frame -- see ``true_global_transform`` below)."""
    corners_local = np.concatenate([stitched_room.floor_polygon, np.ones((len(stitched_room.floor_polygon), 1))], axis=1)
    true_global = (corners_local @ true_transform.T)[:, :2]
    est_global = (corners_local @ stitched_room.transform_to_global.T)[:, :2]
    return float(np.mean(np.linalg.norm(true_global - est_global, axis=1)))


def xzr_to_matrix(x: float, z: float, rotation_rad: float) -> np.ndarray:
    c, s = np.cos(rotation_rad), np.sin(rotation_rad)
    t = np.eye(3)
    t[:2, :2] = [[c, -s], [s, c]]
    t[:2, 2] = [x, z]
    return t


def matrix_to_xzr(t: np.ndarray) -> tuple[float, float, float]:
    rotation_rad = float(np.arctan2(t[1, 0], t[0, 0]))
    return float(t[0, 2]), float(t[1, 2]), rotation_rad


def true_global_transform(room: RoomModel, true_genframe_xzr: tuple[float, float, float]) -> np.ndarray:
    """Composes this room's own (pre-stitch) ``transform_to_global`` -- which maps its
    ``fit_room_box``-invented local frame back into the synthetic generator's x/z frame, since
    that's the frame each room's point cloud was generated in -- with the room's true global
    placement *of that generator frame*. Needed because fit_room_box's local frame is an
    unpredictable 0/90/180/270-degree rotation/reflection of the generator's x/z axes (see
    module docstring), so ground-truth placement can only be expressed relative to the
    generator frame, then carried through to the actual local frame via this composition."""
    x, z, rot = true_genframe_xzr
    return xzr_to_matrix(x, z, rot) @ room.transform_to_global


def drifted_placement_xzr(room: RoomModel, true_genframe_xzr: tuple[float, float, float], drift_xzr: tuple[float, float, float]) -> tuple[float, float, float]:
    """Ground-truth transform (see ``true_global_transform``) with a small additional drift
    perturbation applied in the global frame (modeling VIO's accumulated walkthrough-tracking
    error), decomposed back to (x, z, rotation_rad) for ``RoomPlacement``."""
    true_t = true_global_transform(room, true_genframe_xzr)
    dx, dz, drot = drift_xzr
    drifted = xzr_to_matrix(dx, dz, drot) @ true_t
    return matrix_to_xzr(drifted)
