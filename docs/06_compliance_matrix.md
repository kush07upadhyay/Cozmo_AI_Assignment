# 06 - Compliance Matrix

Requirement text is quoted/paraphrased directly from `Applied_AI_Case_Study.pdf` (extracted and
re-verified against the source PDF while writing this matrix - not from memory alone). Status
legend: ✅ done · ⚠️ partial/disclosed gap · ❌ not done.

## Part 1 - Capture

| Requirement | Status | Evidence |
|---|---|---|
| Choose Route 1 (own iOS app) or Route 2 (stock capture protocol) | ✅ Route 2 | [04_capture_protocol.md](04_capture_protocol.md) - Stray Scanner, one-pager. Route 1 explicitly disclosed as not built (no Mac/Xcode in this sandbox), see [11_known_limitations.md](11_known_limitations.md). |
| Three input tiers, all mandatory, same output contract, intervals widen as data thins | ✅ | [cozmoscan/capture/{stray_scanner,video_tier,photo_tier}.py](../cozmoscan/capture/); all 3 feed the same `RoomModel` contract ([01_architecture.md](01_architecture.md)); CI widens photo(15%) > video/lidar(ci_k=2.8 histogram-based). |
| Photos: 2-8 stills/room, no depth/poses | ✅ (via sampling) / ⚠️ | `photo_tier.py` samples stills from a Stray Scanner video rather than ingesting a loose folder of 2-8 independent stills directly - functionally equivalent (no depth/pose used) but not the literal "folder of stills" ingestion path. See [11_known_limitations.md](11_known_limitations.md). |
| Video: handheld walkthrough clip | ✅ | `cozmoscan/capture/video_tier.py`, tested on all 3 real captures + synthetic. |
| LiDAR: depth, poses, intrinsics on Pro-class devices | ✅ | `cozmoscan/capture/stray_scanner.py`, real parser, tested on all 3 real captures. |
| Device matrix: which tier runs on which hardware, accuracy per tier | ✅ | [05_device_matrix.md](05_device_matrix.md). |

## Part 2 - Output contract and gates

