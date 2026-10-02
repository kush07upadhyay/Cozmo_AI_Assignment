"""Generate 2 staged-damage photo crops (moisture stain + structural crack) with exact
pixel-ground-truth polygons, used to validate cozmoscan.damage.detector against known answers.

These are procedurally drawn, not photographs -- disclosed as synthetic throughout. They are
good enough to validate the *segmentation logic* (color/shape discrimination) even though they
can't capture every real-world lighting/texture variation a photograph would.
"""
from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np

OUT_DIR = Path("Sample_data_to_run_code/synthetic_benchmark/damage_room")
PIXELS_PER_METER = 250.0
IMG_W, IMG_H = 1000, 800


def _wall_background(rng: np.random.Generator) -> np.ndarray:
    base = np.full((IMG_H, IMG_W, 3), (214, 219, 222), dtype=np.uint8)  # light warm-gray, BGR
    noise = rng.normal(0, 4.0, size=(IMG_H, IMG_W, 3))
    img = np.clip(base.astype(np.float64) + noise, 0, 255).astype(np.uint8)
    return img


def _draw_moisture_stain(img: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    mask = np.zeros((IMG_H, IMG_W), dtype=np.uint8)
    cx, cy = rng.integers(300, 500), rng.integers(250, 400)
    for _ in range(9):
        r = rng.integers(35, 70)
        ox, oy = rng.integers(-60, 60), rng.integers(-60, 60)
        cv2.circle(mask, (cx + ox, cy + oy), r, 255, -1)
    mask = cv2.GaussianBlur(mask, (31, 31), 0)
    mask = (mask > 80).astype(np.uint8) * 255

    stain_color = np.array([70, 105, 135], dtype=np.float64)  # brownish-yellow, BGR
    alpha = cv2.GaussianBlur(mask, (41, 41), 0).astype(np.float64) / 255.0 * 0.55
    for c in range(3):
        img[:, :, c] = (img[:, :, c] * (1 - alpha) + stain_color[c] * alpha).astype(np.uint8)
    return mask


def _draw_crack(img: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    mask = np.zeros((IMG_H, IMG_W), dtype=np.uint8)
    x, y = rng.integers(600, 700), rng.integers(80, 150)
    pts = [(x, y)]
    for _ in range(40):
        x += rng.integers(-6, 10)
        y += rng.integers(8, 20)
        x = int(np.clip(x, 20, IMG_W - 20))
        y = int(np.clip(y, 0, IMG_H - 20))
        pts.append((x, y))
    for i in range(len(pts) - 1):
        thickness = int(rng.integers(2, 4))
        cv2.line(mask, pts[i], pts[i + 1], 255, thickness)
        cv2.line(img, pts[i], pts[i + 1], (40, 40, 42), thickness)
    return mask


def _mask_to_ground_truth(mask: np.ndarray, damage_class: str) -> dict:
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    largest = max(contours, key=cv2.contourArea)
    area_px = float(cv2.contourArea(largest))
    polygon_px = largest.reshape(-1, 2).tolist()
    return {
        "damage_class": damage_class,
        "polygon_px": polygon_px,
        "area_m2": round(area_px / (PIXELS_PER_METER**2), 4),
        "pixels_per_meter": PIXELS_PER_METER,
    }


def main():
    rng = np.random.default_rng(42)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    stain_img = _wall_background(rng)
    stain_mask = _draw_moisture_stain(stain_img, rng)
    cv2.imwrite(str(OUT_DIR / "damage_photo_stain.png"), stain_img)
    gt_stain = _mask_to_ground_truth(stain_mask, "moisture_stain")

    crack_img = _wall_background(rng)
    crack_mask = _draw_crack(crack_img, rng)
    cv2.imwrite(str(OUT_DIR / "damage_photo_crack.png"), crack_img)
    gt_crack = _mask_to_ground_truth(crack_mask, "structural_crack")

    with open(OUT_DIR / "damage_ground_truth.json", "w") as f:
        json.dump(
            {
                "pixels_per_meter": PIXELS_PER_METER,
                "images": {
                    "damage_photo_stain.png": gt_stain,
                    "damage_photo_crack.png": gt_crack,
                },
            },
            f,
            indent=2,
        )
    print(f"Wrote staged damage images + ground truth to {OUT_DIR}")


if __name__ == "__main__":
    main()
