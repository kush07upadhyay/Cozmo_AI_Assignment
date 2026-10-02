"""Regenerates the example rendered-plan images embedded in docs/ (docs/assets/). Not a gate or
test -- purely documentation evidence, kept as a real script (not a one-off) so the images stay
reproducible from the same synthetic ground truth used everywhere else in the benchmark.

Run: python -m benchmark.render_demo_assets
"""
from __future__ import annotations

from pathlib import Path

from benchmark.evaluate import drifted_placement_xzr, match_wall_indices
from benchmark.gates import MULTI_ROOM_IDS, _fit_all
from cozmoscan.geometry.manhattan_room import ManhattanConfig
from cozmoscan.geometry.stitching import Connector, RoomPlacement, stitch_rooms
from cozmoscan.render.plan_renderer import render_property_plan

OUT_DIR = Path("docs/assets")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rooms, specs = _fit_all(ManhattanConfig())

    maps = {rid: match_wall_indices(rooms[rid], specs[rid]) for rid in MULTI_ROOM_IDS}
    connectors = [
        Connector(room_a="living_room", wall_a=maps["living_room"][1], room_b="hallway", wall_b=maps["hallway"][0]),
        Connector(room_a="hallway", wall_a=maps["hallway"][1], room_b="bedroom", wall_b=maps["bedroom"][0]),
    ]
    # Zero drift (true placement): demonstrates the stitcher's steady-state output, not the
    # ablation's drift-injection path (that is a benchmark/gates.py concern, not a docs concern).
    zero_drift = {rid: (0.0, 0.0, 0.0) for rid in MULTI_ROOM_IDS}
    true_genframe_xzr = {
        "living_room": (0.0, 0.0, 0.0),
        "hallway": (specs["living_room"].width_m, 0.0, 0.0),
        "bedroom": (specs["living_room"].width_m + specs["hallway"].width_m, 0.0, 0.0),
    }
    placements = [
        RoomPlacement(rid, *drifted_placement_xzr(rooms[rid], true_genframe_xzr[rid], zero_drift[rid]))
        for rid in MULTI_ROOM_IDS
    ]
    stitched = stitch_rooms([rooms[rid] for rid in MULTI_ROOM_IDS], placements, connectors, correct_drift=True, anchor_room_id="living_room")
    render_property_plan(stitched, OUT_DIR / "property_plan_example.png", title="Example: 3-room stitched property (synthetic ground truth)")
    print(f"wrote {OUT_DIR / 'property_plan_example.png'}")


if __name__ == "__main__":
    main()
