"""Classical-CV damage detection: moisture stains (color-anomaly segmentation) and structural
cracks (edge-based elongated-shape segmentation). Operates purely in pixel space -- converting
to real-world area/extent (cozmoscan.types.DamageRegion) is the caller's job, since only the
caller knows the pixels-per-meter scale of a given surface photo.

No ML model is used: both detectors are deliberately simple, inspectable, classical-CV
heuristics so every detection can be explained ("flagged because color hue/saturation deviated
from the wall's own background by X" / "flagged because this edge contour has aspect ratio Y").
This trades recall on subtle/ambiguous real damage for being auditable and parameter-tunable
without retraining -- an explicit, disclosed tradeoff (see docs/11_known_limitations.md).
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class DamageDetection:
    """Raw detector output, pixel space only."""

    damage_class: str  # "moisture_stain" | "structural_crack"
    polygon_px: np.ndarray  # (K,2) pixel coords, closed contour
    area_px: float
    length_px: float  # characteristic length (perimeter/2 for thin shapes, 0 for blobs)
    confidence: float


@dataclass
class DamageDetectorConfig:
    min_stain_area_px: int = 900
    stain_hue_tolerance: int = 18  # +/- degrees (OpenCV 0-179 scale) from background hue
    stain_min_saturation_delta: float = 14.0
    stain_min_value_delta: float = 6.0

    canny_lo: int = 40
    canny_hi: int = 120
    crack_dilate_px: int = 3
    min_crack_length_px: int = 80
    min_crack_aspect_ratio: float = 4.0
    max_crack_width_px: float = 45.0


def detect_moisture_stains(bgr: np.ndarray, cfg: DamageDetectorConfig | None = None) -> list[DamageDetection]:
    """Flags pixels whose hue/saturation/value deviate from the image's own dominant
    (background wall) color -- a color-anomaly approach rather than fixed absolute HSV
    thresholds, so it isn't tied to one specific wall paint color."""
    cfg = cfg or DamageDetectorConfig()
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV).astype(np.float64)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]

    bg_h = float(np.median(h))
    bg_s = float(np.median(s))
    bg_v = float(np.median(v))

    hue_diff = np.minimum(np.abs(h - bg_h), 180 - np.abs(h - bg_h))
    sat_diff = s - bg_s  # stains are typically *more* saturated than a plain painted wall
    val_diff = bg_v - v  # stains are typically *darker* than the surrounding wall

    anomaly = (
        (hue_diff <= cfg.stain_hue_tolerance)
        & (sat_diff >= cfg.stain_min_saturation_delta)
        & (val_diff >= cfg.stain_min_value_delta)
    )
    mask = (anomaly.astype(np.uint8)) * 255
    kernel = np.ones((7, 7), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    out = []
    for c in contours:
        area = cv2.contourArea(c)
        if area < cfg.min_stain_area_px:
            continue
        region_mask = np.zeros(mask.shape, dtype=np.uint8)
        cv2.drawContours(region_mask, [c], -1, 255, -1)
        region_sat_delta = float(np.mean(sat_diff[region_mask > 0]))
        confidence = float(np.clip(region_sat_delta / (cfg.stain_min_saturation_delta * 3), 0.2, 0.95))
        simplified = cv2.approxPolyDP(c, epsilon=0.005 * cv2.arcLength(c, True), closed=True)
        out.append(
            DamageDetection(
                damage_class="moisture_stain",
                polygon_px=simplified.reshape(-1, 2),
                area_px=float(area),
                length_px=0.0,
                confidence=confidence,
            )
        )
    return out


def detect_cracks(bgr: np.ndarray, cfg: DamageDetectorConfig | None = None) -> list[DamageDetection]:
    """Canny edges + elongated/thin-shape filtering (via minAreaRect aspect ratio) to tell a
    crack apart from furniture edges, corners, and other straight lines a plain Canny pass
    would also pick up."""
    cfg = cfg or DamageDetectorConfig()
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, cfg.canny_lo, cfg.canny_hi)
    kernel = np.ones((cfg.crack_dilate_px, cfg.crack_dilate_px), np.uint8)
    dilated = cv2.dilate(edges, kernel, iterations=1)

    contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    out = []
    for c in contours:
        if len(c) < 5:
            continue
        (_, _), (w, h), _ = cv2.minAreaRect(c)
        long_side, short_side = max(w, h), max(min(w, h), 1e-6)
        aspect = long_side / short_side
        if aspect < cfg.min_crack_aspect_ratio or long_side < cfg.min_crack_length_px:
            continue
        if short_side > cfg.max_crack_width_px:
            continue
        perimeter = cv2.arcLength(c, closed=True)
        length_px = perimeter / 2.0  # a thin line's contour wraps both sides, so perimeter ~= 2x length
        confidence = float(np.clip(aspect / (cfg.min_crack_aspect_ratio * 3), 0.2, 0.9))
        simplified = cv2.approxPolyDP(c, epsilon=0.005 * perimeter, closed=True)
        out.append(
            DamageDetection(
                damage_class="structural_crack",
                polygon_px=simplified.reshape(-1, 2),
                area_px=float(cv2.contourArea(c)),
                length_px=float(length_px),
                confidence=confidence,
            )
        )
    return out


def detect_damage(bgr: np.ndarray, cfg: DamageDetectorConfig | None = None) -> list[DamageDetection]:
    """Runs both detectors. Order matters only for readability; the two use disjoint cues
    (color-anomaly vs. thin-edge-shape) so they rarely double-fire on the same real pixels."""
    cfg = cfg or DamageDetectorConfig()
    return detect_moisture_stains(bgr, cfg) + detect_cracks(bgr, cfg)


def to_damage_region(detection: DamageDetection, surface_id: str, pixels_per_meter: float):
    """Converts a pixel-space DamageDetection into a real-world cozmoscan.types.DamageRegion,
    given the photo's pixels-per-meter scale (derived by the caller from the surface's known
    wall length, same ground-plane-photo assumption used by the photo tier)."""
    from cozmoscan.types import DamageRegion

    polygon_xy = detection.polygon_px.astype(np.float64) / pixels_per_meter
    return DamageRegion(
        damage_class=detection.damage_class,
        surface_id=surface_id,
        polygon_xy=polygon_xy,
        area_m2=detection.area_px / (pixels_per_meter**2),
        confidence=detection.confidence,
        extent_m=(detection.length_px / pixels_per_meter) if detection.length_px > 0 else None,
    )
