# 03 — Algorithms

## LiDAR tier ingestion ([cozmoscan/capture/stray_scanner.py](../cozmoscan/capture/stray_scanner.py))

Real parser for [Stray Scanner](https://docs.strayrobots.io/apps/scanner/overview.html) app
exports (see [04_capture_protocol.md](04_capture_protocol.md)). For each (frame-strided, default
~220 frames) sampled frame: reads the 16-bit depth PNG (256x192) and uint8 ARKit confidence PNG,
scales the per-frame RGB intrinsics down to depth resolution, unprojects every (pixel-strided)
depth pixel to camera-frame 3D, then to world frame via that frame's pose
(`Pose.camera_to_world()`). Points are weighted by their ARKit confidence value (0/1/2) and the
whole cloud is voxel-downsampled (1cm cells) afterward, both for performance and to avoid
massively overweighting near-camera oversampled regions.

## Video tier ingestion ([cozmoscan/capture/video_tier.py](../cozmoscan/capture/video_tier.py))

Simulates what a non-LiDAR iPhone's ARKit VIO would give you: posed RGB only, depth/confidence
**deliberately discarded** even though the same Stray Scanner capture has them (disclosed in
`CaptureBundle.meta["note"]`). Pipeline: motion-based keyframe selection (new keyframe once
translation/rotation since the last one crosses a threshold, itself scaled to total path length
so a full long walk-through is still covered within a keyframe budget — not a fixed frame
count, which was an early bug, see below) -> Lucas-Kanade optical-flow point tracking across
consecutive keyframes -> linear DLT multi-view triangulation
([cozmoscan/geometry/triangulation.py](../cozmoscan/geometry/triangulation.py)) for every track,
filtered by minimum parallax angle (>=1.5°), max reprojection error, and max point distance
(12m) — standard SfM robustness checks that reject degenerate near-parallel-ray triangulations.

**Known sensing limit (not a bug):** sparse monocular triangulation only densely reconstructs
near-camera, textured/furnished regions — distant blank walls produce few or no triangulated
points. `fit_room_box()` is given the camera trajectory itself (`trajectory_xz`) as a physical
sanity floor: the fitted footprint can never be smaller than the trajectory's own bounding box
(+0.3m standoff), with a wide CI and an explicit note whenever this fallback is what determined
the size. This produces plausible, honestly-uncertain boxes instead of nonsensical sub-meter
ones when point coverage is too sparse to trust directly.

## Photo tier ingestion ([cozmoscan/capture/photo_tier.py](../cozmoscan/capture/photo_tier.py))

Classical single-view ground-plane metrology — no depth, no pose, no multi-view matching.
Samples `n_photos` (default 4) stills from the capture's video. For each still: Canny edges +
probabilistic Hough line transform, finds the floor-wall and ceiling-wall boundary rows
(near-horizontal lines), then uses an **assumed level camera at a fixed eye height** (default
1.5m, a disclosed capture-protocol assumption) to anchor absolute scale — similar-triangles depth
from the floor-boundary row gives the ground-plane depth at the far wall, and the same
floor-row/ceiling-row vertical relation gives ceiling height directly, without needing a second
reference feature. Results are **median-aggregated** across all sampled photos for outlier
robustness (confirmed working: a single photo that produced ~35-42m nonsense was correctly
outvoted by 2 reasonable photos via the median). `photo_room_model()` builds a simple rectangle
RoomModel from the resulting scalar width/depth/ceiling-height measurements and explicitly
reports **zero openings per wall with a disclosure note** — a single still has no overlapping
coverage to detect openings from, so the tier never guesses them.

## Manhattan room-box reconstruction ([cozmoscan/geometry/manhattan_room.py](../cozmoscan/geometry/manhattan_room.py))

`fit_room_box(cloud, tier, room_id, config, trajectory_xz=None) -> RoomModel` is the shared,
tier-agnostic core (LiDAR and video tiers both feed it a `WeightedPointCloud`; photo tier
bypasses it entirely, see above). Four steps, each reusing the generic 1D peak-finder in
[cozmoscan/geometry/histogram.py](../cozmoscan/geometry/histogram.py) (bin -> merge adjacent
bins -> keep peaks with enough support) rather than full 3D plane RANSAC:

1. **Floor/ceiling**: histogram of point Y (up) values -> the two strongest peaks are floor and
   ceiling. If only one peak is found, ceiling is reported as `None` with a note (e.g. real
   captures where the camera never tilted up) — never guessed.
2. **Manhattan angle**: RANSAC 2D line fit on points in a mid-height "wall band" (adaptively
   widened if too few points fall in it) finds the dominant wall-facing angle `theta0`.
3. **Wall positions**: rotate all points by `-theta0` so walls become axis-aligned, then
   histogram-peak-find along each of the two rotated axes (u, v) to get 4 wall positions. Degrades
   gracefully (wide CI, raw-extent fallback) when an axis has fewer than 2 peaks (e.g. a wall
   never observed by the capture path).
4. **Openings** (per wall): build a 2D occupancy grid (position-along-wall x height) of
   near-wall points. Columns with insufficient vertical coverage are opening candidates,
   classified `door` (sill <=0.15m) vs `window` otherwise. **This step was the subject of the
   Part-4 fix loop** (over-detection on sparse/occluded data) — see
   [09_fix_loop.md](09_fix_loop.md) for the full root-cause/fix/before-after. Current algorithm
   (`ManhattanConfig.adaptive_opening_bins=True`, the default): classifies by the **longest
   contiguous empty run** as a fraction of the valid height band (not mean coverage — mean
   coverage at realistic sparse density sits right on the noise floor, see fix-loop writeup),
   then refines the reported start/width by snapping to the nearest real points just outside the
   gap, searched only within the gap's own height band. The pre-fix fixed-grid algorithm is kept
   (`adaptive_opening_bins=False`) purely so the before/after comparison stays regenerable.

## Confidence intervals

Geometry-tier (LiDAR/video) measurements: `ci = ci_k * spread`, where `spread` is the relevant
histogram peak's dispersion statistic and `ci_k` is a single calibrated multiplier (currently
**2.8**, see [07_benchmark_methodology.md](07_benchmark_methodology.md) for the calibration
method — not an arbitrary choice). Photo-tier measurements use `ci = ci_frac * value`, split into
**two** fractions (not one flat number) after real cross-tier evidence showed the two error modes
are wildly different in practice: `ci_frac_ceiling` (**15%**) for vertical/ceiling-height
metrology, and `ci_frac_lateral` (**55%**) for lateral wall-width/room-depth/floor-area metrology
— see [08_benchmark_report.md](08_benchmark_report.md) for the real numbers that drove the 55%
figure and [11_known_limitations.md](11_known_limitations.md) for the full disclosure.

