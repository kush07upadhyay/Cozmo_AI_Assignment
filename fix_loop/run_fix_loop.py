"""Regenerable fix-loop comparison: opening over-detection at sparse point density
(cozmoscan.geometry.manhattan_room._detect_openings). See fix_loop/fix_declaration.md for the
full root-cause writeup.

Run: python -m fix_loop.run_fix_loop
Produces fix_loop/before_metrics.json, fix_loop/after_metrics.json, fix_loop/diff.md.

Both "before" and "after" run the *same current code* -- the only difference is the
``adaptive_opening_bins`` config flag, which was specifically kept as an opt-out so this
comparison stays runnable forever (no need to check out an old git commit).
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from benchmark.evaluate import match_wall_indices, opening_accuracy
from benchmark.generate_synthetic_benchmark import build_rooms
from cozmoscan.geometry.manhattan_room import ManhattanConfig, fit_room_box
from cozmoscan.types import WeightedPointCloud

BENCH_ROOT = Path("Sample_data_to_run_code/synthetic_benchmark")
OUT_DIR = Path("fix_loop")

ROOM_FILES = {
    "repeat_room_a": "repeat_room",
    "repeat_room_b": "repeat_room",
    "living_room": "living_room",
    "hallway": "hallway",
    "bedroom": "bedroom",
    "den": "den",
}


def _run(adaptive: bool) -> dict:
    specs = build_rooms()
    cfg = ManhattanConfig(adaptive_opening_bins=adaptive)
    per_room = {}
    all_opening_results = []
    for room_name, spec_name in ROOM_FILES.items():
        npz = np.load(BENCH_ROOT / room_name / "points.npz")
        cloud = WeightedPointCloud(points=npz["points"], weights=npz["weights"], source_tier="lidar")
        room = fit_room_box(cloud, tier="lidar", room_id=room_name, config=cfg)
        spec = specs[spec_name]
        mapping = match_wall_indices(room, spec)
        results = opening_accuracy(room, spec, mapping)
        n_detected_total = sum(len(w.openings) for w in room.walls)
        per_room[room_name] = {
            "n_openings_detected_total": n_detected_total,
            "n_openings_ground_truth": len(spec.openings),
            "matched_results": results,
        }
        all_opening_results.extend(results)

    n_gt = len(all_opening_results)
    n_detected = sum(1 for r in all_opening_results if r["detected"])
    n_within_tol = sum(1 for r in all_opening_results if r["within_tol"])
    width_errors = [r["width_error_m"] for r in all_opening_results if r["detected"]]

    return {
        "adaptive_opening_bins": adaptive,
        "per_room": per_room,
        "gate_opening_detection_rate": n_detected / n_gt if n_gt else 0.0,
        "gate_opening_within_2cm_rate": n_within_tol / n_gt if n_gt else 0.0,
        "mean_width_error_m": float(np.mean(width_errors)) if width_errors else None,
        "max_width_error_m": float(np.max(width_errors)) if width_errors else None,
        "total_false_positive_openings": sum(p["n_openings_detected_total"] for p in per_room.values()) - n_detected,
    }


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    before = _run(adaptive=False)
    after = _run(adaptive=True)

    with open(OUT_DIR / "before_metrics.json", "w") as f:
        json.dump(before, f, indent=2)
    with open(OUT_DIR / "after_metrics.json", "w") as f:
        json.dump(after, f, indent=2)

    lines = [
        "# Fix Loop Diff: Opening Over-Detection\n",
        "Regenerate with `python -m fix_loop.run_fix_loop`.\n",
        "| Room | Detected (before) | Detected (after) | Ground truth |",
        "|------|--------------------|--------------------|---------------|",
    ]
    for room_name in ROOM_FILES:
        b = before["per_room"][room_name]["n_openings_detected_total"]
        a = after["per_room"][room_name]["n_openings_detected_total"]
        gt = before["per_room"][room_name]["n_openings_ground_truth"]
        lines.append(f"| {room_name} | {b} | {a} | {gt} |")

    lines += [
        "",
        "| Metric | Before | After |",
        "|--------|--------|-------|",
        f"| Opening detection rate (gate: >=85%) | {before['gate_opening_detection_rate']:.1%} | {after['gate_opening_detection_rate']:.1%} |",
        f"| Opening width within 2cm rate | {before['gate_opening_within_2cm_rate']:.1%} | {after['gate_opening_within_2cm_rate']:.1%} |",
        f"| Mean width error (m) | {before['mean_width_error_m']:.4f} | {after['mean_width_error_m']:.4f} |",
        f"| Total false-positive opening detections (sum over rooms) | {before['total_false_positive_openings']} | {after['total_false_positive_openings']} |",
    ]
    (OUT_DIR / "diff.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
