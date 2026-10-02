"""Multi-room stitching: place each room's locally-reconstructed RoomModel into one shared
global frame, using known connector adjacency (which wall in room A opens into which wall in
room B) plus a per-room *estimated* placement (as a VIO/ARKit walkthrough would hand you,
including its accumulated drift).

Two modes, selectable per the spec's required on/off ablation:
- ``correct_drift=False``: poses are used exactly as given (the drifted estimate) -- this is the
  explicit "fail" case the case study brief warns about, kept only so the ablation has a
  baseline to compare against.
- ``correct_drift=True``: a Manhattan-snap chain relaxation. Starting from an anchor room, each
  connector is walked in turn; the neighboring room's rotation is snapped to the nearest 90
  degrees relative to the anchor's corrected wall direction (Manhattan-world: shared walls are
  parallel lines), and its translation is solved so the shared doorway lines up exactly (zero
  gap/overlap). The remaining 180-degree ambiguity in "which way is the wall facing" (a wall's
  ``p1``/``p2`` endpoint order is an arbitrary artifact of each room's own independent
  reconstruction, not a reliable shared/anti-parallel convention across two different rooms'
  fits) is resolved using a physically meaningful invariant instead: two rooms sharing a wall
  must have their interiors on *opposite sides* of it. This is a tree/chain relaxation, not full
  nonlinear pose-graph bundle adjustment -- it does not handle loop closure if the room graph
  contains a cycle (disclosed in docs/11_known_limitations.md).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from cozmoscan.types import RoomModel


@dataclass
class Connector:
    """A doorway/opening physically shared by two rooms."""

    room_a: str
    wall_a: int
    room_b: str
    wall_b: int


@dataclass
class RoomPlacement:
    """A room's estimated pose in the global frame, as a walkthrough's VIO would hand you --
    including whatever drift has accumulated by the time this room was captured.
    """

    room_id: str
    x: float
    z: float
    rotation_rad: float

    def as_matrix(self) -> np.ndarray:
        c, s = np.cos(self.rotation_rad), np.sin(self.rotation_rad)
        t = np.eye(3)
        t[:2, :2] = [[c, -s], [s, c]]
        t[:2, 2] = [self.x, self.z]
        return t


def _wall_midpoint_and_dir(room: RoomModel, wall_index: int) -> tuple[np.ndarray, np.ndarray]:
    wall = room.walls[wall_index]
    mid_local = (wall.p1 + wall.p2) / 2
    return mid_local, wall.direction()


def _snap_to_90deg(angle_rad: float) -> float:
    step = np.pi / 2
    return round(angle_rad / step) * step


def _side_of_line(line_point: np.ndarray, line_dir: np.ndarray, query_point: np.ndarray) -> float:
    """Signed side (>0 / <0) of ``query_point`` relative to the infinite line through
    ``line_point`` in direction ``line_dir``, via 2D cross product."""
    rel = query_point - line_point
    return float(line_dir[0] * rel[1] - line_dir[1] * rel[0])


def _room_centroid_global(room: RoomModel, transform: np.ndarray) -> np.ndarray:
    centroid_local = room.floor_polygon.mean(axis=0)
    return (transform @ np.append(centroid_local, 1.0))[:2]


def stitch_rooms(
    rooms: list[RoomModel],
    placements: list[RoomPlacement],
    connectors: list[Connector],
    correct_drift: bool = True,
    anchor_room_id: str | None = None,
) -> list[RoomModel]:
    """Returns copies of ``rooms`` with ``transform_to_global`` set to the stitched placement."""
    by_id = {r.room_id: r for r in rooms}
    placement_by_id = {p.room_id: p for p in placements}
    anchor_room_id = anchor_room_id or rooms[0].room_id

    if not correct_drift:
        out = []
        for r in rooms:
            r2 = _copy_room(r)
            r2.transform_to_global = placement_by_id[r2.room_id].as_matrix()
            out.append(r2)
        return out

    # adjacency: room_id -> list[(neighbor_id, my_wall, neighbor_wall)]
    adjacency: dict[str, list[tuple[str, int, int]]] = {r.room_id: [] for r in rooms}
    for c in connectors:
        adjacency[c.room_a].append((c.room_b, c.wall_a, c.wall_b))
        adjacency[c.room_b].append((c.room_a, c.wall_b, c.wall_a))

    corrected: dict[str, np.ndarray] = {anchor_room_id: placement_by_id[anchor_room_id].as_matrix()}
    frontier = [anchor_room_id]
    while frontier:
        current_id = frontier.pop()
        current_room = by_id[current_id]
        current_transform = corrected[current_id]
        for neighbor_id, my_wall, neighbor_wall in adjacency[current_id]:
            if neighbor_id in corrected:
                continue
            neighbor_room = by_id[neighbor_id]

            mid_a_local, dir_a_local = _wall_midpoint_and_dir(current_room, my_wall)
            mid_a_global = (current_transform @ np.append(mid_a_local, 1.0))[:2]
            dir_a_global = current_transform[:2, :2] @ dir_a_local
            angle_a_global = float(np.arctan2(dir_a_global[1], dir_a_global[0]))
            side_a = _side_of_line(mid_a_global, dir_a_global, _room_centroid_global(current_room, current_transform))

            mid_b_local, dir_b_local = _wall_midpoint_and_dir(neighbor_room, neighbor_wall)
            angle_b_local = float(np.arctan2(dir_b_local[1], dir_b_local[0]))

            # A wall's direction (p1->p2) has no inherent physical sense -- it's an arbitrary
            # artifact of each room's own independent reconstruction, so "anti-parallel" is not
            # a reliable cross-room convention (verified empirically: parallel wall pairs in
            # RoomModel.walls are labeled with the *same* p1->p2 sense, not alternating). Instead,
            # align the wall *lines* (mod 180 degrees -- two candidate rotations, 180 degrees
            # apart) and disambiguate using the one physically meaningful invariant available:
            # two rooms sharing a wall must have their interiors on opposite sides of it.
            raw_rotation = angle_a_global - angle_b_local
            neighbor_transform = None
            for candidate in (raw_rotation, raw_rotation + np.pi):
                rotation = _snap_to_90deg(candidate)
                c, s = np.cos(rotation), np.sin(rotation)
                rot_mat = np.array([[c, -s], [s, c]])
                mid_b_rotated = rot_mat @ mid_b_local
                translation = mid_a_global - mid_b_rotated

                candidate_transform = np.eye(3)
                candidate_transform[:2, :2] = rot_mat
                candidate_transform[:2, 2] = translation

                side_b = _side_of_line(mid_a_global, dir_a_global, _room_centroid_global(neighbor_room, candidate_transform))
                if np.sign(side_b) != np.sign(side_a):
                    neighbor_transform = candidate_transform
                    break
            if neighbor_transform is None:
                # Degenerate (e.g. centroid essentially on the wall line) -- fall back to the
                # last candidate computed rather than leaving the room unplaced.
                neighbor_transform = candidate_transform

            corrected[neighbor_id] = neighbor_transform
            frontier.append(neighbor_id)

    out = []
    for r in rooms:
        r2 = _copy_room(r)
        if r2.room_id in corrected:
            r2.transform_to_global = corrected[r2.room_id]
        else:
            r2.notes.append(f"Room {r2.room_id!r} is not connected to the anchor room; using raw (uncorrected) placement.")
            r2.transform_to_global = placement_by_id[r2.room_id].as_matrix()
        out.append(r2)
    return out


def _copy_room(room: RoomModel) -> RoomModel:
    import copy

    return copy.deepcopy(room)
