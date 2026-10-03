# 08 - Benchmark Report

All numbers below are regenerated, not hand-typed: `python -m benchmark.gates` (synthetic
ground-truth gates), `python -m benchmark.calibrate_ci` (CI calibration), `python -m
benchmark.real_data_report` (real-capture timing + cross-tier consistency), `python -m
fix_loop.run_fix_loop` (before/after fix-loop numbers). Every table here is a direct
transcription of one of those scripts' JSON output - see each file for full raw data.

## 1. Gates (synthetic ground truth, 6 rooms, LiDAR tier)

| Gate | Requirement | Result | Status |
|---|---|---|---|
| `opening_widths` | detection >=85%, width err <=2cm for >=85% of openings | detection 100%, within-2cm 41.7% | ❌ FAIL |
| `ceiling_height` | max abs error <=1.5cm, all rooms | 5/6 rooms <0.1mm; `repeat_room_b` 2.0cm | ❌ FAIL |
| `repeatability` | per-wall diff <=1cm or <=0.5% | worst 2.0cm abs / 0.376% rel (passes on the OR) | ✅ PASS |
| `drift_ablation` | corrected <=5cm AND better than uncorrected | corrected 1.7-2.5cm vs raw 84-216cm | ✅ PASS |
| `photo_tier_whole_property_stitch` | footprint within ±8%, no overlaps | not computed - no ground-truthed multi-room photo data exists | ⚠️ UNKNOWN |

Full reasoning and root causes for the 2 failing gates: [11_known_limitations.md](11_known_limitations.md) items 1-2. Reproduce: `python -m benchmark.gates` (writes [benchmark/gate_results.json](../benchmark/gate_results.json)).

## 2. Repeatability detail (`repeat_room_a` vs `repeat_room_b`, same `RoomSpec`, different seed)

| Wall | Length A (m) | Length B (m) | Abs error (m) | Rel error |
|---|---|---|---|---|
| 0 | 5.32 | 5.30 | 0.0200 | 0.376% |
| 1 | 5.32 | 5.30 | 0.0200 | 0.376% |
| 2 | 4.20 | 4.20 | ~0 | ~0% |
| 3 | 4.20 | 4.20 | ~0 | ~0% |

Worst case (2.0cm / 0.376%) passes the gate's `<=1cm OR <=0.5%` OR-condition on the relative
branch.

## 3. Drift ablation detail (`living_room`→`hallway`→`bedroom`, living_room = anchor)

| Room | Corner error, drift OFF (m) | Corner error, drift ON (m) |
|---|---|---|
| living_room (anchor) | 0.000 | 0.000 |
| hallway | 0.836 | 0.017 |
| bedroom | 2.158 | 0.025 |

Drift correction is not just "better than nothing" - it's a ~49x–87x reduction in corner error,
and the anchor room's error is exactly 0 in both conditions by construction (sanity-checked, see
[07_benchmark_methodology.md](07_benchmark_methodology.md)).

## 4. CI calibration

- `ManhattanConfig.ci_k`: calibrated to **2.8** (raw max-ratio 2.723, rounded up), from n=30
 synthetic wall-length + ceiling-height samples. Full method: [07_benchmark_methodology.md](07_benchmark_methodology.md). Raw data: [benchmark/ci_calibration.json](../benchmark/ci_calibration.json).
- Photo tier `ci_frac_ceiling`=0.15, `ci_frac_lateral`=0.55 - see §5 below for the real-data
 evidence that drove the lateral figure specifically.

## 5. Real-data cross-tier consistency + timing (3 real captures, all 3 tiers, no true ground truth)

Reproduce: `python -m benchmark.real_data_report` (writes [benchmark/real_data_report.json](../benchmark/real_data_report.json)). LiDAR is used as the reference tier (most sensor-rich), **not** a
substitute for true laser/tape ground truth - see [07_benchmark_methodology.md](07_benchmark_methodology.md) for why this check exists and its limits.

### Timing (wall-clock, this dev machine, CPU-only)