## Multi-room stitching ([cozmoscan/geometry/stitching.py](../cozmoscan/geometry/stitching.py))

`stitch_rooms(rooms, placements, connectors, correct_drift, anchor_room_id)` combines N
independently-reconstructed rooms into one globally-consistent property. `Connector(room_a,
wall_a, room_b, wall_b)` declares which wall pairs are physically shared/adjacent.
`RoomPlacement(room_id, x, z, rotation_rad)` is each room's initial (e.g. VIO-estimated) global
pose. With `correct_drift=False`, rooms are placed exactly at their given placements (the
"raw/uncorrected" ablation arm). With `correct_drift=True` (default): a BFS/frontier relaxation
walks the connector graph from the anchor room, and for each newly-placed room, **snaps its
rotation to the nearest 90°** relative to its already-placed neighbor and solves the translation
so the shared wall's midpoints align exactly. The remaining 180° ambiguity (a wall's direction
sense is not a reliable cross-room convention — confirmed empirically, not assumed) is resolved
using a physically-meaningful invariant instead: **the two rooms' interiors must end up on
opposite sides of the shared wall** (a cross-product side test against each room's own
centroid). This correction is what the drift-ablation gate measures: corrected corner error
1.7-2.5cm vs 84-216cm uncorrected, on the same synthetic 3-room property with injected drift.

## Damage detection ([cozmoscan/damage/detector.py](../cozmoscan/damage/detector.py))

Two classical CV detectors, deliberately not ML (no training data available, and the spec
doesn't require it): **moisture stains** via HSV color-anomaly-from-background-median (flags
regions whose hue/saturation deviate from the surface's own dominant color, so it doesn't need a
hardcoded "stain color"); **structural cracks** via Canny edges filtered for elongated,
low-width connected shapes (aspect-ratio + thinness heuristics). Both return pixel-space
`DamageDetection` polygons (simplified via `cv2.approxPolyDP`), converted to real-world meters
by `to_damage_region()` given a known pixels-per-meter scale for that photo (supplied per
`DamagePhotoSpec`, e.g. from a reference object or known camera distance/FOV at capture time).

## Concealed-risk rules + scope generation

[cozmoscan/damage/rules.py](../cozmoscan/damage/rules.py): a small ordered rule table, checked
most-specific-first — metadata-backed rules (e.g. "moisture stain on a wall tagged
`has_plumbing`" -> `mold_or_rot_behind_wall`) take priority over area/length-only fallback
heuristics (e.g. "stain area >= 0.3m²" or "crack extent >= 1.5m"). Every flag records the rule
name that fired (`concealed_rule`), so the inference is auditable — never a bare "risky: true/false".
Without any `SurfaceTag` metadata supplied, only the fallback heuristics can fire — an honest
default, the engine never assumes building context it wasn't told.

[cozmoscan/damage/scope.py](../cozmoscan/damage/scope.py): a deterministic
`damage_class -> [ScopeLineItem, ...]` lookup (e.g. moisture stain -> remove+install drywall +
prime/repaint, each quantity = measured area x a disclosed waste/feather factor, 1.15x/1.3x).
Every quantity traces back to a measured number, never a guessed one.
