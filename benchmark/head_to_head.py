"""Part 3: head-to-head comparison vs. a real consumer scanning app (Polycam / magicplan free
tier), LiDAR tier, on shared dimensions for >=2 rooms. Target: cozmoscan beats-or-ties the
consumer app on >=70% of shared dimensions (wall lengths, ceiling height, floor area) against
independently-measured ground truth (laser/tape).

STATUS, disclosed honestly (see docs/11_known_limitations.md): this script has NEVER been run
against real numbers. This sandbox has no iPhone/iPad, no Mac, no Xcode, and cannot install or
run Polycam/magicplan (both are iOS/Android-only apps with no usable free-tier desktop or web
equivalent). There is therefore no way to produce a genuine head-to-head result here. Rather
than fabricate plausible-looking numbers (which would be confident garbage -- worse than an
honest gap), this module ships as a fully working, ready-to-run comparison engine: give it two
JSON files shaped as below, from an actual capture session on physical hardware, and it computes
the real result.

Expected input JSON shape (one file per system being compared, cozmoscan and the consumer app):
{
  "room_a": {"wall_0_length": 5.30, "wall_1_length": 5.30, "wall_2_length": 4.20,
             "wall_3_length": 4.20, "ceiling_height": 2.70, "floor_area": 22.26},
  "room_b": {...}
}
And one ground-truth JSON file in the same shape, populated from physical laser/tape
measurements of the same 2 (or more) real rooms.

Run (once real data exists):
    python -m benchmark.head_to_head --cozmo cozmo_measurements.json --consumer app_measurements.json \\
        --ground-truth ground_truth.json [--tol-m 0.02]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def compare(cozmo: dict, consumer: dict, ground_truth: dict, tol_m: float = 0.02) -> dict:
    """For every (room, dimension) present in ALL THREE inputs, compares |error| of each system
    against ground truth. A dimension counts as a cozmoscan "win" if its error is strictly
    smaller, a "tie" if both errors are within ``tol_m`` of each other, else a "loss"."""
    per_dim = []
    for room_id, gt_dims in ground_truth.items():
        if room_id not in cozmo or room_id not in consumer:
            continue
        for dim, true_val in gt_dims.items():
            if dim not in cozmo[room_id] or dim not in consumer[room_id]:
                continue
            cozmo_err = abs(cozmo[room_id][dim] - true_val)
            consumer_err = abs(consumer[room_id][dim] - true_val)
            if abs(cozmo_err - consumer_err) <= tol_m:
                outcome = "tie"
            elif cozmo_err < consumer_err:
                outcome = "win"
            else:
                outcome = "loss"
            per_dim.append({
                "room_id": room_id, "dimension": dim, "true_value": true_val,
                "cozmo_error_m": cozmo_err, "consumer_error_m": consumer_err, "outcome": outcome,
            })

    n = len(per_dim)
    n_beat_or_tie = sum(1 for d in per_dim if d["outcome"] in ("win", "tie"))
    rate = n_beat_or_tie / n if n else 0.0
    return {
        "name": "head_to_head_vs_consumer_app",
        "requirement": "beat-or-tie consumer app on >=70% of shared dimensions, LiDAR tier, >=2 rooms, vs physical ground truth",
        "n_shared_dimensions": n,
        "n_beat_or_tie": n_beat_or_tie,
        "beat_or_tie_rate": rate,
        "passed": (n > 0) and (rate >= 0.70),
        "per_dimension": per_dim,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cozmo", required=True, help="JSON: cozmoscan's measured dimensions per room.")
    parser.add_argument("--consumer", required=True, help="JSON: consumer app's measured dimensions per room.")
    parser.add_argument("--ground-truth", required=True, help="JSON: physically (laser/tape) measured true dimensions per room.")
    parser.add_argument("--tol-m", type=float, default=0.02, help="Tie threshold in meters (default 2cm).")
    parser.add_argument("--out", default="benchmark/head_to_head_result.json")
    args = parser.parse_args(argv)

    cozmo = json.loads(Path(args.cozmo).read_text())
    consumer = json.loads(Path(args.consumer).read_text())
    ground_truth = json.loads(Path(args.ground_truth).read_text())
    result = compare(cozmo, consumer, ground_truth, tol_m=args.tol_m)

    Path(args.out).write_text(json.dumps(result, indent=2))
    status = "PASS" if result["passed"] else "FAIL"
    print(f"[{status}] {result['name']}: {result['n_beat_or_tie']}/{result['n_shared_dimensions']} "
          f"({result['beat_or_tie_rate']:.1%}) beat-or-tie, target >=70%")
    print(f"wrote {args.out}")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
