"""Calibrates ManhattanConfig.ci_k (the multiplier applied to each measurement's raw
histogram-peak 'spread' to produce its reported confidence interval) against the ONLY source of
ground truth available for the geometry tiers: the synthetic benchmark's known true wall
lengths and ceiling heights (benchmark/synthetic_rooms.py RoomSpec).

Method (disclosed, not hidden): for every wall-length and ceiling-height measurement across all
6 synthetic rooms, compute residual = |measured.value - true_value| and raw_spread =
measured.ci / CURRENT_CI_K (recovering the pre-multiplier spread, valid since ci is exactly
linear in ci_k). The ratio residual/raw_spread tells us, in units of "how many raw-spreads would
the CI need to span to cover this particular error". The calibrated ci_k is the MAX of that
ratio across all samples (n=30: 24 wall lengths + 6 ceiling heights) -- i.e. the smallest k that
would have made every single disclosed CI in this benchmark actually contain the true value.

This is a deliberately simple/conservative calibration (not a percentile/statistical-coverage
fit) because n=30 is too small to support a tighter percentile claim honestly. See
docs/07_benchmark_methodology.md for the full writeup and this script's caveats.

Run: python -m benchmark.calibrate_ci
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from benchmark.evaluate import match_wall_indices
from benchmark.gates import ALL_ROOMS, _fit_all
from cozmoscan.geometry.manhattan_room import ManhattanConfig

CURRENT_CI_K = 2.0  # the ci_k value in effect while this script runs (must match the config below)


def _wall_true_length(spec, gen_wall_index: int) -> float:
    return spec.depth_m if gen_wall_index in (0, 1) else spec.width_m


def collect_samples() -> list[dict]:
    cfg = ManhattanConfig(ci_k=CURRENT_CI_K)
    rooms, specs = _fit_all(cfg)
    samples = []
    for room_name, spec_name in ALL_ROOMS.items():
        room, spec = rooms[room_name], specs[spec_name]
        mapping = match_wall_indices(room, spec)
        for gen_idx, recon_idx in mapping.items():
            wall = room.walls[recon_idx]
            true_len = _wall_true_length(spec, gen_idx)
            residual = abs(wall.length.value - true_len)
            raw_spread = wall.length.ci / CURRENT_CI_K
            ratio = (residual / raw_spread) if raw_spread > 1e-9 else (0.0 if residual < 1e-9 else float("inf"))
            samples.append({
                "room": room_name, "quantity": f"wall_{gen_idx}_length", "true_value": true_len,
                "measured_value": wall.length.value, "residual": residual, "raw_spread": raw_spread, "ratio": ratio,
            })
        if room.ceiling_height is not None:
            residual = abs(room.ceiling_height.value - spec.height_m)
            raw_spread = room.ceiling_height.ci / CURRENT_CI_K
            ratio = (residual / raw_spread) if raw_spread > 1e-9 else (0.0 if residual < 1e-9 else float("inf"))
            samples.append({
                "room": room_name, "quantity": "ceiling_height", "true_value": spec.height_m,
                "measured_value": room.ceiling_height.value, "residual": residual, "raw_spread": raw_spread, "ratio": ratio,
            })
    return samples


def main() -> dict:
    samples = collect_samples()
    ratios = np.array([s["ratio"] for s in samples if np.isfinite(s["ratio"])])
    n_inf = sum(1 for s in samples if not np.isfinite(s["ratio"]))
    calibrated_ci_k = float(np.max(ratios)) if len(ratios) else CURRENT_CI_K
    result = {
        "current_ci_k": CURRENT_CI_K,
        "n_samples": len(samples),
        "n_infinite_ratio_excluded": n_inf,
        "ratio_stats": {
            "min": float(np.min(ratios)), "median": float(np.median(ratios)),
            "mean": float(np.mean(ratios)), "max": float(np.max(ratios)),
        },
        "calibrated_ci_k": calibrated_ci_k,
        "samples": samples,
    }
    out_path = Path("benchmark/ci_calibration.json")
    out_path.write_text(json.dumps(result, indent=2))
    print(f"n={len(samples)} (excluded {n_inf} infinite-ratio samples)")
    print(f"ratio residual/raw_spread: min={result['ratio_stats']['min']:.3f} median={result['ratio_stats']['median']:.3f} "
          f"mean={result['ratio_stats']['mean']:.3f} max={result['ratio_stats']['max']:.3f}")
    print(f"current ci_k={CURRENT_CI_K} -> calibrated ci_k={calibrated_ci_k:.3f} (max-ratio method, see module docstring)")
    print(f"wrote {out_path}")
    return result


if __name__ == "__main__":
    main()