| Requirement | Status | Evidence |
|---|---|---|
| Dimensioned per-room plan: walls, ceiling height, floor area, openings | ✅ | `RoomModel` ([02_data_model.md](02_data_model.md)), rendered by `plan_renderer.py`. |
| Stitched multi-room plan with correct adjacency | ✅ | `cozmoscan/geometry/stitching.py` + `run_stitch()`; validated against synthetic 3-room ground truth (drift-ablation gate). |
| Per-surface damage regions, class + metric extent | ✅ | `DamageRegion` (`damage_class`, `area_m2`, `extent_m`), `cozmoscan/damage/detector.py`. |
| Concealed-damage flags with the rule that fired | ✅ | `DamageRegion.concealed_risk`/`concealed_rule`, `cozmoscan/damage/rules.py` (named, versioned rules). |
| Scope line items keyed to surfaces | ✅ | `ScopeLineItem.surface_id`, `cozmoscan/damage/scope.py`. |
| Confidence interval on every measurement | ✅ | `Measurement.ci` on every wall length, opening width/height, ceiling height, floor area - structural, not a convention. |
| One command per capture | ✅ | `cozmoscan scan` (single capture dir -> JSON+PNG), see [README.md](../README.md). |
| JSON to published schema | ✅ | [schema/capture_output.schema.json](../schema/capture_output.schema.json), [schema/property_output.schema.json](../schema/property_output.schema.json), validated via `jsonschema` before every write. |
| Rendered plan | ✅ | `plan.png` / `property_plan.png`, see [docs/assets/](assets/) for examples. |
| Stitched plan produced from every tier including photos | ⚠️ | Mechanically works (photo-tier `RoomModel`s stitch through the same `stitch_rooms()`) but never run on a multi-room *photo* capture set (none exists - synthetic generator only produces point clouds). Disclosed gap, see gate 5 and [11_known_limitations.md](11_known_limitations.md). |
| Benchmark set: 1 multi-room (3+ rooms + connector) | ✅ | `living_room`/`hallway`/`bedroom`, `Sample_data_to_run_code/synthetic_benchmark/ground_truth.json`. |
| Benchmark set: 1 furnished room, staged damage, 2 classes | ✅ | `damage_room` (moisture_stain + structural_crack), [benchmark/generate_damage_images.py](../benchmark/generate_damage_images.py). |
| Benchmark set: same rooms at all 3 tiers | ⚠️ | True for the 3 REAL captures (lidar/video/photo all derived from the same Stray Scanner sessions). NOT true for the synthetic ground-truth rooms (point clouds only) - so quantitative gates 1-4 are effectively LiDAR-tier-only; video/photo tiers are exercised qualitatively on real data only. Disclosed in [08_benchmark_report.md](08_benchmark_report.md). |
| Benchmark set: >=1 room captured twice, same tier (repeatability) | ✅ | `repeat_room_a` / `repeat_room_b`. |
| Benchmark set: laser/tape ground truth on everything | ⚠️ | No physical room available in this sandbox -> synthetic ground truth used instead (spec explicitly sanctions building the benchmark set yourself). Real captures have no ground truth at all (disclosed, used for qualitative/integration testing only). |
| Gate: opening widths <=2cm @ >=85%, miss+phantom both count as miss | ✅ computed, ❌ fails | `benchmark/gates.py::gate_opening_widths` - 100% detection, 41.7% within 2cm. See [09_fix_loop.md](09_fix_loop.md). |
| Gate: ceiling height <=1.5cm/room, repeat-capture spread <=1cm | ✅ computed, ❌ fails (1 room) | `gate_ceiling_height` - 5/6 rooms <0.1mm, `repeat_room_b` at 2.0cm. |
| Gate: repeatability <=1cm or 0.5%/wall | ✅ computed, ✅ passes | `gate_repeatability`. |
| Gate: drift accountability, ablation on/off | ✅ computed, ✅ passes | `gate_drift_ablation` - 1.7-2.5cm corrected vs 84-216cm raw. |
| Gate: photo-tier whole-property stitch, ±8%, no overlaps | ⚠️ honestly UNKNOWN | `gate_photo_tier_stitch` returns `passed=None` with a detailed reason (no synthetic multi-room photo data exists). Not faked. |
| Photo-tier wall lengths within ±8%, video-tier ±3%, calibration scored at every tier | ⚠️ measured, currently misses target | No true ground truth exists for video/photo tiers (same root cause as the gate above), so `benchmark/real_data_report.py` measures a cross-tier-vs-LiDAR proxy on all 3 real captures instead ([08_benchmark_report.md](08_benchmark_report.md) §5). Result, honestly reported: **video** misses ±3% on all 3 rooms (13.6%/5.6%/4.9%); **photo** misses ±8% on all 3 (18.7%/50.6%/48.9%). `ci_k`=2.8 and `ci_frac_ceiling`/`ci_frac_lateral`=0.15/0.55 are calibrated at every tier regardless ([07_benchmark_methodology.md](07_benchmark_methodology.md)) so the *disclosed* uncertainty is not "confident garbage" even though underlying accuracy is currently short of target - see [11_known_limitations.md](11_known_limitations.md) item 4. |

## Part 3 - Head-to-head vs. consumer app

| Requirement | Status | Evidence |
|---|---|---|
| LiDAR tier vs. 1 consumer app (free tier OK), 2 rooms, 1 table, beat-or-tie >=70% shared dims | ⚠️ engine built, never run | [benchmark/head_to_head.py](../benchmark/head_to_head.py) - fully working `compare()` + CLI, logic validated with toy numbers. Never run for real: no iPhone/iPad/Mac in this sandbox to install Polycam/magicplan or capture physical ground truth. Disclosed explicitly in the module docstring and [11_known_limitations.md](11_known_limitations.md), not fabricated. |

## Part 4 - Fix loop (25% of score)