| Capture | Tier | Load (s) | Reconstruct (s) | Total (s) |
|---|---|---|---|---|
| single_room (26m²) | lidar | 5.36 | 0.32 | 5.68 |
| single_room | video | 15.21 | 0.01 | 15.22 |
| single_room | photo | 3.37 | 0.00 | 3.37 |
| single_scan_floor_only (87m²) | lidar | 5.72 | 0.31 | 6.03 |
| single_scan_floor_only | video | 39.94 | 0.04 | 39.98 |
| single_scan_floor_only | photo | 11.50 | 0.00 | 11.50 |
| single_scan_with_ceiling (92m²) | lidar | 7.43 | 0.31 | 7.74 |
| single_scan_with_ceiling | video | 78.04 | 0.02 | 78.06 |
| single_scan_with_ceiling | photo | 20.48 | 0.00 | 20.48 |

LiDAR is fast and flat (~6-8s regardless of room size - dominated by fixed point-cloud I/O, not
reconstruction, which is consistently <0.35s). Video scales with frame count/room size (15s-78s)
- optical-flow tracking across every sampled frame is the dominant cost. Photo scales mildly with
video length (it samples stills from the same source video, 3.4s-20.5s). All 9 runs are well
within the spec's "<15 min fresh run" budget for a single capture.

### Cross-tier wall-length / floor-area consistency vs. LiDAR

| Capture | Tier | Wall-length rel. err | Tolerance | Within tolerance? | Floor-area rel. err |
|---|---|---|---|---|---|
| single_room | video | 13.6% | ±3% | ❌ | 25.4% |
| single_room | photo | 18.7% | ±8% | ❌ | 34.5% |
| single_scan_floor_only | video | 5.6% | ±3% | ❌ | 11.4% |
| single_scan_floor_only | photo | 50.6% | ±8% | ❌ | 75.7% |
| single_scan_with_ceiling | video | 4.9% | ±3% | ❌ | 6.5% |
| single_scan_with_ceiling | photo | 48.9% | ±8% | ❌ | 74.1% |

**Honest reading**: neither tier currently meets its target on real data. Video is moderately
off (close on 2 of 3 rooms: 4.9%/5.6% vs a 3% target); photo is far off on the 2 larger/more
open rooms (48.9%/50.6%) and moderately off on the smallest (18.7%). This directly drove
widening `ci_frac_lateral` to 55% (§4) rather than leaving a falsely narrow 15% figure in place
- see [11_known_limitations.md](11_known_limitations.md) item 4 for the full disclosure and root
cause (single-view similar-triangles depth estimation is sensitive to horizon-row error, which
compounds with room size/distance and gets worse with only a few sampled stills on a large room).
Ceiling height (ceiling-only, not shown as a row above since it's a separate measurement from
wall length) remains close: photo-tier readings of 2.98m/2.93m/2.97m vs LiDAR's single
comparable reading of 3.06m (one capture never tilted up far enough for LiDAR to observe a
ceiling) - within the disclosed `ci_frac_ceiling=0.15`.

## 6. Head-to-head vs. consumer app (Part 3)

**Table intentionally empty - not fabricated.** `benchmark/head_to_head.py` is complete and
tested (toy-number logic validation, not committed as fake results) but was never run for real:
this sandbox has no iPhone/iPad/Mac to install Polycam/magicplan or capture physical ground
truth. See [11_known_limitations.md](11_known_limitations.md) item 14. Ready to run the moment
real captures + ground truth exist:
```
python -m benchmark.head_to_head --cozmo <cozmo.json> --consumer <consumer.json> --ground-truth <gt.json>
```

## 7. Fix loop before/after (Part 4)

| Metric | Before | After |
|---|---|---|
| Opening detection rate | 100%* | 100% |
| Total false-positive opening detections | 49 | 0 |
| Opening width within-2cm rate | 0.0% | 41.7% |
| Mean width error | 0.3667m | 0.0236m |

\* "100% detection" pre-fix is misleading in isolation - it means every true opening was *among*
a flood of 49 false positives (6-14 "openings" detected per room vs 2 true), not that detection
was precise. See [09_fix_loop.md](09_fix_loop.md) for the full story.
