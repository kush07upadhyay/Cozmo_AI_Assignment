"""Generate the full synthetic benchmark set (point clouds + staged-damage images + ground
truth) under Sample_data_to_run_code/synthetic_benchmark/.

Composition (mirrors the case study's required benchmark set, since the real sample captures
have no ground truth to score against):
- repeat_room, captured twice (different noise seeds)            -> repeatability gate
- living_room / hallway / bedroom, connected in a line             -> multi-room stitch + drift
  (hallway/bedroom are given a *drifted* estimated placement; stitch_rooms' on/off ablation is
  scored against each room's true placement)
- damage_room point cloud + 2 staged-damage photo crops with known polygons -> damage detection
- 1 extra padding room (den) with a couple more openings            -> bigger openings-accuracy
  sample size for the "openings width" gate

All rooms are generated with a *sparse, occluded* density profile (not a dense uniform scan) --
chosen deliberately because the real sample captures show the same characteristic sparsity
(furniture occlusion, grazing viewing angles), and an idealized dense synthetic cloud would not
exercise that failure mode at all. See docs/07_benchmark_methodology.md.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import numpy as np

from benchmark.synthetic_rooms import OpeningSpec, RoomSpec, SyntheticCaptureConfig, generate_room_point_cloud

OUT_ROOT = Path("Sample_data_to_run_code/synthetic_benchmark")

REALISTIC_CFG = dict(points_per_sqm=160.0, noise_std_m=0.006, outlier_frac=0.015, occlusion_patches_per_wall=2, occlusion_patch_size_m=0.5)


def _save_cloud(name: str, spec: RoomSpec, seed: int, furniture: int = 0):
    cfg = SyntheticCaptureConfig(rng_seed=seed, furniture_clusters=furniture, **REALISTIC_CFG)
    cloud = generate_room_point_cloud(spec, cfg)
    out_dir = OUT_ROOT / name
    out_dir.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out_dir / "points.npz", points=cloud.points, weights=cloud.weights)
    return cloud


def build_rooms() -> dict[str, RoomSpec]:
    rooms = {
        "repeat_room": RoomSpec(
            "repeat_room",
            width_m=4.2,
            depth_m=5.3,
            height_m=2.5,
            openings=[
                OpeningSpec(wall_index=2, start_m=1.6, width_m=0.9, height_m=2.0, sill_height_m=0.0, kind="door"),
                OpeningSpec(wall_index=0, start_m=2.0, width_m=1.2, height_m=1.2, sill_height_m=0.9, kind="window"),
            ],
        ),
        "living_room": RoomSpec(
            "living_room",
            width_m=5.5,
            depth_m=4.5,
            height_m=2.5,
            openings=[
                OpeningSpec(wall_index=1, start_m=1.8, width_m=0.9, height_m=2.0, sill_height_m=0.0, kind="door"),
                OpeningSpec(wall_index=2, start_m=1.5, width_m=1.4, height_m=1.3, sill_height_m=0.85, kind="window"),
            ],
        ),
        "hallway": RoomSpec(
            "hallway",
            width_m=1.5,
            depth_m=3.0,
            height_m=2.5,
            openings=[
                OpeningSpec(wall_index=0, start_m=1.05, width_m=0.9, height_m=2.0, sill_height_m=0.0, kind="door"),
                OpeningSpec(wall_index=1, start_m=1.05, width_m=0.9, height_m=2.0, sill_height_m=0.0, kind="door"),
            ],
        ),
        "bedroom": RoomSpec(
            "bedroom",
            width_m=3.6,
            depth_m=3.4,
            height_m=2.5,
            openings=[
                OpeningSpec(wall_index=0, start_m=1.25, width_m=0.9, height_m=2.0, sill_height_m=0.0, kind="door"),
                OpeningSpec(wall_index=3, start_m=1.0, width_m=1.1, height_m=1.2, sill_height_m=0.9, kind="window"),
            ],
        ),
        "den": RoomSpec(
            "den",
            width_m=3.2,
            depth_m=3.8,
            height_m=2.4,
            openings=[
                OpeningSpec(wall_index=2, start_m=1.15, width_m=0.85, height_m=2.0, sill_height_m=0.0, kind="door"),
                OpeningSpec(wall_index=1, start_m=1.3, width_m=1.0, height_m=1.1, sill_height_m=0.95, kind="window"),
            ],
        ),
        "damage_room": RoomSpec(
            "damage_room",
            width_m=4.0,
            depth_m=3.5,
            height_m=2.5,
            openings=[OpeningSpec(wall_index=2, start_m=1.3, width_m=0.9, height_m=2.0, sill_height_m=0.0, kind="door")],
        ),
    }
    return rooms


def true_global_placements() -> dict[str, dict]:
    """Rooms placed in a straight line, each centered on the shared connector wall of its
    neighbor (not corner-aligned) -- stitch_rooms' connector correction aligns *wall
    midpoints*, so for the ablation to be a fair/meaningful test the ground-truth layout must
    itself be consistent with two connected rooms sharing the same physical wall segment.
    """
    lr_w, lr_d = 5.5, 4.5
    hw_w, hw_d = 1.5, 3.0
    hw_z = lr_d / 2 - hw_d / 2
    bd_d = 3.4
    bd_z = hw_z + hw_d / 2 - bd_d / 2
    return {
        "living_room": {"x": 0.0, "z": 0.0, "rotation_rad": 0.0},
        "hallway": {"x": lr_w, "z": hw_z, "rotation_rad": 0.0},
        "bedroom": {"x": lr_w + hw_w, "z": bd_z, "rotation_rad": 0.0},
    }


def drifted_placements() -> dict[str, dict]:
    true = true_global_placements()
    drift = {
        "living_room": {"x": 0.0, "z": 0.0, "rotation_rad": 0.0},
        "hallway": {"x": 0.12, "z": -0.08, "rotation_rad": np.radians(8.0)},
        "bedroom": {"x": 0.25, "z": -0.19, "rotation_rad": np.radians(15.0)},
    }
    out = {}
    for room_id, t in true.items():
        d = drift[room_id]
        out[room_id] = {"x": t["x"] + d["x"], "z": t["z"] + d["z"], "rotation_rad": t["rotation_rad"] + d["rotation_rad"]}
    return out


def main():
    rooms = build_rooms()
    ground_truth: dict = {"rooms": {}, "multi_room_property": {}, "damage": {}}

    for room_id, spec in rooms.items():
        ground_truth["rooms"][room_id] = {
            "width_m": spec.width_m,
            "depth_m": spec.depth_m,
            "height_m": spec.height_m,
            "openings": [asdict(o) for o in spec.openings],
        }

    _save_cloud("repeat_room_a", rooms["repeat_room"], seed=101, furniture=2)
    _save_cloud("repeat_room_b", rooms["repeat_room"], seed=202, furniture=2)
    ground_truth["rooms"]["repeat_room"]["captures"] = ["repeat_room_a", "repeat_room_b"]

    for room_id, seed in [("living_room", 1), ("hallway", 2), ("bedroom", 3), ("den", 4)]:
        _save_cloud(room_id, rooms[room_id], seed=seed, furniture=2)

    _save_cloud("damage_room", rooms["damage_room"], seed=5, furniture=3)

    ground_truth["multi_room_property"] = {
        "rooms": ["living_room", "hallway", "bedroom"],
        "connectors": [
            {"room_a": "living_room", "wall_a": 1, "room_b": "hallway", "wall_b": 0},
            {"room_a": "hallway", "wall_a": 1, "room_b": "bedroom", "wall_b": 0},
        ],
        "true_global_placements": true_global_placements(),
        "drifted_placements": drifted_placements(),
    }

    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    with open(OUT_ROOT / "ground_truth.json", "w") as f:
        json.dump(ground_truth, f, indent=2)
    print(f"Wrote synthetic benchmark to {OUT_ROOT} ({len(rooms) + 1} point clouds, ground_truth.json)")


if __name__ == "__main__":
    main()