| Requirement | Status | Evidence |
|---|---|---|
| Declare worst gate + failing number | ✅ | [fix_loop/fix_declaration.md](../fix_loop/fix_declaration.md) §1-2 - opening widths, 0% within 2cm pre-fix. |
| Root-cause hypothesis + evidence | ✅ | §3 - Poisson-sparsity-vs-fixed-coverage-threshold, quantified. |
| Fix shipped + predicted number | ✅ | §4-5 - predicted 2-5 detected/room, achieved exactly 2/2 with 0 false positives (beat prediction); within-2cm rate 0%->41.7% (gate still fails, honestly reported - see below). |
| Before/after both regenerable, readable diff | ✅ | `python -m fix_loop.run_fix_loop`; [fix_loop/before_metrics.json](../fix_loop/before_metrics.json), [fix_loop/after_metrics.json](../fix_loop/after_metrics.json), [fix_loop/diff.md](../fix_loop/diff.md). |
| Scoring self-assessment | "Correct root cause, shipped fix, meaningful movement short of the gate" | The targeted failure mode (massive opening over-detection, 49 false positives) is fully fixed (0 false positives, exact 2/2 detection count in all 6 rooms). The *width-precision* sub-gate (>=85% within 2cm) is still short (41.7%) - root-caused and disclosed honestly in fix_declaration.md §5, not glossed over. |

## Part 5 - Process evidence

| Requirement | Status | Evidence |
|---|---|---|
| Commit as you work, incrementally, not 1-2 commits at the deadline | ✅ | Repo history: incremental commits per working milestone (scaffold, types+ingestion, video/photo tiers, stitching+damage+benchmark generator, fix loop, pipeline+CLI+schema, CI calibration, head-to-head, docs). `git log` reflects the actual build order. |

## Deliverables checklist

| # | Deliverable | Status | Evidence |
|---|---|---|---|
| 1 | Compliance matrix | ✅ | This file. |
| 2 | Capture route (TestFlight build or 1-pager) + device matrix | ✅ | [04_capture_protocol.md](04_capture_protocol.md), [05_device_matrix.md](05_device_matrix.md). |
| 3 | Repo + README, <15 min fresh run, 1 cmd/capture | ✅ | [README.md](../README.md). |
| 4 | Reproduction bundle (regenerate every number from raw inputs) | ✅ | Every benchmark/gate/calibration number is produced by a committed, runnable script (`benchmark/*.py`, `fix_loop/run_fix_loop.py`) against committed or regenerable inputs - no hand-typed numbers. |
| 5 | Benchmark report: gates at all 3 tiers, repeatability table, head-to-head table, timing | ⚠️ | [08_benchmark_report.md](08_benchmark_report.md) - gates computed (LiDAR-tier-equivalent synthetic ground truth + real-data cross-tier check for video/photo), repeatability table included, head-to-head table structurally ready but empty (no real run), timing included (`benchmark/real_data_report.py`). |
| 6 | Fix loop bundle | ✅ | `fix_loop/` folder, see [09_fix_loop.md](09_fix_loop.md). |
| 7 | Technical report, <=6 pages | ✅ | [technical_report.md](technical_report.md). |
| 8 | Raw benchmark data: sensor logs, ground truth, app exports | ✅ / ⚠️ | Synthetic ground truth + generator scripts committed; real captures' raw sensor logs are the provided zips (kept out of git as large provided fixtures, see [Sample_data_to_run_code/README.md](../Sample_data_to_run_code/README.md)); no consumer-app export exists (Part 3 never run for real). |

## Walk-in test readiness

| Requirement | Status | Evidence |
|---|---|---|
| CLI runs cold on an arbitrary new capture folder, any tier chosen on the day | ✅ | `cozmoscan scan --capture-dir <any Stray-Scanner-format folder> --tier {lidar,video,photo}` - the exact command path used for every smoke test in this submission (no special-casing of the 3 provided sample folders). |

## Constraints

| Constraint | Status | Evidence |
|---|---|---|
| Handheld consumer capture only | ✅ | Stray Scanner on consumer iPhone/iPad hardware. |
| Pretrained model/dataset/API usable with disclosure | N/A used | No pretrained model or external API used anywhere in this pipeline - pure classical CV/geometry (disclosed as a design choice, not a constraint violation). |
| Everything runs without calling your infrastructure | ✅ verified | `grep`-confirmed zero network-call code (`requests`/`urllib`/`socket`/etc.) anywhere in `cozmoscan/`. See [12_security_privacy.md](12_security_privacy.md). |
| Cover mirrors/glass/wet-look surfaces/low light | ✅ | [11_known_limitations.md](11_known_limitations.md) - disclosed as LiDAR/ARKit multipath failure modes and Hough/optical-flow degradation under low light. |
