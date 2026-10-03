# 05 - Device Matrix

All 3 tiers are captured with the same app ([Stray Scanner](https://docs.strayrobots.io/apps/scanner/overview.html),
see [04_capture_protocol.md](04_capture_protocol.md)) - the device requirement differs because
the LiDAR tier needs the LiDAR sensor itself, while Video/Photo only need ARKit's standard
visual-inertial odometry (VIO), which is far more widely available.

| Tier | Minimum device | OS | Required sensors | Notes |
|---|---|---|---|---|
| **LiDAR** | iPhone 12 Pro or later **Pro/Pro Max** model, or iPad Pro (2020 or later) | iOS/iPadOS 13+ | LiDAR scanner + rear camera + ARKit | Only Pro-line iPhones and Pro iPads have the LiDAR sensor Stray Scanner's depth export depends on. |
| **Video** | Any iPhone 6s or later (non-Pro OK) | iOS 13+ | Rear camera + ARKit (VIO pose) | No LiDAR needed - the pipeline deliberately discards depth/confidence even on a Pro device to validate this tier honestly (see [03_algorithms.md](03_algorithms.md)). |
| **Photo** | Any iPhone (or in principle any camera) | iOS 13+ for the current capture path | Rear camera | Current implementation samples stills **from a Stray Scanner video capture**, not from an arbitrary loose photo folder - see [11_known_limitations.md](11_known_limitations.md) for this disclosed scope gap. |

## Capture app

| | |
|---|---|
| App | Stray Scanner |
| Publisher | Stray Robots |
| Cost | Free |
| Distribution | Public App Store listing |
| Data exported | `rgb.mp4` (video), per-frame `depth/*.png` (16-bit mm, 256x192), per-frame `confidence/*.png` (ARKit confidence 0/1/2), `odometry.csv` (per-frame 6-DoF pose + per-frame RGB intrinsics), `camera_matrix.csv` (RGB intrinsics), `imu.csv` (raw accel/gyro, currently unused by this pipeline) |

## Host machine (running `cozmoscan` itself)

No specific hardware requirement beyond a working Python 3.11+ environment - this is pure
CPU-based classical CV/geometry (numpy/scipy/opencv/matplotlib), no GPU and no model downloads
required. Verified working on Windows with Python 3.13.15 (see [README.md](../README.md) for the
exact setup commands).
