# Sample Data

This folder holds the raw sample captures provided with the case study, plus the self-built
synthetic benchmark. The 3 real captures (and their source zips) are **not** committed to git -
only the synthetic benchmark's ground truth + 2 staged-damage images are (see `.gitignore`: the
zips and their extracted folders are excluded, as is every `.npz` point cloud, due to size).

## 1. Place the provided zips here

Copy the 3 provided archives into this folder:

```
Sample_data_to_run_code/
 single_room.zip
 single_scan_floor_only.zip
 single_scan_with_ceiling.zip
```

## 2. Extract them (fast method - not PowerShell's `Expand-Archive`)

`Expand-Archive` is noticeably slow on archives with many small files (these captures are frame
sequences - hundreds of files each). Use .NET's `ZipFile` directly instead:

```powershell
Add-Type -AssemblyName System.IO.Compression.FileSystem
foreach ($name in @("single_room", "single_scan_floor_only", "single_scan_with_ceiling")) {
   [System.IO.Compression.ZipFile]::ExtractToDirectory("$name.zip", $name)
}
```

This should produce `single_room/`, `single_scan_floor_only/`, and `single_scan_with_ceiling/`,
each a Stray Scanner capture folder (RGB video + depth frames + odometry/poses + camera
intrinsics). See [docs/04_capture_protocol.md](../docs/04_capture_protocol.md) for the exact
folder format and [docs/05_device_matrix.md](../docs/05_device_matrix.md) for what each tier
needs from it.

## 3. Regenerate the synthetic benchmark (optional - already committed, but fully regenerable)

The `synthetic_benchmark/` subfolder (6 rooms with known ground truth, used by all 5 required
gates) is generated from code, not hand-authored. Only `ground_truth.json` and the 2 staged
damage-room images are committed (the `.npz` point clouds are regenerated, not stored, due to
size). To regenerate everything from scratch:

```powershell
python -m benchmark.generate_synthetic_benchmark
python -m benchmark.generate_damage_images
```

See [docs/07_benchmark_methodology.md](../docs/07_benchmark_methodology.md) for exactly how this
generator works and why it's deliberately sparse/occluded rather than a convenient dense cloud.

## Final expected layout

```
Sample_data_to_run_code/
 single_room/                      (from the provided zip)
 single_scan_floor_only/           (from the provided zip)
 single_scan_with_ceiling/         (from the provided zip)
 synthetic_benchmark/
   ground_truth.json               (committed)
   damage_room/
     damage_ground_truth.json      (committed)
     damage_photo_stain.png        (committed)
     damage_photo_crack.png        (committed)
   repeat_room_a/points.npz        (regenerated, not committed)
   repeat_room_b/points.npz        (regenerated, not committed)
   living_room/points.npz          (regenerated, not committed)
   hallway/points.npz              (regenerated, not committed)
   bedroom/points.npz              (regenerated, not committed)
   den/points.npz                  (regenerated, not committed)
```
