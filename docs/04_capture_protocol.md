# 04 — Capture Protocol (Route 2: stock capture app)

The spec offers two routes: **Route 1** (a custom-built iOS app, distributed via TestFlight) or
**Route 2** (a documented protocol using an existing stock capture app). This submission uses
**Route 2**. This sandbox has no physical iPhone/iPad, no Mac, and no Xcode available, so
building and signing a custom iOS app (Route 1) was not possible here — that is disclosed as
future work in [11_known_limitations.md](11_known_limitations.md), not silently skipped.

## The app: Stray Scanner

[Stray Scanner](https://docs.strayrobots.io/apps/scanner/overview.html) (Stray Robots) — free,
App Store, source referenced in its own docs. Exports per-frame RGB video, depth, ARKit
confidence, 6-DoF poses, and camera intrinsics to a self-contained folder. This is a real,
independently-verifiable choice, not a hypothetical: the 3 sample captures provided with this
case study (`Sample_data_to_run_code/*.zip`) are themselves genuine Stray Scanner exports,
confirmed by inspecting their file format directly (`<hash>/{camera_matrix.csv, odometry.csv,
imu.csv, rgb.mp4, depth/*.png, confidence/*.png}`).

Install: App Store -> search "Stray Scanner" -> install (free) -> grant camera permission.

## Capture steps, per tier

All 3 tiers are captured with **the same app, the same way** — the tier distinction is in what
the pipeline *uses* from the export afterward (depth+confidence for LiDAR, pose+RGB only for
Video, a handful of RGB stills only for Photo), not a different capture motion. This is
deliberate: it lets all 3 tiers be exercised from one real capture session.

1. Open Stray Scanner, tap record, and walk a slow, steady loop around the room perimeter,
   keeping the camera at roughly chest/eye height and tilted slightly down-and-level (not
   pointed at the floor or ceiling the whole time).
2. Cover **every wall** at a roughly perpendicular angle at some point in the walk (grazing-
   angle-only coverage of a wall is the single biggest driver of sparse/noisy reconstruction —
   see [11_known_limitations.md](11_known_limitations.md)).
3. Pause briefly (1-2 seconds, standing still) facing each doorway/window so there's dense,
   stable coverage of every opening — this directly improves opening width accuracy.
4. Briefly tilt up to capture the ceiling line and down to capture the floor line, at least once
   each, if ceiling height is wanted (the pipeline degrades gracefully — `ceiling_height: null` +
   a note — if this is skipped, rather than guessing).
5. Stop recording. Export/share the capture folder (Stray Scanner's own share/export flow) to
   get it onto the machine running `cozmoscan`.
6. For **damage close-ups**: separately, take one or more focused stills of the specific damaged
   surface (any camera app is fine — these are supplied to `cozmoscan scan` independently via
   `--damage-manifest`, see README). Each needs a known `pixels_per_meter` scale for that photo —
   easiest in practice is to include a reference object of known size (e.g. a sheet of letter/A4
   paper, a tape measure) in frame, or to know the exact camera-to-surface distance and field of
   view and compute it from that.

## Practical tips

- Walk pace: slow and steady beats fast — motion blur and large inter-frame baselines both hurt
  the video/photo tiers' feature tracking more than the LiDAR tier (which has depth either way).
- Avoid walking in a perfectly straight line end-to-end; a loop or S-path gives better multi-view
  triangulation geometry for the video tier (more varied viewing angles per point).
- Avoid glass, mirrors, and glossy surfaces where possible — these are classic LiDAR/ARKit
  failure modes (multipath reflections), independent of this pipeline's own algorithms.
- Good, even lighting helps the photo tier's Hough line detection (floor/ceiling boundary) and
  the damage detectors' color-anomaly and edge-based detection alike.
- For multi-room properties: capture each room as its own separate Stray Scanner session (one
  `cozmoscan scan` per room, per the one-command-per-capture requirement), then supply the
  physical adjacency (`Connector`) and each room's approximate global placement
  (`RoomPlacement`) to `cozmoscan stitch` — see README for the exact JSON shapes.

## Route 1 (disclosed future work, not built here)

A native iOS app (ARKit + `AVFoundation`/`ARSession` capture, distributed via TestFlight) would
remove the manual export/share step and could add live in-app capture guidance (e.g. "wall not
yet covered" overlays). Not built in this submission due to no Mac/Xcode access in this sandbox.
The capture *data format* this pipeline already consumes (posed RGB + optional depth +
intrinsics) is exactly what such an app would need to produce, so a future Route 1 app would
need no changes to `cozmoscan/capture/*` or anything downstream — only a new capture-time UI.
