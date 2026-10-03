# Cozmo Scan - Applied AI Engineer Case Study Submission

A dimensioned floor-plan + damage-scope reconstruction pipeline from handheld iPhone capture
(Photo / Video / LiDAR tiers), built end-to-end for
[Applied_AI_Case_Study.pdf](Applied_AI_Case_Study.pdf). One command per capture, pure Python,
no network calls, no cloud, runs cold on any new capture folder.

**Start here:** [docs/00_overview.md](docs/00_overview.md) for the full repo map, or
[docs/technical_report.md](docs/technical_report.md) for the condensed (<=6 page) submission
writeup if you only read one thing.

## Setup (fresh clone to first scan, <15 minutes)

```powershell
# 1. Create a venv and install dependencies (~1 min)
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 2. Place the 3 provided sample-data zips in Sample_data_to_run_code/, then extract them
#    (see Sample_data_to_run_code/README.md for the fast .NET extraction method - ~1 min)

# 3. Scan a room - one command, any tier
.\.venv\Scripts\python.exe -m cozmoscan.cli scan `
    --capture-dir "Sample_data_to_run_code/single_room" --tier lidar `
    --room-id living_room --out out/living_room
```

That's it - `out/living_room/result.json` (schema-validated) and `out/living_room/plan.png`
(rendered floor plan) now exist. Swap `--tier lidar` for `--tier video` or `--tier photo` to run
the same command against the other two tiers; swap `--capture-dir` for any other Stray-Scanner-
format capture folder, including a brand-new one captured live.

## One command per capture

```powershell
# Scan, with optional damage photos + surface metadata
python -m cozmoscan.cli scan --capture-dir <dir> --tier {lidar,video,photo} --room-id <id> --out <out-dir> `
    [--damage-manifest damage_manifest.json] [--surface-tags surface_tags.json]

# Stitch >=2 already-scanned rooms into one property (separate command: it inherently needs
# more than one capture's output as input, so it cannot itself be "per capture")
python -m cozmoscan.cli stitch --rooms <room1>/result.json <room2>/result.json `
    --connectors connectors.json --placements placements.json --out <out-dir> [--no-drift-correction]
```

Run `python -m cozmoscan.cli scan --help` / `stitch --help` for the full flag reference.

## Reproduce every reported number

Nothing in this submission's docs/report is hand-typed - every number comes from a committed,
runnable script against committed or regenerable inputs:

```powershell
python -m benchmark.generate_synthetic_benchmark   # regenerate the 6-room synthetic ground truth
python -m benchmark.generate_damage_images          # regenerate the 2 staged-damage images
python -m benchmark.gates                           # the 5 required gates -> benchmark/gate_results.json
python -m benchmark.calibrate_ci                     # ci_k calibration -> benchmark/ci_calibration.json
python -m benchmark.real_data_report                 # real-capture timing + cross-tier accuracy
python -m fix_loop.run_fix_loop                      # Part-4 fix-loop before/after -> fix_loop/*.json, diff.md
python -m benchmark.head_to_head --cozmo <f> --consumer <f> --ground-truth <f>   # Part-3, once real captures exist
```

## Dependencies

Pinned in [requirements.txt](requirements.txt): `numpy`, `pillow`, `opencv-python-headless`,
`scipy`, `matplotlib`, `jsonschema`, `imageio[ffmpeg]`. No pretrained models, no external APIs, no
network calls anywhere in `cozmoscan/` (verified by grep, see
[docs/12_security_privacy.md](docs/12_security_privacy.md)).

## Repo map

See [docs/00_overview.md](docs/00_overview.md) for the full table. Short version:
`cozmoscan/` is the pipeline package, `schema/` the published JSON Schemas, `benchmark/` the
self-built synthetic ground truth + required gates + calibration + real-data report,
`fix_loop/` the Part-4 deliverable, `docs/` this submission's full writeup (architecture, data
model, algorithms, capture protocol, device matrix, compliance matrix, benchmark report, fix
loop, known limitations, security/privacy, technical report).

## Honesty, not polish, is the design goal

Every gate result, every confidence interval, and every limitation in this submission is measured
and disclosed, not rounded away - see [docs/11_known_limitations.md](docs/11_known_limitations.md)
for the complete list (16 items) and [docs/06_compliance_matrix.md](docs/06_compliance_matrix.md)
for exactly where every spec requirement is (or isn't yet) satisfied.
