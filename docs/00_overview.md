# 00 — Overview

Cozmo Scan is a 3-tier (Photo / Video / LiDAR) room-scanning pipeline: it turns a handheld
phone capture into a dimensioned, damage-annotated, schema-validated floor plan, in one command
per capture. Built end-to-end for the Applied AI Engineer case study
([Applied_AI_Case_Study.pdf](../Applied_AI_Case_Study.pdf)), against the real sample LiDAR
captures provided in [Sample_data_to_run_code/](../Sample_data_to_run_code/) plus a
self-built synthetic benchmark with known ground truth (the spec explicitly sanctions building
your own benchmark set).

**Start here:** [README.md](../README.md) for setup + the one-command run. This `docs/` folder
is the supporting detail; [technical_report.md](technical_report.md) is the condensed (<=6 page)
submission writeup if you only read one file.

## Map of this repo

| Path | What it is |
|---|---|
| `cozmoscan/` | The pipeline package: capture ingestion, geometry reconstruction, damage detection, rendering, orchestration, CLI. |
| `cozmoscan/pipeline.py` | `run_single_room()` / `run_stitch()` — the two entry points the CLI wraps. |
| `cozmoscan/cli.py` | `scan` / `stitch` subcommands (one command per capture). |
| `schema/` | Published JSON Schemas (draft-07) for both pipeline outputs. |
| `benchmark/` | Synthetic ground-truth generator, the 5 required gates, CI calibration, real-data cross-tier/timing report, head-to-head engine. |
| `fix_loop/` | Part-4 deliverable: declared gate, root cause, fix, before/after, regenerable. |
| `Sample_data_to_run_code/` | Provided real LiDAR captures + the generated synthetic benchmark. |
| `docs/` | This folder. |

## Map of this folder

| Doc | Content |
|---|---|
| [01_architecture.md](01_architecture.md) | Pipeline stages, data flow, package layout. |
| [02_data_model.md](02_data_model.md) | Every dataclass + the published JSON schemas. |
| [03_algorithms.md](03_algorithms.md) | How each stage actually works (geometry, CV, stitching, rules). |
| [04_capture_protocol.md](04_capture_protocol.md) | How to actually capture a room (Route 2 one-pager). |
| [05_device_matrix.md](05_device_matrix.md) | Which devices/OS/sensors each tier needs. |
| [06_compliance_matrix.md](06_compliance_matrix.md) | Every spec requirement -> where it's satisfied. |
| [07_benchmark_methodology.md](07_benchmark_methodology.md) | How the synthetic benchmark + gates + CI calibration were built. |
| [08_benchmark_report.md](08_benchmark_report.md) | The actual numbers. |
| [09_fix_loop.md](09_fix_loop.md) | Pointer/summary of the Part-4 fix-loop bundle. |
| [10_ui_ux_rendered_plan.md](10_ui_ux_rendered_plan.md) | Plan renderer design, incl. the damage-marker design choice. |
| [11_known_limitations.md](11_known_limitations.md) | Every disclosed gap, in one place. |
| [12_security_privacy.md](12_security_privacy.md) | Data sensitivity, local-only processing, OWASP-relevant notes. |
| [technical_report.md](technical_report.md) | <=6 page condensed submission writeup. |

## At a glance: what passed, what didn't

5 required benchmark gates, computed with real numbers against synthetic ground truth
([08_benchmark_report.md](08_benchmark_report.md), [benchmark/gate_results.json](../benchmark/gate_results.json)):

| Gate | Result |
|---|---|
| Opening width accuracy (>=85% within 2cm) | **FAIL** — 100% detection, 41.7% within 2cm (disclosed residual) |
| Ceiling height (<=1.5cm/room) | **FAIL** — 5/6 rooms <0.1mm error, 1 room (`repeat_room_b`) at 2.0cm |
| Repeatability (<=1cm or 0.5%/wall) | **PASS** |
| Drift ablation (corrected <=5cm, better than uncorrected) | **PASS** — 1.7-2.5cm corrected vs 84-216cm raw |
| Photo-tier whole-property stitch (+-8%, no overlaps) | **UNKNOWN** — honestly not computed, see limitations |

Nothing here is hidden or rounded away — every FAIL/UNKNOWN is root-caused and disclosed, not
smoothed over. This is deliberate: the case study explicitly scores honest disclosure of gaps
over confident fabrication.

Also measured (real captures, no synthetic ground truth available for these 2 tiers): video and
photo tier wall-length accuracy vs. the LiDAR tier on the same real room, both currently **miss**
their spec targets (video ±3%, photo ±8%) — see [08_benchmark_report.md](08_benchmark_report.md)
§5 for the exact numbers. This directly drove widening the photo tier's disclosed confidence
interval rather than leaving a falsely narrow one in place.
